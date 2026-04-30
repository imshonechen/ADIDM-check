import html
import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime

import requests

from app.formatters import format_filesize
from app.models import (
    get_latest_version,
    get_setting,
    get_settings,
    get_telegram_message_by_id,
    get_telegram_message_by_version_target,
    get_telegram_messages,
    get_version_by_id,
    get_version_by_version_str,
    set_setting,
    update_telegram_message_state,
    update_version,
    upsert_telegram_message,
)
from app.translator import translate_changelog

logger = logging.getLogger(__name__)
_polling_thread = None

TELEGRAM_SETTING_KEYS = (
    'telegram_bot_token',
    'telegram_bot_chat_id',
    'telegram_channel_chat_id',
    'telegram_notify_bot_enabled',
    'telegram_notify_channel_enabled',
    'telegram_commands_enabled',
    'telegram_admin_user_ids',
    'telegram_admin_chat_ids',
)


def get_telegram_settings(db_path):
    settings = get_settings(db_path, TELEGRAM_SETTING_KEYS)
    return {
        'bot_token': settings.get('telegram_bot_token') or '',
        'bot_chat_id': settings.get('telegram_bot_chat_id') or '',
        'channel_chat_id': settings.get('telegram_channel_chat_id') or '',
        'notify_bot_enabled': settings.get('telegram_notify_bot_enabled') == '1',
        'notify_channel_enabled': settings.get('telegram_notify_channel_enabled') == '1',
        'commands_enabled': settings.get('telegram_commands_enabled') == '1',
        'admin_user_ids': settings.get('telegram_admin_user_ids') or '',
        'admin_chat_ids': settings.get('telegram_admin_chat_ids') or '',
    }


def notify_new_version(db_path, version_data, timeout):
    settings = get_telegram_settings(db_path)
    bot_token = settings['bot_token']
    if not bot_token:
        return {'sent': False, 'message': 'Telegram Bot Token 未配置'}

    targets = []
    if settings['notify_bot_enabled'] and settings['bot_chat_id']:
        targets.append(('bot', settings['bot_chat_id']))
    if settings['notify_channel_enabled'] and settings['channel_chat_id']:
        targets.append(('channel', settings['channel_chat_id']))

    if not targets:
        return {'sent': False, 'message': 'Telegram 转发目标未启用'}

    results = []
    version_id = version_data.get('id') or _resolve_version_id(db_path, version_data)
    for target_type, chat_id in targets:
        ok, message, payload = send_version_to_target(
            db_path, bot_token, chat_id, target_type, version_data, timeout
        )
        results.append({
            'target': target_type,
            'chat_id': chat_id,
            'ok': ok,
            'message': message,
            'mode': payload.get('mode'),
        })
        if version_id:
            upsert_telegram_message(db_path, {
                'version_id': version_id,
                'target_type': target_type,
                'chat_id': chat_id,
                'message_id': payload.get('message_id'),
                'mode': payload.get('mode') or 'message',
                'text': payload.get('text') or '',
                'content_hash': content_hash(payload.get('text') or ''),
                'status': 'sent' if ok else 'failed',
                'last_error': None if ok else message,
            })

    set_setting(db_path, 'telegram_last_notify_status', 'success' if all(r['ok'] for r in results) else 'partial_failed')
    return {'sent': any(r['ok'] for r in results), 'results': results}


def send_test_message(db_path, target, timeout):
    settings = get_telegram_settings(db_path)
    bot_token = settings['bot_token']
    if not bot_token:
        return False, 'Telegram Bot Token 未配置'

    chat_id = settings['channel_chat_id'] if target == 'channel' else settings['bot_chat_id']
    if not chat_id:
        return False, 'Telegram Chat ID 未配置'

    text = '<b>ADIDM-Check 测试消息</b>\nTelegram 转发配置已连通。'
    ok, message, _ = send_message(bot_token, chat_id, text, timeout)
    return ok, message


