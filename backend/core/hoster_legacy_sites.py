"""Dedicated rules for collected hosts previously treated as direct files.

Each site has its own URL grammar, storage origins and published controls.
Transport and form submission share conservative primitives: bounded HTML,
zero retries, no fabricated API calls and no repeated advertised operation.
An implemented resolver is not evidence of a successful live transfer.
"""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import re
import time
from urllib.parse import urljoin, urlparse, unquote

from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter

from core.hoster_common import (
    HosterParseError, HosterParseResult, _cookies_dict, DEFAULT_HOSTER_USER_AGENT,
    _cloudflare_challenge_seen, _raise_for_dead_page, _extract_size_from_text,
)
from core.host_policy import http_failure_message
from core.config import CONFIG_DIR


@dataclass(frozen=True)
class Site:
    name: str
    domains: tuple
    path: str
    protocol: str
    selectors: str
    storage: tuple = ()


SITES = {
    "filekeeper": Site("FileKeeper", ("filekeeper.net",), r"/[a-zA-Z0-9]{8,}(?:/.*)?", "xfs", 'a#downloadbtn[href], a#download-link[href], a[href*="/d/"]', ("dlproxy.uk",)),
    "tusfiles": Site("TusFiles", ("tusfiles.com", "tusfiles.net", "send.cm"), r"/[a-zA-Z0-9]{8,}(?:/.*)?", "xfs", 'a#downloadbtn[href], a[href*="/d/"]'),
    "uptobox": Site("Uptobox", ("uptobox.com",), r"/[a-zA-Z0-9]{8,}(?:/.*)?", "xfs", 'a#downloadlink[href], a[href*="/dl/"]'),
    "clicknupload": Site("ClicknUpload", ("clicknupload.to", "clicknupload.cc", "clicknupload.red", "clicknupload.co", "clicknupload.click", "clickndownload.org"), r"/[a-zA-Z0-9]{8,}(?:/.*)?", "xfs", 'a#downloadbtn[href], a[href*="/d/"]'),
    "clickndownload": Site("ClicknDownload", ("clickndownload.org", "clicknupload.to", "clicknupload.cc", "clicknupload.click"), r"/[a-zA-Z0-9]{8,}(?:/.*)?", "xfs", 'a#downloadbtn[href], a[href*="/d/"]'),
    "sendcm": Site("Send.cm", ("send.cm",), r"/(?:[a-zA-Z0-9]{8,}|d/[a-zA-Z0-9]+)(?:/.*)?", "xfs", 'a#downloadbtn[href], a[href*="/d/"]'),
    "sendnow": Site("Send.now", ("send.now", "send.cm", "tusfiles.com", "tusfiles.net"), r"/[a-zA-Z0-9]{8,}(?:/.*)?", "xfs", 'a#downloadbtn[href], a[href*="/d/"]'),
    "filerio": Site("FileRio", ("filerio.in", "filerio.com"), r"/[a-zA-Z0-9]{8,}(?:/.*)?", "xfs", 'a#downloadbtn[href], a[href*="/d/"]'),
    "frdl": Site("FRDL", ("frdl.my", "frdl.to", "frdl.io"), r"/[a-zA-Z0-9]{8,}(?:/.*)?", "xfs", 'a#downloadbtn[href], a[href*="/d/"]'),
    "letsupload": Site("LetsUpload", ("letsupload.io",), r"/[a-zA-Z0-9]+(?:/.*)?", "yeti", 'a.download-link[href], a#downloadUrl[href], a[href*="/download/"]'),
    "bowfile": Site("BowFile", ("bowfile.com",), r"/[a-zA-Z0-9]+(?:/.*)?", "yeti", 'a.download-link[href], a#downloadUrl[href], a[href*="/download/"]'),
    "doodrive": Site("DooDrive", ("doodrive.com",), r"/f/[a-zA-Z0-9]+/?", "doo", 'a[href*="/d/"]'),
    "solidfiles": Site("SolidFiles", ("solidfiles.com",), r"/(?:v|d|e)/[a-zA-Z0-9]+/?", "page", 'a.direct-download[href]', ("solidfilesusercontent.com",)),
    "bayfiles": Site("BayFiles", ("bayfiles.com",), r"/[a-zA-Z0-9]+(?:/.*)?", "page", 'a#download-url[href]', ("bayfilesusercontent.com",)),
    "qiwi": Site("Qiwi", ("qiwi.gg",), r"/file/[a-zA-Z0-9_-]+/?", "page", 'a[download][href], a#download[href], a.download[href]', ("spyderrock.com",)),
    "zippyshare": Site("Zippyshare", ("zippyshare.com",), r"/v/[a-zA-Z0-9]+/file\.html", "browser", 'a#dlbutton[href]'),
    "teraboxapp": Site("TeraBoxApp", ("teraboxapp.com", "terabox.app", "1024terabox.com", "terabox.com"), r"/(?:s/[^/]+|sharing/link)/?", "terabox", '.download-btn'),
    "rapidgator_free": Site("Rapidgator", ("rapidgator.net",), r"/file/[a-fA-F0-9]{32}(?:/[^/]+)?/?", "rapidgator", 'a.btn-free:visible, #freeDownload:visible, #free-download:visible'),
}


