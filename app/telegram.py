import html
import logging
import os

import requests

from app.formatters import format_filesize
from app.models import get_settings, set_setting

logger = logging.getLogger(__name__)

TELEGRAM_SETTING_KEYS = (
    'telegram_bot_token',
    'telegram_bot_chat_id',
    'telegram_channel_chat_id',
    'telegram_notify_bot_enabled',
    'telegram_notify_channel_enabled',
)


def get_telegram_settings(db_path):
    settings = get_settings(db_path, TELEGRAM_SETTING_KEYS)
    return {
        'bot_token': settings.get('telegram_bot_token') or '',
        'bot_chat_id': settings.get('telegram_bot_chat_id') or '',
        'channel_chat_id': settings.get('telegram_channel_chat_id') or '',
        'notify_bot_enabled': settings.get('telegram_notify_bot_enabled') == '1',
        'notify_channel_enabled': settings.get('telegram_notify_channel_enabled') == '1',
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
    for target_type, chat_id in targets:
        file_path = get_download_file_path(db_path, version_data.get('filename'))
        if file_path:
            text = build_version_message(version_data, max_changelog=300)
            ok, message = send_document(bot_token, chat_id, file_path, text, timeout)
            mode = 'document'
        else:
            text = build_version_message(version_data)
            ok, message = send_message(bot_token, chat_id, text, timeout)
            mode = 'message'
        results.append({
            'target': target_type,
            'chat_id': chat_id,
            'ok': ok,
            'message': message,
            'mode': mode,
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
    return send_message(bot_token, chat_id, text, timeout)


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
        return False, str(e)
    except ValueError as e:
        logger.warning(f'Invalid Telegram response: {e}')
        return False, 'Telegram 返回格式异常'

    if not resp.ok or not data.get('ok'):
        description = data.get('description', f'HTTP {resp.status_code}')
        logger.warning(f'Failed to send Telegram message: {description}')
        return False, description

    return True, '发送成功'


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
        return False, str(e)
    except requests.RequestException as e:
        logger.warning(f'Failed to send Telegram document: {e}')
        return False, str(e)
    except ValueError as e:
        logger.warning(f'Invalid Telegram document response: {e}')
        return False, 'Telegram 返回格式异常'

    if not resp.ok or not data.get('ok'):
        description = data.get('description', f'HTTP {resp.status_code}')
        logger.warning(f'Failed to send Telegram document: {description}')
        return False, description

    return True, '文件发送成功'


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