def send_version_to_target(db_path, bot_token, chat_id, target_type, version_data, timeout):
    file_path = get_download_file_path(db_path, version_data.get('filename'))
    if file_path:
        text = build_version_message(version_data, max_changelog=300)
        ok, message, payload = send_document(bot_token, chat_id, file_path, text, timeout)
        payload.update({'mode': 'document', 'text': trim_caption(text)})
    else:
        text = build_version_message(version_data)
        ok, message, payload = send_message(bot_token, chat_id, text, timeout)
        payload.update({'mode': 'message', 'text': text})
    return ok, message, payload


def send_text_to_target(db_path, bot_token, chat_id, target_type, version_data, text, timeout):
    file_path = get_download_file_path(db_path, version_data.get('filename'))
    if file_path:
        ok, message, payload = send_document(bot_token, chat_id, file_path, text, timeout)
        payload.update({'mode': 'document', 'text': trim_caption(text)})
    else:
        ok, message, payload = send_message(bot_token, chat_id, text, timeout)
        payload.update({'mode': 'message', 'text': text})
    return ok, message, payload


def build_version_message(version_data, max_changelog=1200):
    lines = [
        '<b>ADIDM-Check 检测到新版本</b>',
        f"版本：<code>{_escape(version_data.get('version'))}</code>",
    ]
    if version_data.get('filename'):
        lines.append(f"文件名：<code>{_escape(version_data.get('filename'))}</code>")
    if version_data.get('filesize'):
        lines.append(f"大小：<code>{_escape(format_filesize(version_data.get('filesize')))}</code>")
    if version_data.get('sha256'):
        lines.append(f"SHA256：<code>{_escape(version_data.get('sha256'))}</code>")
    if version_data.get('download_url'):
        lines.append(f"下载地址：{_escape(version_data.get('download_url'))}")
    if version_data.get('direct_url'):
        lines.append(f"直连地址：{_escape(version_data.get('direct_url'))}")
    changelog_source = version_data.get('changelog_zh') or version_data.get('changelog')
    if changelog_source:
        changelog = changelog_source
        if len(changelog) > max_changelog:
            changelog = changelog[:max_changelog] + '...'
        lines.append('')
        lines.append('<b>更新日志</b>')
        lines.append(_escape(changelog))
    return '\n'.join(lines)


def send_message(bot_token, chat_id, text, timeout):
    api_url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    try:
        resp = requests.post(api_url, json={
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }, timeout=timeout)
        data = resp.json()
    except requests.RequestException as e:
        logger.warning(f'Failed to send Telegram message: {e}')
        return False, str(e), {}
    except ValueError as e:
        logger.warning(f'Invalid Telegram response: {e}')
        return False, 'Telegram 返回格式异常', {}

    if not resp.ok or not data.get('ok'):
        description = data.get('description', f'HTTP {resp.status_code}')
        logger.warning(f'Failed to send Telegram message: {description}')
        return False, description, {}

    return True, '发送成功', {'message_id': data.get('result', {}).get('message_id')}


def send_document(bot_token, chat_id, file_path, caption, timeout):
    api_url = f'https://api.telegram.org/bot{bot_token}/sendDocument'
    try:
        with open(file_path, 'rb') as document:
            resp = requests.post(api_url, data={
                'chat_id': chat_id,
                'caption': trim_caption(caption),
                'parse_mode': 'HTML',
            }, files={'document': (os.path.basename(file_path), document)}, timeout=timeout)
        data = resp.json()
    except OSError as e:
        logger.warning(f'Failed to read Telegram document: {e}')
        return False, str(e), {}
    except requests.RequestException as e:
        logger.warning(f'Failed to send Telegram document: {e}')
        return False, str(e), {}
    except ValueError as e:
        logger.warning(f'Invalid Telegram document response: {e}')
        return False, 'Telegram 返回格式异常', {}

    if not resp.ok or not data.get('ok'):
        description = data.get('description', f'HTTP {resp.status_code}')
        logger.warning(f'Failed to send Telegram document: {description}')
        return False, description, {}

    return True, '文件发送成功', {'message_id': data.get('result', {}).get('message_id')}


