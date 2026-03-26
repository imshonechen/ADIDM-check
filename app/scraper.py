import os
import re
import hashlib
import logging
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests
from curl_cffi import requests as cffi_requests

from app.models import get_version_by_version_str, insert_version, set_setting, refresh_version

logger = logging.getLogger(__name__)


def _solve_puzzle(session, file_url, timeout):
    """Solve a single puzzle challenge."""
    resp = session.get('https://workupload.com/puzzle', headers={
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': file_url,
    }, timeout=timeout)
    data = resp.json()['data']

    puzzle = data['puzzle']
    find_set = set(data['find'])
    answers = []
    for i in range(data['range']):
        h = hashlib.sha256((puzzle + str(i)).encode()).hexdigest()
        if h in find_set:
            answers.append(str(i))
            if len(answers) == len(data['find']):
                break

    if len(answers) != len(data['find']):
        return False

    captcha_val = ' '.join(answers) + ' '
    session.post('https://workupload.com/captcha', headers={
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': file_url,
    }, data={'captcha': captcha_val}, timeout=timeout)
    return True


def _fetch_workupload(download_url, timeout, version_str=None):
    """Bypass workupload.com captcha, extract file info and direct download URL.
    Returns dict with filename, filesize, sha256, direct_url, changelog or empty dict."""
    s = cffi_requests.Session(impersonate='chrome')
    file_key = download_url.rstrip('/').split('/')[-1]
    start_url = f'https://workupload.com/start/{file_key}'
    result = {}

    # Step 1: Visit file page
    s.get(download_url, timeout=timeout)

    # Step 2: Solve captcha (1st time)
    if not _solve_puzzle(s, download_url, timeout):
        logger.warning('Failed to solve puzzle (1st)')
        return result

    # Step 3: Visit /start to get token cookie
    s.get(start_url, timeout=timeout)

    # Step 4: Solve captcha again (required after token)
    if not _solve_puzzle(s, download_url, timeout):
        logger.warning('Failed to solve puzzle (2nd)')
        return result

    # Step 5: Visit /start again to get download start page
    resp = s.get(start_url, timeout=timeout)
    page_text = resp.text

    # Step 6: Extract file info from page HTML
    filename_match = re.search(
        r'Filename:.*?</td>\s*<td[^>]*>(.*?)</td>', page_text, re.DOTALL)
    filesize_match = re.search(
        r'Filesize:.*?</td>\s*<td[^>]*>(.*?)</td>', page_text, re.DOTALL)
    sha256_match = re.search(
        r'Checksum:.*?</td>\s*<td[^>]*>([a-fA-F0-9]{64})\s*\(SHA256\)</td>',
        page_text, re.DOTALL)

    if filename_match:
        result['filename'] = filename_match.group(1).strip()
    if filesize_match:
        result['filesize'] = filesize_match.group(1).strip()
    if sha256_match:
        result['sha256'] = sha256_match.group(1).strip()

    # Step 7: Get direct download URL via API
    api_url = f'https://workupload.com/api/file/getDownloadServer/{file_key}'
    try:
        api_resp = s.get(api_url, headers={
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': start_url,
        }, timeout=timeout)
        api_data = api_resp.json()
        if api_data.get('success') and api_data.get('data', {}).get('url'):
            result['direct_url'] = api_data['data']['url']
    except Exception as e:
        logger.warning(f'Failed to get direct download URL: {e}')

    # Step 8: Download file to local storage
    file_path = None
    if result.get('direct_url') and result.get('filename'):
        try:
            file_path = _download_file(s, result['direct_url'], result['filename'],
                                       timeout, result.get('sha256'))
        except Exception as e:
            logger.warning(f'Failed to download file: {e}')

    # Step 9: Extract changelog from downloaded zip
    if file_path:
        try:
            changelog = _extract_changelog(file_path, version_str)
            if changelog:
                result['changelog'] = changelog
        except Exception as e:
            logger.warning(f'Failed to extract changelog: {e}')

    return result