def _scraper(proxies):
    # cloudscraper may transparently repeat a rejected request. These new
    # host flows observe the first response and never solve/replay implicitly.
    session = requests.Session()
    session.headers['User-Agent'] = DEFAULT_HOSTER_USER_AGENT
    if proxies: session.proxies.update(proxies)
    return session


def _belongs(host, domains):
    host = (host or "").lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _validate_source(site, url):
    p = urlparse(url)
    if p.scheme not in {"https", "http"} or p.username or p.password or not _belongs(p.hostname, site.domains) or not re.fullmatch(site.path, unquote(p.path)):
        raise HosterParseError(f"전용 파서: {site.name} 파일 URL 형식을 확인하지 못했습니다")


def _candidate(site, value, current, source):
    candidate = urljoin(current, value or "")
    p = urlparse(candidate)
    if (p.scheme not in {"http", "https"} or p.username or p.password
            or not _belongs(p.hostname, site.domains + site.storage)
            or candidate in {current, source}):
        return None
    # An advertised control still must lead to storage, never a plan, account,
    # sibling share or an asset. Refuse ambiguity instead of downloading HTML.
    if re.search(r"/(?:login|register|premium|pricing|privacy|contact)(?:/|$)", p.path, re.I):
        return None
    if re.search(r"\.(?:js|css|png|jpg|svg|html)(?:$|/)", p.path, re.I):
        return None
    storage_host = _belongs(p.hostname, site.storage) if site.storage else False
    source_host = (urlparse(source).hostname or "").lower()
    subdomain = (p.hostname or "").lower() != source_host
    file_path = bool(re.search(r"\.(?:nsp|nsz|xci|xcz|rar|zip|7z|bin|iso|pdf|mp4)(?:$|/)", unquote(p.path), re.I))
    storage_path = bool(re.search(r"^/(?:d|dl|download|downloads)/[^/]+", p.path, re.I))
    return candidate if storage_host or file_path or subdomain and storage_path else None


def _metadata(soup):
    info = {}
    node = soup.select_one('input[name="fname"], h1.node-name, h1.uk-h4, #filename, #dl-filename, .file-name, [data-filename]')
    if node:
        name = node.get('value') or node.get('data-filename') or node.get_text(' ', strip=True)
        if name: info['name'] = str(name).strip()
        parent = node.find_parent('form')
        size = _extract_size_from_text(parent.get_text(' ', strip=True)) if parent else None
        if size: info['size'] = size
    node = soup.select_one('#filesize, .filesize, .file-size')
    if node:
        size = _extract_size_from_text(node.get_text(' ', strip=True))
        if size: info['size'] = size
    return info