def edit_message(bot_token, chat_id, message_id, mode, text, timeout):
    if mode == 'document':
        api_method = 'editMessageCaption'
        body = {
            'chat_id': chat_id,
            'message_id': message_id,
            'caption': trim_caption(text),
            'parse_mode': 'HTML',
        }
    else:
        api_method = 'editMessageText'
        body = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': text,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }
    return telegram_post(bot_token, api_method, body, timeout)


def delete_message(bot_token, chat_id, message_id, timeout):
    return telegram_post(bot_token, 'deleteMessage', {
        'chat_id': chat_id,
        'message_id': message_id,
    }, timeout)


def telegram_post(bot_token, api_method, body, timeout):
    try:
        resp = requests.post(f'https://api.telegram.org/bot{bot_token}/{api_method}',
                             json=body, timeout=timeout)
        data = resp.json()
    except requests.RequestException as e:
        logger.warning(f'Failed to call Telegram {api_method}: {e}')
        return False, str(e)
    except ValueError as e:
        logger.warning(f'Invalid Telegram {api_method} response: {e}')
        return False, 'Telegram 返回格式异常'

    if not resp.ok or not data.get('ok'):
        description = data.get('description', f'HTTP {resp.status_code}')
        logger.warning(f'Failed Telegram {api_method}: {description}')
        return False, description
    return True, '操作成功'


def send_version_message(db_path, version_id, target_type, timeout):
    settings = get_telegram_settings(db_path)
    bot_token = settings['bot_token']
    if not bot_token:
        return False, 'Telegram Bot Token 未配置', None

    chat_id = _chat_id_for_target(settings, target_type)
    if not chat_id:
        return False, 'Telegram Chat ID 未配置', None

    version = get_version_by_id(db_path, version_id)
    if not version:
        return False, '版本记录不存在', None

    ok, message, payload = send_version_to_target(db_path, bot_token, chat_id, target_type, version, timeout)
    row_id = upsert_telegram_message(db_path, {
        'version_id': version_id,
        'target_type': target_type,
        'chat_id': chat_id,
        'message_id': payload.get('message_id'),
        'mode': payload.get('mode') or 'message',
        'text': payload.get('text') or '',
        'content_hash': content_hash(payload.get('text') or ''),
        'status': 'sent' if ok else 'failed',
        'last_error': None if ok else message,
    })
    return ok, message, row_id


def send_version_message_text(db_path, version_id, target_type, text, timeout):
    settings = get_telegram_settings(db_path)
    bot_token = settings['bot_token']
    if not bot_token:
        return False, 'Telegram Bot Token 未配置', None

    chat_id = _chat_id_for_target(settings, target_type)
    if not chat_id:
        return False, 'Telegram Chat ID 未配置', None

    version = get_version_by_id(db_path, version_id)
    if not version:
        return False, '版本记录不存在', None

    ok, message, payload = send_text_to_target(db_path, bot_token, chat_id, target_type, version, text, timeout)
    row_id = upsert_telegram_message(db_path, {
        'version_id': version_id,
        'target_type': target_type,
        'chat_id': chat_id,
        'message_id': payload.get('message_id'),
        'mode': payload.get('mode') or 'message',
        'text': payload.get('text') or '',
        'content_hash': content_hash(payload.get('text') or ''),
        'status': 'sent' if ok else 'failed',
        'last_error': None if ok else message,
    })
    return ok, message, row_id


