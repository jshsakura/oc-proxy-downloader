"""Public share adapters for the ordinary HTTP download pipeline."""

import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup
from core.hoster_common import HosterParseError, HosterParseResult


def google_drive_file_id(url):
    p = urlparse(url or '')
    if p.hostname not in {'drive.google.com', 'drive.usercontent.google.com', 'docs.google.com'}:
        return None
    match = re.fullmatch(r'/file/d/([A-Za-z0-9_-]+)(?:/[^/]+)?/?', p.path)
    identifier = match[1] if match else (parse_qs(p.query).get('id') or [None])[0]
    return identifier if identifier and re.fullmatch(r'[A-Za-z0-9_-]+', identifier) else None


def parse_google_drive_sync(url, proxies=None):
    identifier = google_drive_file_id(url)
    if not identifier:
        raise HosterParseError('Google Drive 개별 파일 공유 링크가 필요합니다; 폴더 링크는 파일 선택이 필요합니다')
    params = {'id': identifier, 'export': 'download'}
    resourcekey = (parse_qs(urlparse(url).query).get('resourcekey') or [None])[0]
    if resourcekey:
        params['resourcekey'] = resourcekey
    # No API token, metadata preflight, HEAD or guest-account registration.
    return HosterParseResult('https://drive.usercontent.google.com/download?' + urlencode(params),
                             referer=url).as_parse_result()


def google_drive_confirmation(body, current_url, source_url):
    """Advance one advertised public download confirmation, never retry it."""
    identifier = google_drive_file_id(source_url)
    if not identifier or urlparse(current_url).hostname != 'drive.usercontent.google.com':
        return None
    soup = BeautifulSoup(body, 'html.parser')
    form = soup.select_one('form#download-form')
    if not form:
        text = soup.get_text(' ', strip=True).lower()
        if 'too many users' in text or 'download quota' in text:
            raise HosterParseError('Google Drive 다운로드 한도 초과; 자동 재시도하지 않습니다')
        if ('request access' in text or 'you need access' in text
                or soup.select_one('a[href*="accounts.google.com/ServiceLogin"]')):
            raise HosterParseError('Google Drive 파일 접근 권한 또는 로그인이 필요합니다')
        raise HosterParseError('Google Drive 공개 파일 확인 단계가 제공되지 않았습니다 (원본 보존)')
    action = urljoin(current_url, form.get('action') or current_url)
    p = urlparse(action)
    fields = {n['name']: n.get('value', '') for n in form.select('input[type="hidden"][name]')}
    if (p.scheme != 'https' or p.hostname != 'drive.usercontent.google.com'
            or p.path != '/download' or p.username or p.password
            or form.get('method', 'get').lower() != 'get'
            or fields.get('id') != identifier or not fields.get('confirm')):
        raise HosterParseError('Google Drive 확인 폼의 파일 ID/목적지가 일치하지 않습니다 (원본 보존)')
    target = p._replace(query=urlencode(fields), fragment='').geturl()
    if target == current_url:
        raise HosterParseError('Google Drive 같은 확인 요청을 반복하지 않습니다')
    return target


async def read_confirmation_body(stream, limit=512 * 1024):
    body = bytearray()
    async for chunk in stream.iter_chunked(16384):
        body.extend(chunk)
        if len(body) > limit:
            raise HosterParseError('Google Drive 확인 페이지 크기 상한 초과')
    return bytes(body)
