from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash

from app.formatters import format_filesize
from app.models import (
    get_user_by_username, get_all_versions, get_version_by_id,
    insert_version, update_version, delete_version, set_featured,
    get_setting, set_settings
)
from app.scheduler import reschedule_daily_scrape
from app.settings import get_scrape_settings, scrape_settings_to_storage, validate_scrape_settings
from app.telegram import (
    build_message_editor_context,
    delete_tracked_message,
    edit_tracked_message,
    get_version_message_summary,
    get_telegram_settings,
    resend_tracked_message_text,
    send_test_message,
    send_version_message_text,
    sync_tracked_message,
)
from app.translator import get_translation_settings, translate_changelog

admin_bp = Blueprint('admin', __name__, url_prefix='/admin',
                     template_folder='templates')


# --- Page Routes ---

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        if current_user.is_authenticated:
            return redirect(url_for('admin.dashboard'))
        return render_template('login.html')

    data = request.form
    username = data.get('username', '')
    password = data.get('password', '')
    db_path = current_app.config['DATABASE_PATH']
    user = get_user_by_username(db_path, username)

    if user and check_password_hash(user.password_hash, password):
        login_user(user)
        return redirect(url_for('admin.dashboard'))

    return render_template('login.html', error='用户名或密码错误')


@admin_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('admin.login'))


@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
def dashboard():
    db_path = current_app.config['DATABASE_PATH']
    versions = get_all_versions(db_path)
    for version in versions:
        version['filesize_display'] = format_filesize(version.get('filesize'))
        version['changelog_display'] = version.get('changelog_zh') or version.get('changelog')
        version['telegram_messages'] = get_version_message_summary(db_path, version['id'])
    last_checked = get_setting(db_path, 'last_checked')
    last_check_status = get_setting(db_path, 'last_check_status')
    return render_template('dashboard.html', versions=versions,
                           last_checked=last_checked, last_check_status=last_check_status)


@admin_bp.route('/settings')
@login_required
def settings():
    db_path = current_app.config['DATABASE_PATH']
    telegram_settings = get_telegram_settings(db_path)
    telegram_last_notify_status = get_setting(db_path, 'telegram_last_notify_status')
    telegram_last_notify_label = _format_telegram_notify_status(telegram_last_notify_status)
    translation_settings = get_translation_settings(db_path)
    scrape_settings = get_scrape_settings(db_path, current_app.config)
    return render_template('settings.html',
                           telegram_settings=telegram_settings,
                           telegram_last_notify_label=telegram_last_notify_label,
                           translation_settings=translation_settings,
                           scrape_settings=scrape_settings)


@admin_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'GET':
        return render_template('edit.html', version=None)

    data = request.form.to_dict()
    if not data.get('version') or not data.get('download_url'):
        return render_template('edit.html', version=None, error='版本号和下载地址为必填项')

    db_path = current_app.config['DATABASE_PATH']
    insert_version(db_path, data)
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/edit/<int:version_id>', methods=['GET', 'POST'])
@login_required
def edit(version_id):
    db_path = current_app.config['DATABASE_PATH']
    version = get_version_by_id(db_path, version_id)
    if not version:
        return redirect(url_for('admin.dashboard'))

    if request.method == 'GET':
        return render_template('edit.html', version=version)

    data = request.form.to_dict()
    update_version(db_path, version_id, data)
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/versions/<int:version_id>/telegram/<target_type>')
@login_required
def telegram_message_editor(version_id, target_type):
    if target_type not in ('bot', 'channel'):
        return redirect(url_for('admin.dashboard'))
    context = build_message_editor_context(
        current_app.config['DATABASE_PATH'], version_id, target_type
    )
    if not context:
        return redirect(url_for('admin.dashboard'))
    return render_template('telegram_message.html', **context)


# --- API Routes ---