def _extract_changelog(zip_path, version_str=None, password='1234'):
    """Extract changelog for a specific version from Changelog.txt in a password-protected zip.
    The file contains multiple versions' logs separated by '== Change Log vX.X ==' headers.
    Only the log entries for the matching version are returned."""
    if not os.path.exists(zip_path):
        return None

    with zipfile.ZipFile(zip_path, 'r') as zf:
        # Find Changelog.txt (case-insensitive)
        changelog_name = None
        for name in zf.namelist():
            basename = name.rsplit('/', 1)[-1] if '/' in name else name
            if basename.lower() == 'changelog.txt':
                changelog_name = name
                break

        if not changelog_name:
            logger.info(f'No Changelog.txt found in {zip_path}')
            return None

        content = zf.read(changelog_name, pwd=password.encode())
        # Try UTF-8 first, fallback to GBK
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            text = content.decode('gbk', errors='replace')

    # Normalize line endings to \n
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    if not version_str:
        return text.strip()

    # Parse version-specific changelog
    # Format: == Change Log vX.X ==
    # Match the target version section, stop at next section header or end
    pattern = r'==\s*Change\s+Log\s+v' + re.escape(version_str) + r'\s*==[ \t]*\n(.*?)(?=\n==\s*Change\s+Log\s+v|\Z)'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        # Remove leading whitespace from each line
        lines = match.group(1).strip().splitlines()
        return '\n'.join(line.strip() for line in lines)

    logger.info(f'No changelog entry found for version {version_str}')
    return None


def _download_file(session, direct_url, filename, timeout, expected_sha256=None):
    """Download file to data/downloads/ directory.
    If file exists, verify SHA256; re-download if mismatch."""
    from app.config import Config
    download_dir = os.path.join(os.path.dirname(Config.DATABASE_PATH), 'downloads')
    os.makedirs(download_dir, exist_ok=True)

    file_path = os.path.join(download_dir, filename)
    if os.path.exists(file_path):
        if expected_sha256:
            local_hash = _sha256_file(file_path)
            if local_hash == expected_sha256.lower():
                logger.info(f'File exists and SHA256 matches: {file_path}')
                return file_path
            else:
                logger.info(f'File exists but SHA256 mismatch (local={local_hash[:16]}..., expected={expected_sha256[:16]}...), re-downloading')
        else:
            logger.info(f'File already exists: {file_path}')
            return file_path

    resp = session.get(direct_url, timeout=timeout)
    with open(file_path, 'wb') as f:
        f.write(resp.content)

    logger.info(f'Downloaded: {file_path} ({len(resp.content)} bytes)')
    return file_path


def _sha256_file(file_path):
    """Calculate SHA256 hash of a local file."""
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def scrape(db_path, scrape_url, user_agent, timeout):
    """Scrape IDM version info and store if new version found.
    If version exists, refresh its data from source.
    Returns dict with version, is_new, is_updated, and status."""
    from datetime import datetime
    headers = {'User-Agent': user_agent}

    # Record check time regardless of result
    set_setting(db_path, 'last_checked', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    # Step 1: Fetch XML from source
    try:
        resp = requests.get(scrape_url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f'Failed to fetch {scrape_url}: {e}')
        set_setting(db_path, 'last_check_status', 'source_error')
        return {'status': 'source_error', 'message': '源站请求失败：' + str(e)}

    # Step 2: Parse XML
    try:
        root = ET.fromstring(resp.text)
        version = root.findtext('Version')
        download_url = root.findtext('Download_URL')
        if not version or not download_url:
            logger.error('Missing Version or Download_URL in XML')
            set_setting(db_path, 'last_check_status', 'source_error')
            return {'status': 'source_error', 'message': '源站 XML 格式异常，缺少版本号或下载地址'}
    except ET.ParseError as e:
        logger.error(f'XML parse error: {e}')
        set_setting(db_path, 'last_check_status', 'source_error')
        return {'status': 'source_error', 'message': '源站 XML 解析失败'}

    # Step 3: Fetch workupload details if applicable
    file_info = {}
    parsed = urlparse(download_url)
    if 'workupload.com' in parsed.netloc:
        try:
            file_info = _fetch_workupload(download_url, timeout, version)
        except Exception as e:
            logger.warning(f'Failed to fetch file details from {download_url}: {e}')

    # Step 4: Check if version already exists
    existing = get_version_by_version_str(db_path, version)
    if existing:
        # Refresh existing record
        refresh_data = {'download_url': download_url}
        refresh_data.update(file_info)
        source_changed = refresh_version(db_path, existing['id'], refresh_data)
        set_setting(db_path, 'last_check_status', 'success')
        return {
            'status': 'success',
            'version': version,
            'is_new': False,
            'is_updated': source_changed,
        }

    # Step 5: Insert new version
    data = {'version': version, 'download_url': download_url}
    data.update(file_info)
    insert_version(db_path, data)
    set_setting(db_path, 'last_check_status', 'success')
    return {'status': 'success', 'version': version, 'is_new': True, 'is_updated': False}