def _read_page(session, site, method, url, *, data=None, referer=None, expires=None):
    # Redirects are observed rather than replaying POSTs or contacting ads.
    remaining = max(.001, expires-time.monotonic()) if expires else 30
    reply = session.request(method, url, data=data, headers={'Referer':referer} if referer else {}, stream=True, timeout=(min(10,remaining), min(30,remaining)), allow_redirects=False)
    try:
        key=hashlib.sha256((method+url+json.dumps(data,sort_keys=True)).encode()).hexdigest()[:16]
        try:
            path=Path(CONFIG_DIR)/f'host_page_{key}.json'
            path.write_text(json.dumps({'host':site.name,'method':method,'url_sha256':hashlib.sha256(url.encode()).hexdigest(),'http_status':reply.status_code,'location':reply.headers.get('Location'),'deletion_confirmed':False}));path.chmod(0o600)
        except OSError:
            pass
        if reply.status_code in {301,302,303,307,308}:
            return reply.status_code, urljoin(url, reply.headers.get('Location','')), None
        ctype = reply.headers.get('Content-Type','').lower()
        if ctype and not any(x in ctype for x in ('html','text/plain','json')):
            raise HosterParseError(f"전용 파서: {site.name} 폼 응답이 파일 스트림입니다; 주소를 재요청하지 않습니다")
        content=bytearray()
        for block in reply.iter_content(16384):
            if expires and time.monotonic()>=expires:raise HosterParseError(f"전용 파서: {site.name} 단회 처리 시간 상한 초과")
            content.extend(block)
            if len(content)>2*1024*1024:raise HosterParseError(f"전용 파서: {site.name} 페이지 크기 상한 초과")
        text=bytes(content).decode(reply.encoding or 'utf-8',errors='replace')
        # Preserve the already received document. Diagnostics must never cause
        # a second GET just to recover the markup that the parser rejected.
        try:
            path=Path(CONFIG_DIR)/f'host_page_{key}.html'
            path.write_text(text);path.chmod(0o600)
        except OSError:
            pass
        status = reply.status_code
        if _cloudflare_challenge_seen(reply,text):
            # One normal browser fallback is allowed for a proven GET
            # interstitial. Never repeat a rejected POST or cycle engines.
            if method != 'GET' or getattr(session, '_oc_fs_used', False):
                raise HosterParseError(f"{site.name} Cloudflare 보안 확인이 필요합니다; 자동 반복하지 않습니다")
            session._oc_fs_used = True
            from core.hoster_common import _flaresolverr_request_get, _solution_cookies
            solution = _flaresolverr_request_get(url, referer=referer or '', proxies=getattr(session, 'proxies', None),
                max_timeout_ms=min(60000, max(1, int((expires-time.monotonic())*1000))) if expires else 60000)
            if not solution:
                raise HosterParseError(f"{site.name} Cloudflare 단회 브라우저 확인이 완료되지 않았습니다; 자동 반복 없음")
            resolved = solution.get('url') or url
            if not _belongs(urlparse(resolved).hostname, site.domains):
                raise HosterParseError(f"전용 파서: {site.name} 브라우저 확인 목적지가 다릅니다 (원본 보존)")
            text, status = solution.get('response') or '', int(solution.get('status') or 0)
            if len(text.encode()) > 2*1024*1024:
                raise HosterParseError(f"전용 파서: {site.name} 브라우저 페이지 크기 상한 초과")
            try:
                path=Path(CONFIG_DIR)/f'host_page_{key}_fs.html'
                path.write_text(text);path.chmod(0o600)
            except OSError:
                pass
            if status != 200 or _cloudflare_challenge_seen(None,text):
                raise HosterParseError(f"{site.name} Cloudflare 단회 브라우저 확인 후 HTTP {status}; 자동 반복 없음")
            session.cookies.update(_solution_cookies(solution))
            if solution.get('userAgent'):session.headers['User-Agent']=solution['userAgent']
            url = resolved
        if status >= 400:
            if status in {404,410}:
                raise HosterParseError(f"{site.name} 호스터 페이지 HTTP {status} (삭제 여부 미확인)")
            raise HosterParseError(http_failure_message(status, reply.reason, reply.headers))
        if status != 200:
            raise HosterParseError(f"전용 파서: {site.name} 예상하지 못한 페이지 응답 HTTP {status}")
        _raise_for_dead_page(site.name,text,status)
        return status, url, text
    finally:
        reply.close()