@admin_bp.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '')
    password = data.get('password', '')
    db_path = current_app.config['DATABASE_PATH']
    user = get_user_by_username(db_path, username)

    if user and check_password_hash(user.password_hash, password):
        login_user(user)
        return jsonify({'code': 0, 'message': '登录成功'})

    return jsonify({'code': 1, 'message': '用户名或密码错误'}), 401


@admin_bp.route('/api/versions')
@login_required
def api_versions():
    db_path = current_app.config['DATABASE_PATH']
    versions = get_all_versions(db_path)
    for version in versions:
        version['filesize_display'] = format_filesize(version.get('filesize'))
        version['changelog_display'] = version.get('changelog_zh') or version.get('changelog')
    return jsonify({'code': 0, 'data': versions})


@admin_bp.route('/api/versions', methods=['POST'])
@login_required
def api_create_version():
    data = request.get_json(silent=True) or {}
    if not data.get('version') or not data.get('download_url'):
        return jsonify({'code': 1, 'message': '版本号和下载地址为必填项'}), 400

    db_path = current_app.config['DATABASE_PATH']
    new_id = insert_version(db_path, data)
    return jsonify({'code': 0, 'message': '新增成功', 'data': {'id': new_id}}), 201


@admin_bp.route('/api/versions/<int:version_id>', methods=['PUT'])
@login_required
def api_update_version(version_id):
    db_path = current_app.config['DATABASE_PATH']
    version = get_version_by_id(db_path, version_id)
    if not version:
        return jsonify({'code': 1, 'message': '记录不存在'}), 404

    data = request.get_json(silent=True) or {}
    update_version(db_path, version_id, data)
    return jsonify({'code': 0, 'message': '更新成功'})


@admin_bp.route('/api/versions/<int:version_id>', methods=['DELETE'])
@login_required
def api_delete_version(version_id):
    db_path = current_app.config['DATABASE_PATH']
    version = get_version_by_id(db_path, version_id)
    if not version:
        return jsonify({'code': 1, 'message': '记录不存在'}), 404

    delete_version(db_path, version_id)
    return jsonify({'code': 0, 'message': '删除成功'})


@admin_bp.route('/api/versions/<int:version_id>/feature', methods=['PUT'])
@login_required
def api_set_featured(version_id):
    db_path = current_app.config['DATABASE_PATH']
    version = get_version_by_id(db_path, version_id)
    if not version:
        return jsonify({'code': 1, 'message': '记录不存在'}), 404

    set_featured(db_path, version_id)
    return jsonify({'code': 0, 'message': '已设为展示版本'})


@admin_bp.route('/api/scrape', methods=['POST'])
@login_required
def api_scrape():
    from app.scraper import scrape
    config = current_app.config
    settings = get_scrape_settings(config['DATABASE_PATH'], config)
    result = scrape(
        config['DATABASE_PATH'],
        settings['scrape_url'],
        settings['scrape_user_agent'],
        settings['request_timeout']
    )
    if result.get('status') == 'source_error':
        return jsonify({'code': 1, 'message': result.get('message', '源站异常'), 'data': result})

    return jsonify({'code': 0, 'message': '抓取完成', 'data': result})


@admin_bp.route('/api/scrape-settings', methods=['POST'])
@login_required
def api_update_scrape_settings():
    data = request.get_json(silent=True) or {}
    settings, error = validate_scrape_settings(data)
    if error:
        return jsonify({'code': 1, 'message': error}), 400

    db_path = current_app.config['DATABASE_PATH']
    set_settings(db_path, scrape_settings_to_storage(settings))
    reschedule_daily_scrape(current_app._get_current_object())
    return jsonify({'code': 0, 'message': '系统设置已保存'})


