from app.models import get_settings

SCRAPE_SETTING_KEYS = (
    'scrape_url',
    'scrape_user_agent',
    'scrape_hour',
    'scrape_minute',
    'request_timeout',
)


def get_scrape_settings(db_path, config):
    settings = get_settings(db_path, SCRAPE_SETTING_KEYS)
    return {
        'scrape_url': settings.get('scrape_url') or config['SCRAPE_URL'],
        'scrape_user_agent': settings.get('scrape_user_agent') or config['SCRAPE_USER_AGENT'],
        'scrape_hour': _int_setting(settings.get('scrape_hour'), config['SCRAPE_HOUR']),
        'scrape_minute': _int_setting(settings.get('scrape_minute'), config['SCRAPE_MINUTE']),
        'request_timeout': _int_setting(settings.get('request_timeout'), config['REQUEST_TIMEOUT']),
    }


def validate_scrape_settings(data):
    scrape_url = (data.get('scrape_url') or '').strip()
    scrape_user_agent = (data.get('scrape_user_agent') or '').strip()
    try:
        scrape_hour = _parse_int(data.get('scrape_hour'), '抓取小时')
        scrape_minute = _parse_int(data.get('scrape_minute'), '抓取分钟')
        request_timeout = _parse_int(data.get('request_timeout'), '请求超时')
    except ValueError as e:
        return None, str(e)

    if not scrape_url:
        return None, '抓取地址不能为空'
    if not scrape_user_agent:
        return None, 'User-Agent 不能为空'
    if scrape_hour < 0 or scrape_hour > 23:
        return None, '抓取小时必须在 0-23 之间'
    if scrape_minute < 0 or scrape_minute > 59:
        return None, '抓取分钟必须在 0-59 之间'
    if request_timeout < 1 or request_timeout > 300:
        return None, '请求超时必须在 1-300 秒之间'

    return {
        'scrape_url': scrape_url,
        'scrape_user_agent': scrape_user_agent,
        'scrape_hour': scrape_hour,
        'scrape_minute': scrape_minute,
        'request_timeout': request_timeout,
    }, None


def scrape_settings_to_storage(settings):
    return {
        'scrape_url': settings['scrape_url'],
        'scrape_user_agent': settings['scrape_user_agent'],
        'scrape_hour': str(settings['scrape_hour']),
        'scrape_minute': str(settings['scrape_minute']),
        'request_timeout': str(settings['request_timeout']),
    }


def _int_setting(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _parse_int(value, label):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{label}必须是整数')
