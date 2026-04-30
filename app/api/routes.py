from flask import Blueprint, jsonify, current_app

from app.formatters import format_filesize

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/latest')
def latest():
    from app.models import get_latest_version, get_setting
    db_path = current_app.config['DATABASE_PATH']
    version = get_latest_version(db_path)
    if not version:
        return jsonify({'code': 1, 'message': '暂无版本数据'}), 404
    version.pop('is_featured', None)
    # Only keep date part (YYYY-MM-DD) for frontend display
    if version.get('created_at'):
        version['created_at'] = version['created_at'][:10]
    if version.get('updated_at'):
        version['updated_at'] = version['updated_at'][:10]
    version['filesize_display'] = format_filesize(version.get('filesize'))
    version['changelog_display'] = version.get('changelog_zh') or version.get('changelog')
    last_checked = get_setting(db_path, 'last_checked')
    if last_checked:
        last_checked = last_checked[:10]
    last_check_status = get_setting(db_path, 'last_check_status')
    return jsonify({'code': 0, 'data': version,
                    'last_checked': last_checked, 'last_check_status': last_check_status})