@admin_bp.route('/api/telegram-settings', methods=['POST'])
@login_required
def api_update_telegram_settings():
    data = request.get_json(silent=True) or {}
    db_path = current_app.config['DATABASE_PATH']
    set_settings(db_path, {
        'telegram_bot_token': data.get('bot_token', '').strip(),
        'telegram_bot_chat_id': data.get('bot_chat_id', '').strip(),
        'telegram_channel_chat_id': data.get('channel_chat_id', '').strip(),
        'telegram_notify_bot_enabled': '1' if data.get('notify_bot_enabled') else '0',
        'telegram_notify_channel_enabled': '1' if data.get('notify_channel_enabled') else '0',
        'telegram_commands_enabled': '1' if data.get('commands_enabled') else '0',
        'telegram_admin_user_ids': data.get('admin_user_ids', '').strip(),
        'telegram_admin_chat_ids': data.get('admin_chat_ids', '').strip(),
    })
    return jsonify({'code': 0, 'message': 'Telegram 设置已保存'})


@admin_bp.route('/api/translation-settings', methods=['POST'])
@login_required
def api_update_translation_settings():
    data = request.get_json(silent=True) or {}
    provider = data.get('provider', 'off')
    if provider not in ('off', 'deeplx', 'openai'):
        return jsonify({'code': 1, 'message': '翻译服务无效'}), 400

    db_path = current_app.config['DATABASE_PATH']
    set_settings(db_path, {
        'translation_provider': provider,
        'translation_deeplx_url': data.get('deeplx_url', '').strip(),
        'translation_openai_base_url': data.get('openai_base_url', '').strip(),
        'translation_openai_api_key': data.get('openai_api_key', '').strip(),
        'translation_openai_model': data.get('openai_model', '').strip() or 'gpt-4o-mini',
    })
    return jsonify({'code': 0, 'message': '翻译设置已保存'})


@admin_bp.route('/api/translation-test', methods=['POST'])
@login_required
def api_test_translation():
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'code': 1, 'message': '测试文本不能为空'}), 400

    db_path = current_app.config['DATABASE_PATH']
    scrape_settings = get_scrape_settings(db_path, current_app.config)
    translation = translate_changelog(db_path, text, scrape_settings['request_timeout'])
    if not translation:
        return jsonify({'code': 1, 'message': '翻译失败，请检查翻译服务配置'}), 400

    return jsonify({'code': 0, 'message': '翻译测试成功', 'data': {'translation': translation}})


@admin_bp.route('/api/telegram-test', methods=['POST'])
@login_required
def api_test_telegram():
    data = request.get_json(silent=True) or {}
    target = data.get('target', 'bot')
    if target not in ('bot', 'channel'):
        return jsonify({'code': 1, 'message': '测试目标无效'}), 400

    db_path = current_app.config['DATABASE_PATH']
    scrape_settings = get_scrape_settings(db_path, current_app.config)
    ok, message = send_test_message(db_path, target, scrape_settings['request_timeout'])
    if not ok:
        return jsonify({'code': 1, 'message': message}), 400

    return jsonify({'code': 0, 'message': message})


@admin_bp.route('/api/versions/<int:version_id>/telegram/<target_type>/send', methods=['POST'])
@login_required
def api_send_version_telegram_message(version_id, target_type):
    data = request.get_json(silent=True) or {}
    if target_type not in ('bot', 'channel'):
        return jsonify({'code': 1, 'message': '发送目标无效'}), 400
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'code': 1, 'message': '消息内容不能为空'}), 400

    db_path = current_app.config['DATABASE_PATH']
    scrape_settings = get_scrape_settings(db_path, current_app.config)
    version = get_version_by_id(db_path, version_id)
    if not version:
        return jsonify({'code': 1, 'message': '版本记录不存在'}), 404

    ok, message, row_id = send_version_message_text(
        db_path, version['id'], target_type, text, scrape_settings['request_timeout']
    )
    if not ok:
        return jsonify({'code': 1, 'message': message, 'data': {'id': row_id}}), 400
    return jsonify({'code': 0, 'message': message, 'data': {'id': row_id}})


