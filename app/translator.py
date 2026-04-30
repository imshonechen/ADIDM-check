import logging

import requests

from app.models import get_settings

logger = logging.getLogger(__name__)

TRANSLATION_SETTING_KEYS = (
    'translation_provider',
    'translation_deeplx_url',
    'translation_openai_base_url',
    'translation_openai_api_key',
    'translation_openai_model',
)


def get_translation_settings(db_path):
    settings = get_settings(db_path, TRANSLATION_SETTING_KEYS)
    return {
        'provider': settings.get('translation_provider') or 'off',
        'deeplx_url': settings.get('translation_deeplx_url') or '',
        'openai_base_url': settings.get('translation_openai_base_url') or '',
        'openai_api_key': settings.get('translation_openai_api_key') or '',
        'openai_model': settings.get('translation_openai_model') or 'gpt-4o-mini',
    }


def translate_changelog(db_path, text, timeout):
    if not text:
        return None

    settings = get_translation_settings(db_path)
    provider = settings['provider']
    try:
        if provider == 'deeplx':
            return translate_with_deeplx(settings['deeplx_url'], text, timeout)
        if provider == 'openai':
            return translate_with_openai(settings, text, timeout)
    except Exception as e:
        logger.warning(f'Failed to translate changelog with {provider}: {e}')
        return None

    return None


def translate_with_deeplx(api_url, text, timeout):
    if not api_url:
        return None

    resp = requests.post(api_url, json={
        'text': text,
        'source_lang': 'EN',
        'target_lang': 'ZH',
    }, timeout=timeout)
    data = resp.json()
    if not resp.ok:
        raise RuntimeError(data.get('message') or f'HTTP {resp.status_code}')

    translated = data.get('data') or data.get('translation') or data.get('text')
    if isinstance(translated, list):
        translated = '\n'.join(str(item) for item in translated)
    return str(translated).strip() if translated else None


def translate_with_openai(settings, text, timeout):
    api_url = build_openai_chat_completions_url(settings['openai_base_url'])
    api_key = settings['openai_api_key']
    model = settings['openai_model']
    if not api_url or not api_key or not model:
        return None

    resp = requests.post(
        api_url,
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json={
            'model': model,
            'messages': [
                {
                    'role': 'system',
                    'content': '你是技术更新日志翻译助手。请将英文更新日志翻译为简体中文，保留版本号、文件名、哈希、项目符号和换行结构，不要添加解释。',
                },
                {'role': 'user', 'content': text},
            ],
            'temperature': 0.2,
        },
        timeout=timeout,
    )
    data = resp.json()
    if not resp.ok:
        error = data.get('error') or {}
        raise RuntimeError(error.get('message') or f'HTTP {resp.status_code}')

    choices = data.get('choices') or []
    if not choices:
        return None
    message = choices[0].get('message') or {}
    translated = message.get('content')
    return translated.strip() if translated else None


def build_openai_chat_completions_url(base_url):
    url = (base_url or '').strip().rstrip('/')
    if not url:
        return ''
    if url.endswith('/v1/chat/completions'):
        return url
    if url.endswith('/v1'):
        return f'{url}/chat/completions'
    return f'{url}/v1/chat/completions'