def edit_tracked_message(db_path, tracked_id, text, timeout):
    row = get_telegram_message_by_id(db_path, tracked_id)
    if not row:
        return False, '消息记录不存在'
    settings = get_telegram_settings(db_path)
    if not settings['bot_token']:
        return False, 'Telegram Bot Token 未配置'
    if not row.get('message_id'):
        update_telegram_message_state(db_path, tracked_id, 'failed', 'Telegram Message ID 缺失')
        return False, 'Telegram Message ID 缺失'

    stored_text = trim_caption(text) if row['mode'] == 'document' else text
    ok, message = edit_message(settings['bot_token'], row['chat_id'], row['message_id'],
                               row['mode'], stored_text, timeout)
    if ok or _is_not_modified(message):
        update_telegram_message_state(db_path, tracked_id, 'edited', None,
                                      text=stored_text, content_hash=content_hash(stored_text))
        return True, '编辑成功'

    status = 'missing' if _looks_missing(message) else 'failed'
    update_telegram_message_state(db_path, tracked_id, status, message)
    return False, message


def sync_tracked_message(db_path, tracked_id, timeout):
    row = get_telegram_message_by_id(db_path, tracked_id)
    if not row:
        return False, '消息记录不存在'
    text = build_version_message(row, max_changelog=300 if row['mode'] == 'document' else 1200)
    return edit_tracked_message(db_path, tracked_id, text, timeout)