@admin_bp.route('/api/versions/<int:version_id>/telegram/<target_type>/edit', methods=['POST'])
@login_required
def api_edit_version_telegram_message(version_id, target_type):
    db_path = current_app.config['DATABASE_PATH']
    timeout = get_scrape_settings(db_path, current_app.config)['request_timeout']
    context = build_message_editor_context(db_path, version_id, target_type)
    if not context or not context.get('message'):
        return jsonify({'code': 1, 'message': '消息记录不存在'}), 404
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'code': 1, 'message': '消息内容不能为空'}), 400

    ok, message = edit_tracked_message(
        db_path, context['message']['id'], text, timeout
    )
    if not ok:
        return jsonify({'code': 1, 'message': message}), 400
    return jsonify({'code': 0, 'message': message})


@admin_bp.route('/api/versions/<int:version_id>/telegram/<target_type>/sync', methods=['POST'])
@login_required
def api_sync_version_telegram_message(version_id, target_type):
    db_path = current_app.config['DATABASE_PATH']
    timeout = get_scrape_settings(db_path, current_app.config)['request_timeout']
    context = build_message_editor_context(db_path, version_id, target_type)
    if not context or not context.get('message'):
        return jsonify({'code': 1, 'message': '消息记录不存在'}), 404
    ok, message = sync_tracked_message(
        db_path, context['message']['id'], timeout
    )
    if not ok:
        return jsonify({'code': 1, 'message': message}), 400
    return jsonify({'code': 0, 'message': message})


@admin_bp.route('/api/versions/<int:version_id>/telegram/<target_type>/delete', methods=['POST'])
@login_required
def api_delete_version_telegram_message(version_id, target_type):
    db_path = current_app.config['DATABASE_PATH']
    timeout = get_scrape_settings(db_path, current_app.config)['request_timeout']
    context = build_message_editor_context(db_path, version_id, target_type)
    if not context or not context.get('message'):
        return jsonify({'code': 1, 'message': '消息记录不存在'}), 404
    ok, message = delete_tracked_message(
        db_path, context['message']['id'], timeout
    )
    if not ok:
        return jsonify({'code': 1, 'message': message}), 400
    return jsonify({'code': 0, 'message': message})


@admin_bp.route('/api/versions/<int:version_id>/telegram/<target_type>/resend', methods=['POST'])
@login_required
def api_resend_version_telegram_message(version_id, target_type):
    db_path = current_app.config['DATABASE_PATH']
    timeout = get_scrape_settings(db_path, current_app.config)['request_timeout']
    context = build_message_editor_context(db_path, version_id, target_type)
    if not context or not context.get('message'):
        return jsonify({'code': 1, 'message': '消息记录不存在'}), 404
    data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip() or context['message_text']
    ok, message = resend_tracked_message_text(
        db_path, context['message']['id'], text, timeout
    )
    if not ok:
        return jsonify({'code': 1, 'message': message}), 400
    return jsonify({'code': 0, 'message': message})


@admin_bp.route('/api/versions/<int:version_id>/translate', methods=['POST'])
@login_required
def api_translate_version(version_id):
    db_path = current_app.config['DATABASE_PATH']
    version = get_version_by_id(db_path, version_id)
    if not version:
        return jsonify({'code': 1, 'message': '版本记录不存在'}), 404
    if not version.get('changelog'):
        return jsonify({'code': 1, 'message': '该版本没有可翻译的更新日志'}), 400

    scrape_settings = get_scrape_settings(db_path, current_app.config)
    translation = translate_changelog(db_path, version['changelog'], scrape_settings['request_timeout'])
    if not translation:
        return jsonify({'code': 1, 'message': '翻译失败，请检查翻译服务配置'}), 400

    update_version(db_path, version_id, {'changelog_zh': translation})
    return jsonify({'code': 0, 'message': '翻译完成', 'data': {'translation': translation}})


def _format_telegram_notify_status(status):
    labels = {
        'success': '成功',
        'partial_failed': '部分失败',
    }
    return labels.get(status, '未转发')