def _form(soup, site):
    if site.name == 'FileKeeper':
        # Observed 2026-09-30: the site's own inline script builds download2
        # after a countdown, rather than putting a form in the initial HTML.
        countdown = soup.select_one('#download-countdown[data-code][data-countdown]')
        if countdown:
            if countdown.get('data-has-captcha') == 'true':
                raise HosterParseError('FileKeeper 다운로드에 사람 확인 캡차가 필요합니다; 자동 반복하지 않습니다')
            if countdown.get('data-has-password') == 'true':
                raise HosterParseError('FileKeeper 파일 비밀번호가 필요합니다; 자동 반복하지 않습니다')
            form = BeautifulSoup('<form method="POST"></form>', 'html.parser').form
            fields = {'op': 'download2', 'id': countdown['data-code'],
                      'rand': countdown.get('data-rand', ''),
                      'referer': countdown.get('data-referer', ''),
                      'method_free': countdown.get('data-method') or 'Free download',
                      'down_direct': '1'}
            for name, value in fields.items():
                node = soup.new_tag('input', attrs={'type': 'hidden', 'name': name, 'value': value})
                form.append(node)
            return form
    if site.protocol=='xfs':
        return next((f for f in soup.select('form') if f.select_one('input[name="op"][value="download1"], input[name="op"][value="download2"]')),None)
    if site.protocol=='doo':
        return next((f for f in soup.select('form') if f.select_one('input[name="f"], input[name="data"], input[name="CSRFToken"]') or 'direct-downloader' in f.get('action','')),None)
    if site.protocol=='yeti':
        return next((f for f in soup.select('form') if f.select_one('input[name="submitted"], input[name="downloadToken"]') and re.search(r'download',f.get('action',''),re.I)),None)
    return None