def delete_tracked_message(db_path, tracked_id, timeout):
    row = get_telegram_message_by_id(db_path, tracked_id)
    if not row:
        return False, '消息记录不存在'
    settings = get_telegram_settings(db_path)
    if not settings['bot_token']:
        return False, 'Telegram Bot Token 未配置'
    if not row.get('message_id'):
        update_telegram_message_state(db_path, tracked_id, 'missing', 'Telegram Message ID 缺失')
        return False, 'Telegram Message ID 缺失'

    ok, message = delete_message(settings['bot_token'], row['chat_id'], row['message_id'], timeout)
    if ok:
        update_telegram_message_state(
            db_path, tracked_id, 'deleted', None,
            deleted_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
        return True, '删除成功'

    status = 'missing' if _looks_missing(message) else 'failed'
    update_telegram_message_state(db_path, tracked_id, status, message)
    return False, message


def resend_tracked_message(db_path, tracked_id, timeout):
    row = get_telegram_message_by_id(db_path, tracked_id)
    if not row:
        return False, '消息记录不存在'
    settings = get_telegram_settings(db_path)
    if not settings['bot_token']:
        return False, 'Telegram Bot Token 未配置'
    version = get_version_by_id(db_path, row['version_id'])
    if not version:
        return False, '版本记录不存在'

    ok, message, payload = send_version_to_target(
        db_path, settings['bot_token'], row['chat_id'], row['target_type'], version, timeout
    )
    update_telegram_message_state(
        db_path, tracked_id, 'sent' if ok else 'failed', None if ok else message,
        text=payload.get('text') or '', content_hash=content_hash(payload.get('text') or ''),
        telegram_message_id=payload.get('message_id')
    )
    return ok, message


def resend_tracked_message_text(db_path, tracked_id, text, timeout):
    row = get_telegram_message_by_id(db_path, tracked_id)
    if not row:
        return False, '消息记录不存在'
    settings = get_telegram_settings(db_path)
    if not settings['bot_token']:
        return False, 'Telegram Bot Token 未配置'
    version = get_version_by_id(db_path, row['version_id'])
    if not version:
        return False, '版本记录不存在'

    ok, message, payload = send_text_to_target(
        db_path, settings['bot_token'], row['chat_id'], row['target_type'], version, text, timeout
    )
    update_telegram_message_state(
        db_path, tracked_id, 'sent' if ok else 'failed', None if ok else message,
        text=payload.get('text') or '', content_hash=content_hash(payload.get('text') or ''),
        telegram_message_id=payload.get('message_id')
    )
    return ok, message


def trim_caption(caption):
    if len(caption) <= 1000:
        return caption
    lines = caption.splitlines()
    while lines and len('\n'.join(lines)) > 1000:
        lines.pop()
    trimmed = '\n'.join(lines)
    if trimmed:
        return trimmed
    return '<b>ADIDM-Check 检测到新版本</b>'


def get_download_file_path(db_path, filename):
    if not filename:
        return None
    download_dir = os.path.join(os.path.dirname(db_path), 'downloads')
    file_path = os.path.join(download_dir, filename)
    if os.path.exists(file_path):
        return file_path
    return None


def _escape(value):
    return html.escape(str(value or ''), quote=False)


def content_hash(text):
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()


def get_message_status_label(status):
    labels = {
        'sent': '已发送',
        'edited': '已编辑',
        'deleted': '已删除',
        'missing': '远端可能已删除',
        'failed': '操作失败',
    }
    return labels.get(status, '未知')


def enrich_message_status(row):
    if not row:
        return None
    row['status_label'] = get_message_status_label(row.get('status'))
    row['editor_state'] = '编辑中' if row.get('status') in ('sent', 'edited', 'failed') and row.get('message_id') else '新增中'
    return row


def get_version_target_message(db_path, version_id, target_type):
    return enrich_message_status(get_telegram_message_by_version_target(db_path, version_id, target_type))


def get_version_message_summary(db_path, version_id):
    return {
        'bot': get_version_target_message(db_path, version_id, 'bot'),
        'channel': get_version_target_message(db_path, version_id, 'channel'),
    }


def build_message_editor_context(db_path, version_id, target_type):
    settings = get_telegram_settings(db_path)
    version = get_version_by_id(db_path, version_id)
    if not version:
        return None
    message = get_version_target_message(db_path, version_id, target_type)
    generated_text = build_version_message(version)
    editable = message and message.get('status') in ('sent', 'edited', 'failed') and message.get('message_id')
    chat_id = message.get('chat_id') if editable else _chat_id_for_target(settings, target_type)
    return {
        'version': version,
        'target_type': target_type,
        'target_label': '频道' if target_type == 'channel' else '机器人',
        'chat_id': chat_id,
        'message': message,
        'editor_state': '编辑中' if editable else '新增中',
        'message_text': message.get('text') if editable and message.get('text') else generated_text,
        'generated_text': generated_text,
    }


def get_command_settings(db_path):
    settings = get_telegram_settings(db_path)
    return {
        'commands_enabled': settings['commands_enabled'],
        'admin_user_ids': settings['admin_user_ids'],
        'admin_chat_ids': settings['admin_chat_ids'],
    }


def start_command_polling(app):
    global _polling_thread
    if _polling_thread and _polling_thread.is_alive():
        return
    _polling_thread = threading.Thread(target=_polling_loop, args=(app,), daemon=True)
    _polling_thread.start()
    logger.info('Telegram command polling thread started')


def _polling_loop(app):
    offset = None
    while True:
        with app.app_context():
            db_path = app.config['DATABASE_PATH']
            settings = get_telegram_settings(db_path)
            if settings['commands_enabled'] and settings['bot_token']:
                offset = _poll_once(app, settings['bot_token'], offset)
        time.sleep(3)


def _poll_once(app, bot_token, offset):
    params = {'timeout': 20, 'allowed_updates': json.dumps(['message'])}
    if offset is not None:
        params['offset'] = offset
    try:
        resp = requests.get(f'https://api.telegram.org/bot{bot_token}/getUpdates',
                            params=params, timeout=25)
        data = resp.json()
    except requests.RequestException as e:
        logger.warning(f'Failed to poll Telegram updates: {e}')
        return offset
    except ValueError as e:
        logger.warning(f'Invalid Telegram getUpdates response: {e}')
        return offset

    if not resp.ok or not data.get('ok'):
        logger.warning(f"Telegram getUpdates failed: {data.get('description', resp.status_code)}")
        return offset

    for update in data.get('result', []):
        offset = update['update_id'] + 1
        message = update.get('message') or {}
        text = (message.get('text') or '').strip()
        if text.startswith('/'):
            handle_command(app, bot_token, message, text)
    return offset


def handle_command(app, bot_token, message, text):
    db_path = app.config['DATABASE_PATH']
    chat_id = str(message.get('chat', {}).get('id', ''))
    user_id = str(message.get('from', {}).get('id', ''))
    if not _is_command_allowed(db_path, chat_id, user_id):
        send_message(bot_token, chat_id, '没有权限执行该命令。', app.config['REQUEST_TIMEOUT'])
        return

    parts = text.split(maxsplit=1)
    command = parts[0].split('@', 1)[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ''
    if command == '/help':
        reply = '可用命令：\n/check 手动检测更新\n/latest 查看最新版本\n/status 查看检测状态\n/translate [版本号] 翻译更新日志'
    elif command == '/status':
        reply = _command_status(db_path)
    elif command == '/latest':
        reply = build_version_message(get_latest_version(db_path) or {})
    elif command == '/check':
        reply = _command_check(app)
    elif command == '/translate':
        reply = _command_translate(app, arg)
    else:
        reply = '未知命令，发送 /help 查看可用命令。'
    send_message(bot_token, chat_id, reply, app.config['REQUEST_TIMEOUT'])


def _command_status(db_path):
    return (
        f"最近检测：{get_setting(db_path, 'last_checked') or '未检测'}\n"
        f"检测状态：{get_setting(db_path, 'last_check_status') or '未知'}\n"
        f"最近转发：{get_setting(db_path, 'telegram_last_notify_status') or '未转发'}"
    )


def _command_check(app):
    from app.scraper import scrape
    config = app.config
    result = scrape(config['DATABASE_PATH'], config['SCRAPE_URL'],
                    config['SCRAPE_USER_AGENT'], config['REQUEST_TIMEOUT'])
    if result.get('status') == 'source_error':
        return result.get('message', '检测失败')
    state = '新版本' if result.get('is_new') else '无新版本'
    if result.get('is_updated'):
        state = '已有版本已刷新'
    return f"检测完成：{result.get('version') or '-'}（{state}）"


def _command_translate(app, version_arg):
    db_path = app.config['DATABASE_PATH']
    version = get_version_by_version_str(db_path, version_arg) if version_arg else get_latest_version(db_path)
    if not version:
        return '版本记录不存在。'
    changelog = version.get('changelog')
    if not changelog:
        return '该版本没有可翻译的更新日志。'
    translated = translate_changelog(db_path, changelog, app.config['REQUEST_TIMEOUT'])
    if not translated:
        return '翻译失败，请检查翻译配置。'
    update_version(db_path, version['id'], {'changelog_zh': translated})
    for row in get_telegram_messages(db_path, version['id']):
        sync_tracked_message(db_path, row['id'], app.config['REQUEST_TIMEOUT'])
    return f"版本 {version['version']} 更新日志已翻译，并已同步 Telegram 消息。"


def _is_command_allowed(db_path, chat_id, user_id):
    settings = get_telegram_settings(db_path)
    allowed_users = _split_csv(settings['admin_user_ids'])
    allowed_chats = _split_csv(settings['admin_chat_ids'])
    if not allowed_users and not allowed_chats:
        return False
    return user_id in allowed_users or chat_id in allowed_chats


def _split_csv(value):
    return {item.strip() for item in (value or '').split(',') if item.strip()}


def _chat_id_for_target(settings, target_type):
    if target_type == 'channel':
        return settings['channel_chat_id']
    return settings['bot_chat_id']


def _resolve_version_id(db_path, version_data):
    version = version_data.get('version')
    if not version:
        return None
    row = get_version_by_version_str(db_path, version)
    return row['id'] if row else None


def _looks_missing(message):
    text = (message or '').lower()
    return 'not found' in text or 'message to delete not found' in text


def _is_not_modified(message):
    return 'not modified' in (message or '').lower()
