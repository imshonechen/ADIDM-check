from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash

from app.models import (
    get_user_by_username, get_all_versions, get_version_by_id,
    insert_version, update_version, delete_version, set_featured,
    get_setting
)

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
    last_checked = get_setting(db_path, 'last_checked')
    last_check_status = get_setting(db_path, 'last_check_status')
    return render_template('dashboard.html', versions=versions,
                           last_checked=last_checked, last_check_status=last_check_status)


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
    result = scrape(
        config['DATABASE_PATH'],
        config['SCRAPE_URL'],
        config['SCRAPE_USER_AGENT'],
        config['REQUEST_TIMEOUT']
    )
    if result.get('status') == 'source_error':
        return jsonify({'code': 1, 'message': result.get('message', '源站异常'), 'data': result})

    return jsonify({'code': 0, 'message': '抓取完成', 'data': result})