def parse_site(key, url, proxies=None):
    site=SITES[key];_validate_source(site,url)
    if key == 'zippyshare':
        raise HosterParseError('Zippyshare 서비스가 종료되어 파일 다운로드를 제공하지 않습니다 (공식 종료 안내 확인)')
    if key == 'letsupload':
        raise HosterParseError('LetsUpload 현재 도메인이 파일 서비스 대신 도메인 판매 페이지를 제공합니다 (2026-09-30 확인)')
    if site.protocol in {'browser','terabox','rapidgator'}:
        return _parse_browser(site,url,proxies)
    if key == 'sendnow':
        return _sendnow_browser(url)
    session=_scraper(proxies)
    session.mount('https://',HTTPAdapter(max_retries=0));session.mount('http://',HTTPAdapter(max_retries=0))
    current=url;method='GET';data=None;referer=None;seen=set();operations=set();info={}
    expires = time.monotonic()+240
    try:
        for step in range(7):
            if time.monotonic()>=expires:raise HosterParseError(f"전용 파서: {site.name} 단회 처리 시간 상한 초과")
            fingerprint=(method,current,json.dumps(data,sort_keys=True))
            if fingerprint in seen:raise HosterParseError(f"전용 파서: {site.name} 같은 요청을 반복하지 않습니다")
            seen.add(fingerprint)
            status, location, text=_read_page(session,site,method,current,data=data,referer=referer,expires=expires)
            if text is None:
                candidate=_candidate(site,location,current,url)
                if candidate:
                    return HosterParseResult(candidate,info or None,cookies=_cookies_dict(session),user_agent=session.headers.get('User-Agent'),referer=current).as_parse_result()
                if status in {307,308} and method=='POST':raise HosterParseError(f"전용 파서: {site.name} POST 재전송 리다이렉트를 중단합니다")
                if key in {'sendcm', 'tusfiles'} and urlparse(location).hostname == 'send.now':
                    # Actual 2026-09-30 migration keeps the same public file ID.
                    source_id = urlparse(url).path.rstrip('/').split('/')[-1]
                    if urlparse(location).path.rstrip('/').split('/')[-1] != source_id:
                        raise HosterParseError(f"전용 파서: {site.name} 이동된 파일 ID 불일치 (원본 보존)")
                    return _sendnow_browser(location)
                if not _belongs(urlparse(location).hostname,site.domains):raise HosterParseError(f"전용 파서: {site.name} 리다이렉트 목적지의 파일 처리 경로 미확인 (원본 보존)")
                referer,current,method,data=current,location,'GET',None
                continue
            soup=BeautifulSoup(text,'html.parser');info.update(_metadata(soup))
            links=[]
            for node in soup.select(site.selectors):
                if node.has_attr('hidden') or re.search(r'display\s*:\s*none',node.get('style',''),re.I):continue
                link=_candidate(site,node.get('href'),current,url)
                if link and link not in links:links.append(link)
            if len(links)>1:raise HosterParseError(f"전용 파서: {site.name} 파일 링크가 여러 개입니다; 파일 선택이 필요합니다")
            if links:return HosterParseResult(links[0],info or None,cookies=_cookies_dict(session),user_agent=session.headers.get('User-Agent'),referer=current).as_parse_result()
            form=_form(soup,site)
            if not form:raise HosterParseError(f"전용 파서: {site.name} 사이트별 다운로드 링크/폼을 확인하지 못했습니다 (원본 보존)")
            if form.select_one('.g-recaptcha, .cf-turnstile, input[name*="captcha"], textarea[name="g-recaptcha-response"], iframe[src*="captcha"]'):
                raise HosterParseError(f"{site.name} 다운로드에 사람 확인 캡차가 필요합니다; 자동 반복하지 않습니다")
            if form.get('method','GET').upper()!='POST':raise HosterParseError(f"전용 파서: {site.name} 다운로드 폼 메서드 미확인")
            action=urljoin(current,form.get('action') or current)
            if not _belongs(urlparse(action).hostname,site.domains) or urlparse(action).scheme!='https':raise HosterParseError(f"전용 파서: {site.name} 다운로드 폼 목적지 미확인")
            data={n['name']:n.get('value','') for n in form.select('input[type="hidden"][name]') if not n.has_attr('disabled')}
            if site.protocol=='xfs':
                operation=data.get('op');token=data.get('id')
                source_ids={p for p in urlparse(url).path.split('/') if p}
                if not token or token not in source_ids:raise HosterParseError(f"전용 파서: {site.name} 폼 파일 ID와 원본 URL이 일치하지 않습니다")
                if operation in operations:raise HosterParseError(f"전용 파서: {site.name} 거부된 단계를 재제출하지 않습니다")
                operations.add(operation)
                if operation=='download1':
                    button=form.select_one('[name="method_free"]')
                    if button:data['method_free']=button.get('value') or button.get_text(' ',strip=True)
            countdown=soup.select_one('#countdown, #countdown_str, [data-countdown]')
            if countdown:
                value=countdown.get('data-countdown') or countdown.get_text(' ',strip=True)
                match=re.search(r'\d+',value)
                if not match or int(match[0])>min(120,expires-time.monotonic()):raise HosterParseError(f"전용 파서: {site.name} 대기시간이 단회 파싱 예산을 초과합니다")
                time.sleep(int(match[0]))
            referer,current,method=current,action,'POST'
        raise HosterParseError(f"전용 파서: {site.name} 단회 처리 단계 상한 초과")
    except HosterParseError as exc:
        exc.file_info = {**info, **exc.file_info}
        raise
    finally:
        session.close()


def _sendnow_browser(url):
    from core.browser_solver import solve_download_page, SEND_NOW_FLOW
    try:
        result = solve_download_page(url, SEND_NOW_FLOW)
    except HosterParseError as exc:
        if exc.page_html:
            exc.file_info = {**_extract_sendnow_file_info(exc.page_html), **exc.file_info}
        raise
    info = _extract_sendnow_file_info(result.page_html)
    return HosterParseResult(result.download_link, info or None, cookies=result.cookies,
                             user_agent=result.user_agent, referer=result.page_url or url).as_parse_result()


