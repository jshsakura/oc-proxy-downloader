# -*- coding: utf-8 -*-
"""
Simple 1fichier parsing logic
1. Extract file name / size
2. Parse wait time (precisely, from the button text)
3. Simulate a click after waiting
"""

import re
import time
from datetime import datetime, timezone
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse
from services.notification_service import send_telegram_wait_notification
from core.config import CONFIG_DIR
from core import cancel_signal
from core.hoster_parsers import get_flaresolverr_context_for_url


def _save_parse_debug(stage: str, status_code, body_text):
    """On parse failure, save the response body to ``<config>/parse_debug_<stage>.html``.

    Even in environments where the user has trouble accessing docker logs
    (TrueNAS Apps, etc.), it can be downloaded via
    ``GET /api/debug/last-parse-response`` or the debug link in the detail
    modal for patch analysis.
    """
    try:
        path = CONFIG_DIR / f"parse_debug_{stage}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"<!-- saved at {datetime.now(timezone.utc).isoformat()}, status={status_code} -->\n")
            f.write(body_text or "")
        print(f"[LOG] 파싱 응답 본문을 디버그 파일로 저장: {path}")
    except Exception as save_err:
        print(f"[WARNING] 파싱 디버그 저장 실패: {save_err}")


# 1fichier download host pattern (a-1.1fichier.com, cdn-2.1fichier.com, s17.1fichier.com, etc.)
_DOWNLOAD_HOST_RE = re.compile(
    r"^https?://(?:a-\d+|cdn-\d+|[a-z]-\d+|[a-z]+\d+|download|dl)\.1fichier\.com/",
    re.IGNORECASE,
)

# 1fichier pages that are clearly not download links (excluded)
_EXCLUDE_PATH_KEYWORDS = (
    "/cgu", "/cgv", "/mentions", "/privacy", "/about", "/tarifs",
    "/premium", "/console", "/register", "/login", "/contact", "/faq",
    "/abus", "/hlp", "/api.html", "/help",
)


_FICHIER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}")


def _extract_1fichier_file_id(raw_query: str) -> str:
    """Safely extract only the file ID from a 1fichier raw query.

    When the same URL is pasted twice without a space, the query becomes
    ``<id>https://1fichier.com/?<id>``. In that case we must cut before the
    second URL so we don't produce an invalid file ID that causes a 404.
    """
    value = (raw_query or "").strip()
    if not value:
        return ""

    value = value.split("&", 1)[0].strip()
    lower = value.lower()
    for marker in ("https://", "http://"):
        idx = lower.find(marker, 1)
        if idx > 0:
            value = value[:idx].strip()
            lower = value.lower()

    match = _FICHIER_ID_RE.match(value)
    return match.group(0) if match else ""


def clean_1fichier_url(url):
    """Keep only the first query parameter (file ID) in a 1fichier URL and drop the rest.

    A 1fichier file page URL has the form ``https://1fichier.com/?<file_id>``,
    and extra parameters such as an affiliate tag (``&af=...``) can break
    parsing, so any query other than the file ID is removed.

    Download server hosts (e.g. ``a-1.1fichier.com``) are left untouched,
    because stripping their token query would instead cause a 404.
    """
    if not url or "1fichier.com" not in url:
        return url

    parsed = urlparse(url)

    # Never touch download server hosts
    if parsed.hostname and parsed.hostname.lower() != "1fichier.com":
        return url

    if not parsed.query:
        return url

    file_id = _extract_1fichier_file_id(parsed.query)
    if not file_id:
        return url

    return urlunparse(parsed._replace(query=file_id))


# Extract only the ID query of a 1fichier file page (e.g. ``?7abc...``). For
# download hosts, the last path segment acts like the ID, so use that instead.
_FICHIER_PATH_ID_RE = re.compile(r"/(?:c/)?([A-Za-z0-9_-]{6,})/?$")


def is_1fichier_placeholder_name(name: str) -> bool:
    """Check whether this is a temporary display name built from a URL (``1fichier:<id>``)."""
    return isinstance(name, str) and name.strip().lower().startswith("1fichier:")