def _extract_sendnow_file_info(html_text):
    """Read the file card, not its code title or the advertised upload limit."""
    soup = BeautifulSoup(html_text or '', 'html.parser')
    names = []
    for node in soup.select('h6.max-width-50, h6#qr, input[name="fname"]'):
        name = (node.get('value', '') if node.name == 'input' else node.get_text(' ', strip=True)).strip()
        if re.search(r'\.[A-Za-z0-9]{1,10}$', name) and name not in names:
            names.append(name)
    if len(names) > 1:
        raise HosterParseError('Send.now 파일 카드의 이름이 서로 다릅니다; 원본 보존, 자동 반복 없음')
    info = {'name': names[0]} if names else {}
    button = soup.select_one('#downloadbtn')
    if button:
        size = _extract_size_from_text(button.get_text(' ', strip=True) or button.get('value', ''))
        if size:
            info['size'] = size
    return info


def _parse_browser(site,url,proxies):
    from core import browser_solver as browser
    from core.link_containers import inspect_terabox_download
    browser._require_display();deadline=browser.Deadline(180 if site.protocol=='rapidgator' else 120)
    with browser._queued_browser_slot(site.domains[0],deadline),browser.sync_playwright() as pw:
        instance=pw.chromium.launch(headless=False)
        try:
            # Browser and file request must use the same route and session.
            options={'viewport':browser.VIEWPORT}
            # The special file-transfer path uses direct egress. Keep its
            # browser on that same egress instead of issuing an IP-bound token
            # through a different proxy.
            context=instance.new_context(**options);captured=[]
            def route_navigation(route):
                request=route.request
                if request.is_navigation_request() and request.frame.parent_frame is None:
                    candidate=_candidate(site,request.url,url,url)
                    if candidate:captured.append(candidate);route.abort();return
                    if not _belongs(urlparse(request.url).hostname,site.domains):route.abort();return
                route.continue_()
            context.route('**/*',route_navigation)
            page=context.new_page();response=page.goto(url,wait_until='domcontentloaded',timeout=deadline.budget_ms(60000))
            if response and response.status>=400:
                suffix=' (삭제 여부 미확인)' if response.status in {404,410} else ''
                raise HosterParseError(f'HTTP {response.status}: {site.name} 공유 페이지{suffix}; 자동 반복 없음')
            if site.protocol=='terabox':
                # This helper only returns published registered mirror URLs.
                # TeraBox account-login support remains a separate requirement.
                link=inspect_terabox_download(page,deadline,captured)
            elif site.protocol=='rapidgator':
                visible_text = page.locator('body').inner_text(timeout=deadline.budget_ms(5000))
                size = _extract_size_from_text(visible_text)
                from core.hoster_common import size_to_bytes
                if 'You can download files up to 500 MB in free mode' in visible_text and size_to_bytes(size) > 500 * 1024**2:
                    raise HosterParseError('Rapidgator 무료 모드는 500 MB 초과 파일을 지원하지 않습니다 (실제 페이지 제한)')
                button=page.locator(site.selectors).first
                button.wait_for(state='visible',timeout=deadline.budget_ms(15000))
                button.click(timeout=deadline.budget_ms(15000))
                confirmation_submitted = False
                while deadline.remaining()>0 and not captured:
                    if page.locator('.g-recaptcha:visible, iframe[src*="recaptcha"]:visible, iframe[src*="hcaptcha"]:visible').count():
                        raise HosterParseError('Rapidgator 다운로드에 사람 확인 캡차가 필요합니다; 자동 반복하지 않습니다')
                    # The live free flow advances to /download/captcha. Its
                    # normal Turnstile callback fills verifyCode, then the page
                    # still needs its published Send action. Never fabricate a
                    # token or submit that form more than once.
                    form = page.locator('form#captchaform[action="/download/captcha"]:visible')
                    if form.count():
                        if confirmation_submitted:
                            raise HosterParseError('Rapidgator 확인 폼 제출 후 다시 사람 확인을 요구했습니다; 자동 반복 없음')
                        token = form.locator('input[name="DownloadCaptchaForm[verifyCode]"]').first
                        if token.count() and token.input_value(timeout=deadline.budget_ms(1000)):
                            submit = form.locator('#submit-button:visible').first
                            if not submit.count():
                                raise HosterParseError('Rapidgator 확인 폼의 제출 버튼을 확인하지 못했습니다; 자동 반복 없음')
                            confirmation_submitted = True
                            submit.click(timeout=deadline.budget_ms(15000))
                            page.wait_for_timeout(deadline.budget_ms(1000))
                    page.wait_for_timeout(deadline.budget_ms(500))
                if len(set(captured))!=1:raise HosterParseError('전용 파서: Rapidgator 무료 단회 요청에서 파일 주소를 확인하지 못했습니다')
                link=captured[0]
            else:
                locator=page.locator(site.selectors+':visible').first
                locator.wait_for(state='visible',timeout=deadline.budget_ms(15000))
                link=_candidate(site,locator.get_attribute('href'),page.url,url)
                if not link:raise HosterParseError(f'전용 파서: {site.name} 동적 다운로드 주소를 확인하지 못했습니다')
            cookies={c['name']:c['value'] for c in context.cookies([link])}
            return HosterParseResult(link,_metadata(BeautifulSoup(page.content(),'html.parser')) or None,cookies=cookies,user_agent=page.evaluate('navigator.userAgent'),referer=page.url).as_parse_result()
        except HosterParseError:
            raise
        except Exception as exc:
            raise HosterParseError(f'전용 파서: {site.name} 브라우저 흐름이 완료되지 않았습니다; 자동 반복 없음') from exc
        finally:
            try:
                key = hashlib.sha256(url.encode()).hexdigest()[:16]
                path = Path(CONFIG_DIR) / f'host_browser_{key}.html'
                path.write_text(page.content()); path.chmod(0o600)
                context.storage_state(path=str(Path(CONFIG_DIR) / f'host_browser_{key}_session-private.json'))
                meta = Path(CONFIG_DIR) / f'host_browser_{key}_context-private.json'
                meta.write_text(json.dumps({'url':page.url, 'user_agent':page.evaluate('navigator.userAgent')})); meta.chmod(0o600)
                page.screenshot(path=str(Path(CONFIG_DIR) / f'host_browser_{key}.png'), timeout=3000)
            except Exception:
                pass
            instance.close()