def is_1fichier_file_page_url(url: str) -> bool:
    """Check whether this is a re-parseable 1fichier file page URL."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return False

    host = (parsed.hostname or "").lower()
    return host == "1fichier.com" and bool(_extract_1fichier_file_id(parsed.query))


def choose_1fichier_parse_url(*urls: str) -> str:
    """Pick the original 1fichier file page (for re-parsing) from the candidate URLs."""
    for candidate in urls:
        if not candidate or "1fichier.com" not in candidate:
            continue
        cleaned = clean_1fichier_url(candidate)
        if is_1fichier_file_page_url(cleaned):
            return cleaned
    return ""


def derive_display_name(url: str) -> str:
    """Immediately derive a user-displayable identifier from the URL, even before parsing.

    This avoids exposing a fallback like ``Unknown`` before the file name is
    known. For 1fichier it returns the file ID as ``1fichier:<id>``; otherwise
    it returns the last path segment or the host name. Always returns a short,
    non-empty string.
    """
    if not url:
        return "(no url)"

    try:
        parsed = urlparse(url)
    except ValueError:
        return url[:64]

    host = (parsed.hostname or "").lower()

    if "1fichier.com" in host:
        # File page: 1fichier.com/?XXXX
        if parsed.query:
            file_id = _extract_1fichier_file_id(parsed.query)
            if file_id:
                return f"1fichier:{file_id}"
        # Download server: a-1.1fichier.com/c/XXXX
        m = _FICHIER_PATH_ID_RE.search(parsed.path or "")
        if m:
            return f"1fichier:{m.group(1)}"

    # MEGA: the id sits in the fragment (#!id!key) or path (/file/id), and the
    # real name only comes from decrypting attributes during the download. Show
    # the file id meanwhile so it's an identifier (and dot-free → replaceable).
    if "mega.nz" in host or "mega.co.nz" in host or "mega.io" in host:
        frag = parsed.fragment or ""
        if frag.startswith("!"):
            return f"mega:{frag[1:].split('!', 1)[0]}"
        if "/file/" in (parsed.path or ""):
            return f"mega:{parsed.path.split('/file/', 1)[1].split('/', 1)[0]}"

    # Generic URL: last path segment, falling back to the host
    path = (parsed.path or "").rstrip("/")
    if path:
        last = path.rsplit("/", 1)[-1]
        if last:
            return last
    if host:
        return host
    return url[:64]


def detect_block_reason(html_content):
    """Identify an explicit block/expiry reason in 1fichier response HTML.

    1fichier often responds with status 200 while the body still reveals
    states such as:

    - VPS/VPN IP block ("Accès restreint", "professional infrastructure detected")
    - File deleted or reported ("File not found", "removed", "deleted")
    - The Cloudflare challenge page exposed as-is
    - A temporary maintenance page

    In these cases there is no form, so ``parse_1fichier_simple_sync`` raises
    ``다운로드 폼을 찾을 수 없음`` and the user cannot tell the real cause.
    This function picks out the block reason from the body and returns it as a
    Korean keyword, or returns ``None`` if there is no match.
    """
    if not html_content:
        return None

    text = html_content.lower()

    block_rules = (
        # VPS/VPN/proxy block
        ("accès restreint", "VPS/VPN IP 차단"),
        ("acces restreint", "VPS/VPN IP 차단"),
        ("professional infrastructure detected", "VPS/VPN IP 차단"),
        ("server, proxy, vpn", "VPS/VPN IP 차단"),
        ("unauthorized personal vpn", "VPS/VPN IP 차단"),
        # File status
        ("file not found", "파일 없음 또는 삭제됨"),
        ("the file has been deleted", "파일 삭제됨"),
        ("the requested file has been removed", "파일 삭제됨"),
        ("le fichier a été supprimé", "파일 삭제됨"),
        ("file has been reported", "파일이 신고되어 차단됨"),
        # Quota / rate limit
        ("you must wait", None),  # A wait time is the normal flow, so ignore it (marked with None)
        ("limited to 1 download", "무료 다운로드 한도 초과"),
        # Guest slots full — can be bypassed by logging in as a registered (free) user
        ("free download is temporarily limited", "무료 게스트 슬롯이 가득 참 (1fichier 무료 계정 로그인 필요)"),
        ("all free guest slots are currently in use", "무료 게스트 슬롯이 가득 참 (1fichier 무료 계정 로그인 필요)"),
        ("free slots are available right now for registered users", "무료 게스트 슬롯이 가득 참 (1fichier 무료 계정 로그인 필요)"),
        # Cloudflare challenge
        ("attention required! | cloudflare", "Cloudflare 챌린지(우회 실패)"),
        ("checking your browser before accessing", "Cloudflare 챌린지(우회 실패)"),
    )

    for needle, reason in block_rules:
        if needle in text:
            return reason  # None means "ignore"

    return None


def is_likely_download_url(candidate, base_host=None):
    """Decide whether a candidate URL is likely a real download link."""
    if not candidate or not isinstance(candidate, str):
        return False

    lowered = candidate.lower()

    # Exclude obvious static assets
    for ext in (".css", ".js", ".png", ".jpg", ".jpeg", ".ico", ".svg", "favicon", "logo"):
        if ext in lowered:
            return False

    # Exclude menu / terms / console pages
    for keyword in _EXCLUDE_PATH_KEYWORDS:
        if keyword in lowered:
            return False

    # A download server host passes immediately
    if _DOWNLOAD_HOST_RE.match(candidate):
        return True

    # The 1fichier main domain itself is treated as a (non-download) page
    parsed = urlparse(candidate)
    if parsed.hostname and parsed.hostname.lower() == "1fichier.com":
        return False

    # Allow another 1fichier subdomain with a long path that looks like a file identifier
    if parsed.hostname and parsed.hostname.lower().endswith(".1fichier.com"):
        last_segment = parsed.path.rsplit("/", 1)[-1]
        if len(last_segment) >= 5:
            return True

    return False


# Upper bound for a 1fichier free wait. Normal free waits are <= ~16 min; a value
# beyond this means a daily/rate limit (or a bad parse), so we fail fast with a
# clear reason instead of sitting in "parsing/waiting" for hours.
MAX_WAIT_SECONDS = 30 * 60


# Markers of an unsolved Cloudflare challenge page/response.
_CLOUDFLARE_MARKERS = (
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "just a moment",
    "challenge-platform",
    "cf_chl",
    "cf-turnstile",
)


def _is_cloudflare_block(response) -> bool:
    """True if cloudscraper failed to pass a Cloudflare challenge.

    Covers both the non-200 challenge (403/503 + body markers / cf-mitigated
    header) and the 200-but-challenge-body case, so the caller can fall back to
    FlareSolverr before raising.
    """
    headers = getattr(response, "headers", {}) or {}
    if str(headers.get("cf-mitigated", "")).lower() == "challenge":
        return True
    body = (getattr(response, "text", "") or "").lower()
    return any(marker in body for marker in _CLOUDFLARE_MARKERS)


def parse_1fichier_simple_sync(url, password=None, proxies=None, proxy_addr=None, download_id=None, sse_callback=None,
                               account_cookies=None):
    """
    Simple 1fichier parsing logic
    1. Extract file info
    2. Extract wait time
    3. Acquire the download link after waiting

    ``account_cookies`` (dict) — the 1fichier login session cookies returned by
    ``fichier_auth.get_session_cookies()``. Injecting them into cloudscraper's
    cookies works around guest cases like ``Free guest slots are full``.
    """

    def create_fresh_scraper():
        """Create a fresh CloudScraper instance each time."""
        s = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
        if account_cookies:
            for name, value in account_cookies.items():
                try:
                    s.cookies.set(name, value, domain=".1fichier.com")
                except Exception:
                    pass
        return s

    # Scraper for the first page load (account cookies are pre-injected if present)
    scraper = create_fresh_scraper()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }
    
    try:
        # Step 1: load the page
        print(f"[LOG] 1fichier 페이지 로드: {url}")

        # Strip unnecessary params like &af (keep only the file ID, preserve the download host)
        cleaned_url = clean_1fichier_url(url)
        if cleaned_url != url:
            print(f"[LOG] 불필요한 URL 파라미터 제거 후: {cleaned_url}")
            url = cleaned_url

        print(f"[DEBUG] 사용 중인 프록시: {proxies}")
        print(f"[DEBUG] 헤더: {headers}")

        try:
            # Use a longer timeout when going through a proxy
            timeout_val = (30, 60) if proxies else (10, 30)
            print(f"[DEBUG] 타임아웃 설정: {timeout_val} (연결, 읽기)")
            response = scraper.get(url, headers=headers, proxies=proxies, timeout=timeout_val)
            print(f"[DEBUG] 응답 코드: {response.status_code}")
            print(f"[DEBUG] 응답 헤더: {dict(response.headers)}")
        except Exception as e:
            print(f"[ERROR] 페이지 로드 중 예외 발생: {e}")
            raise e

        # Always save the GET response for debugging (so the flow is traceable even on success)
        _save_parse_debug("get", response.status_code, response.text)

        # Cloudflare fallback: cloudscraper alone often can't pass modern CF
        # challenges. If the response looks like an unsolved challenge, obtain
        # cf_clearance cookies via FlareSolverr (a real browser) once, inject
        # them into the scraper, and retry the GET before giving up.
        if _is_cloudflare_block(response):
            print(f"[LOG] 1fichier Cloudflare 차단 감지 → FlareSolverr 폴백 시도")
            cf_context = get_flaresolverr_context_for_url(url, referer=url, proxies=proxies)
            cf_cookies = cf_context.get("cookies") or {}
            if cf_cookies:
                for name, value in cf_cookies.items():
                    try:
                        scraper.cookies.set(name, value, domain=".1fichier.com")
                    except Exception:
                        pass
                cf_ua = cf_context.get("user_agent")
                if cf_ua:
                    headers['User-Agent'] = cf_ua
                print(f"[LOG] FlareSolverr 쿠키 확보({list(cf_cookies.keys())}), 페이지 재요청")
                response = scraper.get(url, headers=headers, proxies=proxies, timeout=timeout_val)
                print(f"[DEBUG] FlareSolverr 폴백 후 응답 코드: {response.status_code}")
                _save_parse_debug("get_cf_retry", response.status_code, response.text)
            else:
                print(f"[WARNING] FlareSolverr 쿠키 확보 실패 — Cloudflare 우회 불가")

        if response.status_code != 200:
            print(f"[ERROR] 페이지 로드 실패 - 응답 내용: {response.text[:500]}")
            raise Exception(f"페이지 로드 실패: HTTP {response.status_code}")

        # Step 1.5: detect a block reason in the body (the 200-but-no-form case)
        block_reason = detect_block_reason(response.text)
        if block_reason:
            print(f"[ERROR] 1fichier 페이지 차단 감지: {block_reason}")
            raise Exception(f"1fichier 차단: {block_reason}")

        # Step 2: extract file info
        print(f"[DEBUG] HTML 미리보기 (처음 500자):")
        print(response.text[:500])
        print(f"[DEBUG] ===")

        file_info = extract_file_info_simple(response.text)
        if file_info:
            print(f"[LOG] 파일명: {file_info.get('name', 'Unknown')}")
            print(f"[LOG] 파일크기: {file_info.get('size', 'Unknown')}")
        else:
            print(f"[WARNING] 파일 정보 추출 실패")
        
        # Step 3: extract the wait time (precisely, from the button text)
        wait_seconds = extract_wait_time_from_button(response.text)
        if wait_seconds and wait_seconds > MAX_WAIT_SECONDS:
            # Abnormally long wait → daily/rate limit. Don't hang in "parsing".
            print(f"[LOG] 대기시간 과다: {wait_seconds}초 (상한 {MAX_WAIT_SECONDS}초)")
            # Embed the wait as "you must wait N minutes" so classify_error's
            # _extract_retry_after captures the *real* wait — the next_retry_at
            # then reflects when 1fichier actually unlocks, instead of defaulting
            # to 10 min. ("대기시간이 너무" still routes it to the rate_limited kind.)
            raise Exception(
                f"1fichier 대기시간이 너무 깁니다 — 무료 다운로드 한도 "
                f"(you must wait {wait_seconds // 60} minutes)"
            )
        if wait_seconds:
            print(f"[LOG] 대기시간: {wait_seconds}초")

            # Send a Telegram wait-time notification (only when 5 minutes or more)
            if file_info:
                wait_minutes = wait_seconds // 60
                if wait_minutes >= 5:
                    file_name = file_info.get('name', 'Unknown')
                    file_size_str = file_info.get('size', 'Unknown')
                    send_telegram_wait_notification(file_name, wait_minutes, "ko", file_size_str)

            # Step 4: wait precisely (SSE countdown + cancel signal)
            print(f"[LOG] {wait_seconds}초 대기 시작...")
            cancelled = _run_wait_countdown(
                wait_seconds=wait_seconds,
                download_id=download_id,
                sse_callback=sse_callback,
            )
            if cancelled:
                print(f"[LOG] 대기 중 정지 감지, 파싱 중단 (id={download_id})")
                return None
            print(f"[LOG] 대기 완료!")


        # Re-check the cancel signal before acquiring the link (in-memory, no DB query)
        if download_id and cancel_signal.is_cancelled(download_id):
            print(f"[LOG] 다운로드 링크 획득 전 정지 감지, 파싱 중단 (id={download_id})")
            return None

        # Step 5: simulate the download button click (keep the same session after waiting)
        download_link = None
        try:
            # POST with the same scraper to keep the session. Pass download_id /
            # sse_callback along so any extra wait between retries also reacts to
            # cancel_signal immediately and drives the UI countdown SSE.
            download_link = simulate_download_click(
                scraper, url, response.text, password, headers, proxies,
                download_id=download_id, sse_callback=sse_callback,
            )
            print(f"[LOG] 다운로드 링크 획득 성공: {download_link}")
        except Exception as download_error:
            # If interrupted by a user stop, return None (it's a stop, not a failure)
            if download_id and cancel_signal.is_cancelled(download_id):
                print(f"[LOG] 사용자 정지 감지 — 파싱 중단 (id={download_id})")
                return None
            print(f"[ERROR] 다운로드 링크 추출 실패: {download_error}")
            raise download_error

        # No download link means failure
        if not download_link:
            raise Exception("다운로드 링크를 찾을 수 없음")

        # Extract the cloudscraper session cookies as a dict (reused for the aiohttp download)
        try:
            session_cookies = {c.name: c.value for c in scraper.cookies}
        except Exception as cookie_error:
            print(f"[WARNING] 쿠키 추출 실패: {cookie_error}")
            session_cookies = {}

        result = {
            'download_link': download_link,
            'file_info': file_info,
            'wait_time': wait_seconds,
            'cookies': session_cookies,
            'user_agent': headers.get('User-Agent'),
            'referer': url,
        }
        print(f"[DEBUG] 파싱 결과 반환: download_link={download_link is not None}, file_info={file_info is not None}, wait_time={wait_seconds}, cookies={len(session_cookies)}")
        return result
        
    except Exception as e:
        print(f"[ERROR] 1fichier 파싱 실패: {e}")
        raise e


def extract_file_info_simple(html_content):
    """Extract file info (name, size) — based on the 1fichier premium table structure."""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        file_info = {}

        # 1. First find the table containing the QR code (the most reliable anchor)
        qr_img = soup.find('img', src=lambda s: s and 'qr.pl' in s)
        if qr_img:
            info_table = qr_img.find_parent('table')
            if info_table:
                td_normal = info_table.find('td', class_='normal')
                if td_normal:
                    spans = td_normal.find_all('span')
                    if len(spans) >= 2:
                        # First span is the file name, second span is the size
                        filename = spans[0].get_text(strip=True)
                        size = spans[1].get_text(strip=True)

                        if filename and not any(x in filename.lower() for x in ['1fichier', 'cloud storage', 'error']):
                            file_info['name'] = filename
                            print(f"[DEBUG] QR 코드 테이블 구조에서 파일명 추출: {filename}")

                        # Double-check that the size string has a unit
                        if size and ('GB' in size or 'MB' in size or 'KB' in size or 'TB' in size):
                            file_info['size'] = size
                            print(f"[DEBUG] QR 코드 테이블 구조에서 파일크기 추출: {size}")

        # 2. If nothing was found above, fall back to regex
        if not file_info.get('name'):
            filename_patterns = [
                r'<h1[^>]*>([^<]+)</h1>',
                r'<title>([^<]+)</title>',
                r'File name[^:]*:\s*([^\n\r<]+)',
                r'Nom du fichier[^:]*:\s*([^\n\r<]+)',
            ]

            for pattern in filename_patterns:
                match = re.search(pattern, html_content, re.IGNORECASE)
                if match:
                    filename = match.group(1).strip()
                    # Clean up the title tag
                    if 'title' in pattern:
                        filename = re.sub(r'\s*-\s*1fichier\.com.*', '', filename, flags=re.I).strip()
                    if filename and not any(x in filename.lower() for x in ['1fichier', 'cloud storage', 'error']):
                        file_info['name'] = filename
                        print(f"[DEBUG] 정규식으로 파일명 추출: {filename}")
                        break

        if not file_info.get('size'):
            size_patterns = [
                r'File size[^:]*:\s*<strong>([^<]+)</strong>', # File size: <strong>1.52 GB</strong>
                r'Size[^:]*:\s*<strong>([^<]+)</strong>',
                r'>\s*(\d+(?:\.\d+)?\s*[KMGT]B)\s*<', # > 1.52 GB <
                r'\(\s*(\d+(?:\.\d+)?\s*[KMGT]B)\s*\)', # (1.52 GB)
            ]

            for pattern in size_patterns:
                match = re.search(pattern, html_content, re.IGNORECASE)
                if match:
                    # Patterns with parentheses may have two groups
                    size_text = match.group(match.lastindex or 1).strip()
                    file_info['size'] = size_text
                    print(f"[DEBUG] 정규식으로 파일크기 추출: {file_info['size']}")
                    break

        return file_info if file_info else None

    except Exception as e:
        print(f"[ERROR] 파일 정보 추출 실패: {e}")
        return None


def preparse_1fichier_standalone(url):
    """Preparse a 1fichier URL — uses cloudscraper, runs standalone."""

    # Exit immediately if it is not a 1fichier URL
    if "1fichier.com" not in url:
        print(f"[WARNING] 1fichier URL이 아니므로 사전파싱을 건너뜁니다: {url}")
        return None

    try:

        print(f"[LOG] 사전파싱 시작: {url}")

        # Strip unnecessary params like &af (keep only the file ID, preserve the download host)
        cleaned_url = clean_1fichier_url(url)
        if cleaned_url != url:
            print(f"[LOG] 사전파싱 URL 정리: {cleaned_url}")
            url = cleaned_url

        # Create a fresh scraper for preparsing
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }

        # Load the page
        response = scraper.get(url, headers=headers, timeout=(10, 30))

        if response.status_code != 200:
            print(f"[ERROR] 사전파싱 실패: HTTP {response.status_code}")
            return None

        # If the body contains a block reason, mark preparse as failed (the main parse will raise the same way)
        block_reason = detect_block_reason(response.text)
        if block_reason:
            print(f"[WARNING] 사전파싱: 차단 감지 - {block_reason}")
            return None

        # Extract file info
        file_info = extract_file_info_simple(response.text)

        if file_info:
            print(f"[LOG] 사전파싱 성공: {file_info}")
            return file_info
        else:
            print(f"[WARNING] 사전파싱: 파일 정보 추출 실패")
            return None

    except Exception as e:
        print(f"[ERROR] 사전파싱 실패: {e}")
        return None


def extract_wait_time_from_button(html_content):
    """Extract the actual wait time from HTML — using the seconds value shown on the button as-is."""
    try:
        print(f"[DEBUG] 대기시간 추출을 위한 HTML 검색 중...")

        # Check the JavaScript ct variable (most accurate)
        # 1. Expression pattern (ct = 3*60)
        ct_calc_patterns = [
            r'var\s+ct\s*=\s*([0-9]+)\s*\*\s*([0-9]+)',  # ct = 3*60
            r'ct\s*=\s*([0-9]+)\s*\*\s*([0-9]+)',
        ]

        for pattern in ct_calc_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                num1, num2 = int(match.group(1)), int(match.group(2))
                wait_time = num1 * num2
                print(f"[LOG] JavaScript 계산식에서 대기시간 추출: {num1}*{num2} = {wait_time}초")
                return wait_time

        # 2. Plain value pattern (ct = 60, ct = 180, etc.)
        ct_simple_patterns = [
            r'var\s+ct\s*=\s*([0-9]+)',  # ct = 60
            r'ct\s*=\s*([0-9]+)',
        ]

        for pattern in ct_simple_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                wait_time = int(match.group(1))
                # Trust only values of 60 seconds or more (small values may be for the countdown)
                if wait_time >= 60:
                    print(f"[LOG] JavaScript 단순값에서 대기시간 추출: {wait_time}초")
                    return wait_time

        # Check wait time given in minutes
        minute_patterns = [
            r'You\s+must\s+wait\s+([0-9]+)\s+minutes?',
            r'wait\s+([0-9]+)\s+minutes?',
            r'([0-9]+)\s+minutes?\s+wait',
        ]

        for pattern in minute_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                wait_minutes = int(match.group(1))
                wait_time = wait_minutes * 60  # Convert minutes to seconds
                print(f"[LOG] 분 단위 대기시간 발견: {wait_minutes}분 = {wait_time}초")
                return wait_time

        # Extract only ASCII digits from the button text (excluding emoji digits)
        button_patterns = [
            r'Free\s+download\s+in\s+.*?([0-9]+)',
            r'Please\s+wait\s+([0-9]+)',
            r'Download\s+in\s+([0-9]+)',
        ]

        for pattern in button_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                wait_time = int(match.group(1))
                if 1 <= wait_time <= 86400:
                    print(f"[LOG] 버튼 텍스트에서 대기시간 추출: {wait_time}초")
                    return wait_time

        print(f"[LOG] 대기시간을 찾을 수 없음")
        return None
        
    except Exception as e:
        print(f"[ERROR] 대기시간 추출 실패: {e}")
        return None


def pick_download_link_from_html(soup, raw_html=""):
    """Pick a real download-link candidate from 1fichier response HTML.

    Priority:
      1. An ``<a href>`` starting with a download server host (``a-X``, ``cdn-X``, etc.)
      2. An ``<a>`` with one of 1fichier's standard download button ids
         (``ok``, ``dlw``, ``dl``)
      3. A ``<form action>`` pointing to a download host
      4. An ``<a href>`` whose text is ``download`` / ``click here`` /
         ``télécharger`` — must pass ``is_likely_download_url``
      5. A URL inside a JavaScript redirect (``location.href = "..."``)
      6. A regex match in the raw HTML — must pass ``is_likely_download_url``
    """
    if soup is None:
        return None

    text_keywords = ('download', 'click here', 'télécharger', 'telecharger')
    keyword_candidates = []

    def _absolutize(href):
        if not href:
            return None
        if href.startswith('/'):
            return f"https://1fichier.com{href}"
        return href

    # Priority 1 + 2: scan <a> tags
    for link in soup.find_all('a', href=True):
        absolute = _absolutize(link.get('href'))
        if not absolute:
            continue

        if _DOWNLOAD_HOST_RE.match(absolute):
            return absolute

        # Prefer 1fichier's standard download button ids
        link_id = (link.get('id') or '').lower()
        if link_id in ('ok', 'dlw', 'dl', 'lnk-dl', 'btn-dl') and is_likely_download_url(absolute):
            return absolute

        text = link.get_text(strip=True).lower()
        if any(keyword in text for keyword in text_keywords) and is_likely_download_url(absolute):
            keyword_candidates.append(absolute)

    # Priority 3: form action
    for form in soup.find_all('form', action=True):
        action = _absolutize(form.get('action'))
        if action and _DOWNLOAD_HOST_RE.match(action):
            return action

    # Priority 4: keyword-matched candidate (the first of those collected above)
    if keyword_candidates:
        return keyword_candidates[0]

    # Priority 5: JavaScript redirect
    if raw_html:
        js_patterns = [
            r'(?:window\.)?location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
            r'document\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']',
            r'location\.replace\s*\(\s*["\']([^"\']+)["\']\s*\)',
            r'window\.open\s*\(\s*["\']([^"\']+)["\']',
        ]
        for pattern in js_patterns:
            for match in re.findall(pattern, raw_html, re.IGNORECASE):
                absolute = _absolutize(match)
                if absolute and is_likely_download_url(absolute):
                    return absolute

    # Priority 6: regex for 1fichier subdomain URLs in the raw HTML
    if raw_html:
        # Also allow . / _ - that may appear in the file path
        general_patterns = (
            r'https?://(?:a-\d+|cdn-\d+|[a-z]-\d+|[a-z]+\d+|download|dl)\.1fichier\.com/[A-Za-z0-9_\-./]+',
            r'https?://[a-zA-Z0-9\-]+\.1fichier\.com/[A-Za-z0-9_\-./]{8,}',
        )
        for pattern in general_patterns:
            for match in re.findall(pattern, raw_html):
                cleaned = match.rstrip('.')
                if is_likely_download_url(cleaned):
                    return cleaned

    return None


# Countdown SSE refresh interval (seconds): every 5 seconds + every 1 second near the end.
_WAIT_SSE_INTERVAL = 5
_WAIT_FINAL_PHASE = 5  # Refresh every second during the last 5 seconds


def _emit(sse_callback, event_type, payload):
    """Call the SSE callback safely. The countdown continues even if it fails."""
    if not sse_callback:
        return
    try:
        sse_callback(event_type, payload)
    except Exception as sse_error:
        print(f"[WARNING] SSE 전송 실패 ({event_type}): {sse_error}")


def _run_wait_countdown(wait_seconds, download_id, sse_callback):
    """1fichier wait-time countdown.

    Returns: ``True`` if interrupted by a user stop signal, ``False`` if it
    waited to the end.

    Design:
    - If a download_id is given, react to cancellation immediately via the wait
      on ``cancel_signal.get_event(id)`` (no DB polling).
    - On entering waiting, send status_update + the first countdown immediately
      (so the UI doesn't show a 0-5 second remaining_time gap).
    - Countdown SSE every 5 seconds, and every second during the last 5 seconds.
    - On finish, send wait_countdown_complete (to avoid stale UI state).
    - The SSE payload carries structured data only — message text is i18n'd on the frontend.
    """
    if wait_seconds <= 0:
        return False

    # Entry: status transition + immediate first countdown
    _emit(sse_callback, "status_update", {
        "id": download_id, "status": "waiting", "progress": 0,
    })
    _emit(sse_callback, "waiting", {
        "id": download_id, "remaining": wait_seconds, "total": wait_seconds,
    })

    # Without a download_id, cancellation can't be detected — just sleep
    if not download_id:
        time.sleep(wait_seconds)
        return False

    event = cancel_signal.get_event(download_id)

    remaining = wait_seconds
    while remaining > 0:
        # Sleep 1 second — wake up immediately if a cancel signal arrives in between
        if event.wait(timeout=1.0):
            return True

        remaining -= 1

        # Refresh condition: every 5 seconds OR the last 5 seconds (every second)
        if remaining > 0 and (
            remaining % _WAIT_SSE_INTERVAL == 0 or remaining <= _WAIT_FINAL_PHASE
        ):
            _emit(sse_callback, "waiting", {
                "id": download_id, "remaining": remaining, "total": wait_seconds,
            })
            print(f"[DEBUG] 대기 중: {remaining}초 남음 (id={download_id})")

    # Finish: immediately clear the UI's waiting indicator
    _emit(sse_callback, "wait_countdown_complete", {"id": download_id})
    return False


# POST retry cap. Set to 3 to absorb the case where a 1fichier registered user
# is asked for one more wait cycle (the first POST responds with "saved on
# account" + a new ct count). Since the next attempt only proceeds when an
# additional wait time is found in the response, single-POST cases like
# guest/premium are unaffected.
MAX_POST_ATTEMPTS = 3


def _collect_form_data(form, password):
    """Build the POST body a real browser would send from the 1fichier download form.

    When a real browser (JS) submits the form via ``$('#f1').submit()``:
    - **Submit buttons that weren't clicked are not included.** The registered-user
      form contains ``<input type="submit" name="save" value="Save on my account">``,
      and auto-collecting it makes 1fichier interpret the action as "save to
      account" rather than a download.
    - **Unchecked checkboxes are not included.** Only those with a ``checked``
      attribute are sent.
    - hidden / text / email / password are included normally.
    """
    form_data = {}
    for input_elem in form.find_all('input'):
        name = input_elem.get('name')
        if not name:
            continue
        value = input_elem.get('value', '')
        input_type = (input_elem.get('type') or 'text').lower()

        if input_type == 'submit':
            continue

        if input_type == 'checkbox':
            if input_elem.has_attr('checked'):
                form_data[name] = value or 'on'
            continue

        if input_type == 'password' and password:
            form_data[name] = password
            continue

        if input_type in ('hidden', 'text', 'email') or value:
            form_data[name] = value

    return form_data


def _build_post_headers(base_headers, url):
    """Add the headers 1fichier expects on a POST request."""
    h = base_headers.copy()
    h.update({
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': url,
        'Origin': 'https://1fichier.com',
    })
    return h


def _extract_link_from_response(response):
    """Extract the download link from a POST response. Returns None if not found.

    For a redirect (3xx), check Location; for 200, extract a candidate from the body.
    """
    if response.status_code in (301, 302, 303, 307, 308):
        location = response.headers.get('Location')
        if location and location.startswith('/'):
            location = f"https://1fichier.com{location}"
        if location and is_likely_download_url(location):
            return location
        return None

    if response.status_code == 200:
        soup = BeautifulSoup(response.text or "", 'html.parser')
        link = pick_download_link_from_html(soup, response.text or "")
        if link:
            if link.startswith('/'):
                link = f"https://1fichier.com{link}"
            return link

    return None


def _classify_post_failure(response):
    """When all POST attempts are done and no link was found, analyze the
    response and return an Exception that is helpful to the user.
    """
    if response is None:
        return Exception("POST 응답 없음 — 네트워크 오류 가능성")

    diag_status = response.status_code
    try:
        diag_soup = BeautifulSoup(response.text or "", "html.parser")
        diag_form_count = len(diag_soup.find_all("form"))
        diag_a_count = len(diag_soup.find_all("a", href=True))
        diag_title = (diag_soup.title.string.strip()
                      if diag_soup.title and diag_soup.title.string else "")
        diag_block = detect_block_reason(response.text or "")
    except Exception:
        diag_form_count = -1
        diag_a_count = -1
        diag_title = ""
        diag_block = None

    if diag_block:
        return Exception(f"1fichier 차단: {diag_block}")

    # The case where the POST response came back as the homepage — 1fichier
    # rejected the form submission (quota/session/automation detection, etc.).
    # If the title is 'Cloud Storage' but there are no forms, it's the homepage,
    # not the download page.
    if diag_form_count == 0 and "cloud storage" in (diag_title or "").lower():
        return Exception(
            "1fichier 폼 제출 거부: 다운로드 페이지 대신 홈페이지가 반환됨 "
            "(세션 만료/한도 초과/자동화 감지 가능성, "
            f"POST status={diag_status}, a_tags={diag_a_count})"
        )

    return Exception(
        "다운로드 링크를 찾을 수 없음 "
        f"(POST status={diag_status}, title='{diag_title[:60]}', "
        f"forms={diag_form_count}, a_tags={diag_a_count})"
    )


def simulate_download_click(scraper, url, html_content, password, headers,
                            proxies, download_id=None, sse_callback=None):
    """Simulate clicking the download button.

    Find the form in the GET page HTML, collect its data, then POST. If the
    response is another wait page, extract the additional wait time and POST
    again, up to ``MAX_POST_ATTEMPTS``.

    If ``download_id`` / ``sse_callback`` are given, the additional wait between
    retries also detects cancel_signal (stopping immediately) and emits the UI
    countdown over SSE.
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    # Check the download button state (informational; the disabled state is ignored)
    download_button = soup.find('button', {'id': 'dlw'})
    if download_button:
        is_disabled = download_button.get('disabled') is not None
        button_text = download_button.get_text(strip=True)
        print(f"[LOG] 다운로드 버튼 상태: disabled={is_disabled}, text='{button_text}'")

    form = soup.find('form', {'id': 'f1'}) or soup.find('form')
    if not form:
        raise Exception("다운로드 폼을 찾을 수 없음")

    form_data = _collect_form_data(form, password)
    print(f"[LOG] 폼 데이터: {form_data}")

    post_headers = _build_post_headers(headers, url)
    timeout_val = (30, 60) if proxies else (10, 30)

    last_response = None
    for attempt in range(1, MAX_POST_ATTEMPTS + 1):
        print(f"[DEBUG] POST attempt {attempt}/{MAX_POST_ATTEMPTS} → {url}")
        try:
            response = scraper.post(
                url, data=form_data, headers=post_headers,
                proxies=proxies, timeout=timeout_val, allow_redirects=False,
            )
        except Exception as post_error:
            print(f"[ERROR] POST 요청 중 예외 발생 (attempt {attempt}): {post_error}")
            raise

        last_response = response
        print(f"[DEBUG] POST attempt {attempt} 응답 코드: {response.status_code}")

        # Save each attempt's response separately as ``parse_debug_post_<n>.html``,
        # and also update ``parse_debug_post.html`` with the latest for compatibility.
        _save_parse_debug(f"post_{attempt}", response.status_code, response.text)
        _save_parse_debug("post", response.status_code, response.text)

        link = _extract_link_from_response(response)
        if link:
            print(f"[LOG] 다운로드 링크 획득 (attempt {attempt}): {link}")
            return link

        if attempt >= MAX_POST_ATTEMPTS:
            break

        # If there's no additional wait time, further attempts are pointless.
        extra_wait = extract_wait_time_from_button(response.text or "")
        if not extra_wait:
            break
        print(f"[LOG] attempt {attempt} 응답에서 추가 대기시간 {extra_wait}초 발견 → 대기 후 재시도")

        # The retry wait goes through _run_wait_countdown — immediate cancel-signal
        # reaction + UI countdown SSE. Falls back to a plain sleep without download_id/sse_callback.
        cancelled = _run_wait_countdown(
            wait_seconds=extra_wait,
            download_id=download_id,
            sse_callback=sse_callback,
        )
        if cancelled:
            # Exited due to a user stop. Rather than classifying the last
            # response and raising, returning None so the caller can detect it
            # via cancel_signal.is_cancelled is handled by the caller
            # (parse_1fichier_simple_sync). Here we just raise the current
            # diagnostic classification — the caller has a stop-detection branch anyway.
            raise Exception("사용자 정지로 다운로드 중단")

    raise _classify_post_failure(last_response)