def parse_filekeeper_sync(url,proxies=None): return parse_site('filekeeper',url,proxies)
def parse_tusfiles_sync(url,proxies=None): return parse_site('tusfiles',url,proxies)
def parse_uptobox_sync(url,proxies=None): return parse_site('uptobox',url,proxies)
def parse_clicknupload_sync(url,proxies=None): return parse_site('clicknupload',url,proxies)
def parse_clickndownload_sync(url,proxies=None): return parse_site('clickndownload',url,proxies)
def parse_sendcm_sync(url,proxies=None): return parse_site('sendcm',url,proxies)
def parse_sendnow_sync(url,proxies=None): return parse_site('sendnow',url,proxies)
def parse_filerio_sync(url,proxies=None): return parse_site('filerio',url,proxies)
def parse_frdl_sync(url,proxies=None): return parse_site('frdl',url,proxies)
def parse_letsupload_sync(url,proxies=None): return parse_site('letsupload',url,proxies)
def parse_bowfile_sync(url,proxies=None): return parse_site('bowfile',url,proxies)
def parse_doodrive_sync(url,proxies=None): return parse_site('doodrive',url,proxies)
def parse_solidfiles_sync(url,proxies=None): return parse_site('solidfiles',url,proxies)
def parse_bayfiles_sync(url,proxies=None): return parse_site('bayfiles',url,proxies)
def parse_qiwi_sync(url,proxies=None): return parse_site('qiwi',url,proxies)
def parse_zippyshare_sync(url,proxies=None): return parse_site('zippyshare',url,proxies)
def parse_teraboxapp_sync(url,proxies=None): return parse_site('teraboxapp',url,proxies)
def parse_rapidgator_free_sync(url,proxies=None): return parse_site('rapidgator_free',url,proxies)
