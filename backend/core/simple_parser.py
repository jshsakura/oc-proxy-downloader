# -*- coding: utf-8 -*-
"""
1fichier 간단한 파싱 로직
1. 파일명/용량 추출
2. 대기시간 파싱 (버튼 텍스트에서 정확히)
3. 대기 후 클릭 시뮬레이션
"""

import re
import time
from datetime import datetime
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse
from services.notification_service import send_telegram_wait_notification
from core.config import CONFIG_DIR
from core import cancel_signal


def _save_parse_debug(stage: str, status_code, body_text):
    """파싱 실패 시 응답 본문을 ``<config>/parse_debug_<stage>.html`` 로 저장.

    사용자가 docker logs 접근이 어려운 환경 (TrueNAS Apps 등) 에서도
    ``GET /api/debug/last-parse-response`` 또는 상세 모달의 디버그 링크로
    내려받아 패치 분석에 사용한다.
    """
    try:
        path = CONFIG_DIR / f"parse_debug_{stage}.html"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"<!-- saved at {datetime.utcnow().isoformat()}Z, status={status_code} -->\n")
            f.write(body_text or "")
        print(f"[LOG] 파싱 응답 본문을 디버그 파일로 저장: {path}")
    except Exception as save_err:
        print(f"[WARNING] 파싱 디버그 저장 실패: {save_err}")


# 1fichier 다운로드 호스트 패턴 (a-1.1fichier.com, cdn-2.1fichier.com, s17.1fichier.com 등)
_DOWNLOAD_HOST_RE = re.compile(
    r"^https?://(?:a-\d+|cdn-\d+|[a-z]-\d+|[a-z]+\d+|download|dl)\.1fichier\.com/",
    re.IGNORECASE,
)

# 명백히 다운로드 링크가 아닌 1fichier 페이지들 (제외)
_EXCLUDE_PATH_KEYWORDS = (
    "/cgu", "/cgv", "/mentions", "/privacy", "/about", "/tarifs",
    "/premium", "/console", "/register", "/login", "/contact", "/faq",
    "/abus", "/hlp", "/api.html", "/help",
)


def clean_1fichier_url(url):
    """1fichier URL 에서 첫 번째 쿼리 파라미터(파일 ID) 만 남기고 나머지 제거.

    1fichier 의 파일 페이지 URL 은 ``https://1fichier.com/?<file_id>`` 형식이고,
    affiliate(``&af=...``) 같은 추가 파라미터가 붙으면 파싱에 실패할 수 있어
    파일 ID 외의 쿼리는 제거한다.

    다운로드 서버 호스트(예: ``a-1.1fichier.com``)는 토큰 쿼리를 잘라내면
    오히려 404 가 나기 때문에 그대로 둔다.
    """
    if not url or "1fichier.com" not in url:
        return url

    parsed = urlparse(url)

    # 다운로드 서버 호스트는 절대 건드리지 않음
    if parsed.hostname and parsed.hostname.lower() != "1fichier.com":
        return url

    if not parsed.query:
        return url

    file_id = parsed.query.split("&", 1)[0]
    if not file_id or file_id == parsed.query:
        return url

    return urlunparse(parsed._replace(query=file_id))


def detect_block_reason(html_content):
    """1fichier 응답 HTML 에서 명시적인 차단/만료 사유를 식별.

    1fichier 는 status 200 으로 응답하면서도 본문에서 다음과 같은 상태를
    드러내는 경우가 많다:

    - VPS/VPN IP 차단 ("Accès restreint", "professional infrastructure detected")
    - 파일이 삭제되었거나 신고됨 ("File not found", "removed", "deleted")
    - Cloudflare 챌린지 페이지가 그대로 노출되는 경우
    - 일시적 점검 페이지

    이런 경우 폼이 없으니 ``parse_1fichier_simple_sync`` 가 ``다운로드 폼을
    찾을 수 없음`` 을 raise 해서 사용자는 진짜 원인을 알 수 없다.
    이 함수는 본문에서 차단 사유를 골라내 한국어 키워드로 반환하거나,
    매칭이 없으면 ``None`` 을 반환한다.
    """
    if not html_content:
        return None

    text = html_content.lower()

    block_rules = (
        # VPS/VPN/프록시 차단
        ("accès restreint", "VPS/VPN IP 차단"),
        ("acces restreint", "VPS/VPN IP 차단"),
        ("professional infrastructure detected", "VPS/VPN IP 차단"),
        ("server, proxy, vpn", "VPS/VPN IP 차단"),
        ("unauthorized personal vpn", "VPS/VPN IP 차단"),
        # 파일 상태
        ("file not found", "파일 없음 또는 삭제됨"),
        ("the file has been deleted", "파일 삭제됨"),
        ("the requested file has been removed", "파일 삭제됨"),
        ("le fichier a été supprimé", "파일 삭제됨"),
        ("file has been reported", "파일이 신고되어 차단됨"),
        # 한도/속도 제한
        ("you must wait", None),  # 대기시간이면 정상 흐름이므로 무시 (None 으로 표시)
        ("limited to 1 download", "무료 다운로드 한도 초과"),
        # 게스트 슬롯 가득 참 — 등록 사용자(무료 계정) 로그인 시 우회 가능
        ("free download is temporarily limited", "무료 게스트 슬롯이 가득 참 (1fichier 무료 계정 로그인 필요)"),
        ("all free guest slots are currently in use", "무료 게스트 슬롯이 가득 참 (1fichier 무료 계정 로그인 필요)"),
        ("free slots are available right now for registered users", "무료 게스트 슬롯이 가득 참 (1fichier 무료 계정 로그인 필요)"),
        # Cloudflare 챌린지
        ("attention required! | cloudflare", "Cloudflare 챌린지(우회 실패)"),
        ("checking your browser before accessing", "Cloudflare 챌린지(우회 실패)"),
    )

    for needle, reason in block_rules:
        if needle in text:
            return reason  # None 이면 무시 의미

    return None


def is_likely_download_url(candidate, base_host=None):
    """후보 URL 이 실제 다운로드 링크일 가능성이 높은지 판단."""
    if not candidate or not isinstance(candidate, str):
        return False

    lowered = candidate.lower()

    # 명백한 정적 자산은 제외
    for ext in (".css", ".js", ".png", ".jpg", ".jpeg", ".ico", ".svg", "favicon", "logo"):
        if ext in lowered:
            return False

    # 메뉴/약관/콘솔 페이지는 제외
    for keyword in _EXCLUDE_PATH_KEYWORDS:
        if keyword in lowered:
            return False

    # 다운로드 서버 호스트면 즉시 통과
    if _DOWNLOAD_HOST_RE.match(candidate):
        return True

    # 1fichier 메인 도메인 자체는 (다운로드가 아닌) 페이지로 판단
    parsed = urlparse(candidate)
    if parsed.hostname and parsed.hostname.lower() == "1fichier.com":
        return False

    # 1fichier 의 다른 서브도메인이고 파일 식별자처럼 보이는 긴 경로면 허용
    if parsed.hostname and parsed.hostname.lower().endswith(".1fichier.com"):
        last_segment = parsed.path.rsplit("/", 1)[-1]
        if len(last_segment) >= 5:
            return True

    return False


def parse_1fichier_simple_sync(url, password=None, proxies=None, proxy_addr=None, download_id=None, sse_callback=None,
                               account_cookies=None):
    """
    1fichier 단순 파싱 로직
    1. 파일정보 추출
    2. 대기시간 추출
    3. 대기 후 다운로드 링크 획득

    ``account_cookies`` (dict) — ``fichier_auth.get_session_cookies()`` 가
    돌려준 1fichier 로그인 세션 쿠키. 이 값을 cloudscraper 의 cookies 에
    주입하면 ``Free guest slots are full`` 같은 게스트 케이스를 우회한다.
    """

    def create_fresh_scraper():
        """매번 새로운 CloudScraper 인스턴스 생성"""
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

    # 첫 페이지 로드용 스크래퍼 (계정 쿠키가 있으면 미리 주입됨)
    scraper = create_fresh_scraper()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }
    
    try:
        # 1단계: 페이지 로드
        print(f"[LOG] 1fichier 페이지 로드: {url}")

        # &af 등 불필요한 파라미터 제거 (파일 ID만 남김, 다운로드 호스트는 보존)
        cleaned_url = clean_1fichier_url(url)
        if cleaned_url != url:
            print(f"[LOG] 불필요한 URL 파라미터 제거 후: {cleaned_url}")
            url = cleaned_url
            
        print(f"[DEBUG] 사용 중인 프록시: {proxies}")
        print(f"[DEBUG] 헤더: {headers}")

        try:
            # 프록시 사용 시 더 긴 타임아웃 적용
            timeout_val = (30, 60) if proxies else (10, 30)
            print(f"[DEBUG] 타임아웃 설정: {timeout_val} (연결, 읽기)")
            response = scraper.get(url, headers=headers, proxies=proxies, timeout=timeout_val)
            print(f"[DEBUG] 응답 코드: {response.status_code}")
            print(f"[DEBUG] 응답 헤더: {dict(response.headers)}")
        except Exception as e:
            print(f"[ERROR] 페이지 로드 중 예외 발생: {e}")
            raise e

        # GET 응답은 항상 디버그용으로 저장 (성공해도 흐름 추적 가능)
        _save_parse_debug("get", response.status_code, response.text)

        if response.status_code != 200:
            print(f"[ERROR] 페이지 로드 실패 - 응답 내용: {response.text[:500]}")
            raise Exception(f"페이지 로드 실패: HTTP {response.status_code}")

        # 1.5단계: 본문 차단 사유 감지 (200 인데도 폼이 없는 케이스)
        block_reason = detect_block_reason(response.text)
        if block_reason:
            print(f"[ERROR] 1fichier 페이지 차단 감지: {block_reason}")
            raise Exception(f"1fichier 차단: {block_reason}")

        # 2단계: 파일 정보 추출
        print(f"[DEBUG] HTML 미리보기 (처음 500자):")
        print(response.text[:500])
        print(f"[DEBUG] ===")

        file_info = extract_file_info_simple(response.text)
        if file_info:
            print(f"[LOG] 파일명: {file_info.get('name', 'Unknown')}")
            print(f"[LOG] 파일크기: {file_info.get('size', 'Unknown')}")
        else:
            print(f"[WARNING] 파일 정보 추출 실패")
        
        # 3단계: 대기시간 추출 (버튼 텍스트에서 정확히)
        wait_seconds = extract_wait_time_from_button(response.text)
        if wait_seconds:
            print(f"[LOG] 대기시간: {wait_seconds}초")

            # 텔레그램 대기시간 알림 전송 (5분 이상일 때만)
            if file_info:
                wait_minutes = wait_seconds // 60
                if wait_minutes >= 5:
                    file_name = file_info.get('name', 'Unknown')
                    file_size_str = file_info.get('size', 'Unknown')
                    send_telegram_wait_notification(file_name, wait_minutes, "ko", file_size_str)

            # 4단계: 정확히 대기 (SSE 카운트다운 + cancel signal)
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


        # 다운로드 링크 획득 전 정지 신호 재확인 (DB 쿼리 없이 in-memory)
        if download_id and cancel_signal.is_cancelled(download_id):
            print(f"[LOG] 다운로드 링크 획득 전 정지 감지, 파싱 중단 (id={download_id})")
            return None

        # 5단계: 다운로드 버튼 클릭 시뮬레이션 (대기 완료 후 같은 세션 유지)
        download_link = None
        try:
            # 같은 스크래퍼로 세션 유지하며 POST 요청
            download_link = simulate_download_click(scraper, url, response.text, password, headers, proxies)
            print(f"[LOG] 다운로드 링크 획득 성공: {download_link}")
        except Exception as download_error:
            print(f"[ERROR] 다운로드 링크 추출 실패: {download_error}")
            # 모든 에러를 그대로 재시도 가능하게 처리
            raise download_error

        # 다운로드 링크가 없으면 실패
        if not download_link:
            raise Exception("다운로드 링크를 찾을 수 없음")

        # cloudscraper 세션의 쿠키를 dict로 추출 (aiohttp 다운로드 시 재사용)
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
    """파일 정보 추출 (이름, 크기) - 1fichier premium table 구조 기준"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        file_info = {}

        # 1. QR 코드가 포함된 테이블을 먼저 찾음 (가장 확실한 기준)
        qr_img = soup.find('img', src=lambda s: s and 'qr.pl' in s)
        if qr_img:
            info_table = qr_img.find_parent('table')
            if info_table:
                td_normal = info_table.find('td', class_='normal')
                if td_normal:
                    spans = td_normal.find_all('span')
                    if len(spans) >= 2:
                        # 첫번째 span이 파일명, 두번째 span이 크기
                        filename = spans[0].get_text(strip=True)
                        size = spans[1].get_text(strip=True)

                        if filename and not any(x in filename.lower() for x in ['1fichier', 'cloud storage', 'error']):
                            file_info['name'] = filename
                            print(f"[DEBUG] QR 코드 테이블 구조에서 파일명 추출: {filename}")
                        
                        # 크기 문자열에 단위가 있는지 한번 더 확인
                        if size and ('GB' in size or 'MB' in size or 'KB' in size or 'TB' in size):
                            file_info['size'] = size
                            print(f"[DEBUG] QR 코드 테이블 구조에서 파일크기 추출: {size}")

        # 2. 위에서 정보를 못찾았으면 정규식 백업
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
                    # title 태그 정리
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
                    # 괄호가 있는 패턴의 경우 그룹이 2개일 수 있음
                    size_text = match.group(match.lastindex or 1).strip()
                    file_info['size'] = size_text
                    print(f"[DEBUG] 정규식으로 파일크기 추출: {file_info['size']}")
                    break

        return file_info if file_info else None

    except Exception as e:
        print(f"[ERROR] 파일 정보 추출 실패: {e}")
        return None


def preparse_1fichier_standalone(url):
    """1fichier URL 사전파싱 - cloudscraper 사용, 단독 실행"""

    # 1fichier URL이 아니면 즉시 종료
    if "1fichier.com" not in url:
        print(f"[WARNING] 1fichier URL이 아니므로 사전파싱을 건너뜁니다: {url}")
        return None

    try:

        print(f"[LOG] 사전파싱 시작: {url}")

        # &af 등 불필요한 파라미터 제거 (파일 ID만 남김, 다운로드 호스트는 보존)
        cleaned_url = clean_1fichier_url(url)
        if cleaned_url != url:
            print(f"[LOG] 사전파싱 URL 정리: {cleaned_url}")
            url = cleaned_url

        # 사전파싱용 새 스크래퍼 생성
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

        # 페이지 로드
        response = scraper.get(url, headers=headers, timeout=(10, 30))

        if response.status_code != 200:
            print(f"[ERROR] 사전파싱 실패: HTTP {response.status_code}")
            return None

        # 차단 사유가 본문에 있으면 사전파싱 실패로 명시 (이후 본 파싱에서 동일하게 raise 됨)
        block_reason = detect_block_reason(response.text)
        if block_reason:
            print(f"[WARNING] 사전파싱: 차단 감지 - {block_reason}")
            return None

        # 파일 정보 추출
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
    """HTML에서 실제 대기시간 추출 - 버튼에 초로 표시된 그대로 사용"""
    try:
        print(f"[DEBUG] 대기시간 추출을 위한 HTML 검색 중...")

        # JavaScript ct 변수 체크 (가장 정확함)
        # 1. 계산식 패턴 (ct = 3*60)
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

        # 2. 단순 값 패턴 (ct = 60, ct = 180 등)
        ct_simple_patterns = [
            r'var\s+ct\s*=\s*([0-9]+)',  # ct = 60
            r'ct\s*=\s*([0-9]+)',
        ]

        for pattern in ct_simple_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                wait_time = int(match.group(1))
                # 60초 이상인 경우만 신뢰 (작은 값은 카운트다운용일 수 있음)
                if wait_time >= 60:
                    print(f"[LOG] JavaScript 단순값에서 대기시간 추출: {wait_time}초")
                    return wait_time

        # 분(minutes) 단위 대기시간 체크
        minute_patterns = [
            r'You\s+must\s+wait\s+([0-9]+)\s+minutes?',
            r'wait\s+([0-9]+)\s+minutes?',
            r'([0-9]+)\s+minutes?\s+wait',
        ]

        for pattern in minute_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                wait_minutes = int(match.group(1))
                wait_time = wait_minutes * 60  # 분을 초로 변환
                print(f"[LOG] 분 단위 대기시간 발견: {wait_minutes}분 = {wait_time}초")
                return wait_time

        # 버튼 텍스트에서 ASCII 숫자만 추출 (이모지 숫자 제외)
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
    """1fichier 응답 HTML 에서 실제 다운로드 링크 후보를 골라낸다.

    우선순위:
      1. 다운로드 서버 호스트(``a-X``, ``cdn-X`` 등) 로 시작하는 ``<a href>``
      2. 1fichier 가 표준으로 사용하는 다운로드 버튼 id 들 (``ok``, ``dlw``,
         ``dl``) 의 ``<a>``
      3. ``<form action>`` 이 다운로드 호스트를 가리키는 경우
      4. ``<a href>`` 중 ``download`` / ``click here`` / ``télécharger``
         텍스트를 가진 링크 — ``is_likely_download_url`` 통과해야 함
      5. JavaScript 리다이렉트 (``location.href = "..."``) 안의 URL
      6. raw HTML 정규식 매칭 — ``is_likely_download_url`` 통과해야 함
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

    # 1순위 + 2순위: <a> 태그 스캔
    for link in soup.find_all('a', href=True):
        absolute = _absolutize(link.get('href'))
        if not absolute:
            continue

        if _DOWNLOAD_HOST_RE.match(absolute):
            return absolute

        # 1fichier 표준 다운로드 버튼 id 우선
        link_id = (link.get('id') or '').lower()
        if link_id in ('ok', 'dlw', 'dl', 'lnk-dl', 'btn-dl') and is_likely_download_url(absolute):
            return absolute

        text = link.get_text(strip=True).lower()
        if any(keyword in text for keyword in text_keywords) and is_likely_download_url(absolute):
            keyword_candidates.append(absolute)

    # 3순위: form action
    for form in soup.find_all('form', action=True):
        action = _absolutize(form.get('action'))
        if action and _DOWNLOAD_HOST_RE.match(action):
            return action

    # 4순위: 키워드 매칭 후보 (위에서 모은 것 중 첫 번째)
    if keyword_candidates:
        return keyword_candidates[0]

    # 5순위: JavaScript 리다이렉트
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

    # 6순위: raw HTML 의 1fichier 서브도메인 URL 정규식
    if raw_html:
        # 파일 경로에 포함될 수 있는 . / _ - 까지 허용
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


# 카운트다운 SSE 갱신 주기 (초). 5초마다 + 마지막 1초마다 자세히.
_WAIT_SSE_INTERVAL = 5
_WAIT_FINAL_PHASE = 5  # 마지막 5초는 1초마다 갱신


def _emit(sse_callback, event_type, payload):
    """SSE 콜백을 안전하게 호출. 실패해도 카운트다운은 계속."""
    if not sse_callback:
        return
    try:
        sse_callback(event_type, payload)
    except Exception as sse_error:
        print(f"[WARNING] SSE 전송 실패 ({event_type}): {sse_error}")


def _run_wait_countdown(wait_seconds, download_id, sse_callback):
    """1fichier 대기시간 카운트다운.

    반환값: ``True`` 면 사용자 정지 신호로 중단됨, ``False`` 면 끝까지 대기.

    설계:
    - download_id 가 있으면 ``cancel_signal.get_event(id)`` 의 wait 로
      취소 즉시 반응 (DB 폴링 안 함).
    - waiting 진입 시 status_update + 첫 카운트다운 즉시 발송 (UI 가
      remaining_time 0~5초 공백을 안 보게).
    - 5초마다 + 마지막 5초는 1초마다 카운트다운 SSE.
    - 종료 시 wait_countdown_complete 발송 (UI stale state 방지).
    - SSE payload 는 구조화 데이터만 — 메시지 텍스트는 프론트 i18n.
    """
    if wait_seconds <= 0:
        return False

    # 진입: status 전이 + 즉시 첫 카운트다운
    _emit(sse_callback, "status_update", {
        "id": download_id, "status": "waiting", "progress": 0,
    })
    _emit(sse_callback, "waiting", {
        "id": download_id, "remaining": wait_seconds, "total": wait_seconds,
    })

    # download_id 가 없으면 정지 감지 불가 — 단순 sleep
    if not download_id:
        time.sleep(wait_seconds)
        return False

    event = cancel_signal.get_event(download_id)

    remaining = wait_seconds
    while remaining > 0:
        # 1초 sleep — 그 사이에 cancel signal 들어오면 즉시 깨어남
        if event.wait(timeout=1.0):
            return True

        remaining -= 1

        # 갱신 조건: 5초 단위 OR 마지막 5초 (1초마다)
        if remaining > 0 and (
            remaining % _WAIT_SSE_INTERVAL == 0 or remaining <= _WAIT_FINAL_PHASE
        ):
            _emit(sse_callback, "waiting", {
                "id": download_id, "remaining": remaining, "total": wait_seconds,
            })
            print(f"[DEBUG] 대기 중: {remaining}초 남음 (id={download_id})")

    # 종료: UI 의 waiting indicator 즉시 정리
    _emit(sse_callback, "wait_countdown_complete", {"id": download_id})
    return False


# POST 재시도 상한. 1fichier 등록 사용자가 한 번 더 대기 사이클을 요구하는
# 경우(첫 POST 가 "saved on account" + 새 ct 카운트로 응답)를 흡수하기 위해
# 3 으로 둠. 매 시도마다 응답에서 추가 대기시간이 발견될 때만 다음 시도로
# 진행하므로, 게스트/프리미엄 같은 단일-POST 케이스에는 영향 없음.
MAX_POST_ATTEMPTS = 3


def _collect_form_data(form, password):
    """1fichier 다운로드 폼에서 실제 브라우저가 보낼 POST 본문을 만든다.

    실제 브라우저(JS) 가 ``$('#f1').submit()`` 으로 폼을 제출할 때:
    - **클릭하지 않은 submit 버튼은 포함되지 않는다.** 등록 사용자 폼에는
      ``<input type="submit" name="save" value="Save on my account">`` 가
      들어있어서 이를 자동 수집하면 1fichier 가 다운로드가 아니라 "계정에
      저장" 액션으로 해석한다.
    - **unchecked 체크박스는 포함되지 않는다.** ``checked`` 속성이 있는
      것만 보낸다.
    - hidden / text / email / password 는 정상적으로 포함.
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
    """POST 요청에 1fichier 가 기대하는 헤더 추가."""
    h = base_headers.copy()
    h.update({
        'Content-Type': 'application/x-www-form-urlencoded',
        'Referer': url,
        'Origin': 'https://1fichier.com',
    })
    return h


def _extract_link_from_response(response):
    """POST 응답에서 다운로드 링크 추출. 못 찾으면 None.

    리다이렉트(3xx) 면 Location 검사, 200 이면 본문에서 후보 추출.
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
    """모든 POST 시도가 끝났는데 링크를 못 찾은 경우, 응답 분석해서
    사용자에게 도움이 되는 Exception 을 반환한다.
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

    # POST 응답이 홈페이지로 돌아온 케이스 — 1fichier 가 폼 제출을 거부
    # (한도/세션/자동화 감지 등). title 이 'Cloud Storage' 인데 form 이
    # 하나도 없으면 다운로드 페이지가 아니라 홈페이지.
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


def simulate_download_click(scraper, url, html_content, password, headers, proxies):
    """다운로드 버튼 클릭 시뮬레이션.

    GET 페이지 HTML 에서 폼을 찾아 데이터 수집 → POST. 응답이 또 대기
    페이지면 추가 대기시간 추출 후 재 POST. ``MAX_POST_ATTEMPTS`` 까지.
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    # 다운로드 버튼 상태 확인 (정보용, disabled 상태는 무시)
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

        # 시도별 응답을 ``parse_debug_post_<n>.html`` 로 분리 저장 + 최신은
        # 호환성 위해 ``parse_debug_post.html`` 도 같이 갱신.
        _save_parse_debug(f"post_{attempt}", response.status_code, response.text)
        _save_parse_debug("post", response.status_code, response.text)

        link = _extract_link_from_response(response)
        if link:
            print(f"[LOG] 다운로드 링크 획득 (attempt {attempt}): {link}")
            return link

        if attempt >= MAX_POST_ATTEMPTS:
            break

        # 추가 대기시간이 없으면 더 시도해도 의미 없음.
        extra_wait = extract_wait_time_from_button(response.text or "")
        if not extra_wait:
            break
        print(f"[LOG] attempt {attempt} 응답에서 추가 대기시간 {extra_wait}초 발견 → 대기 후 재시도")
        time.sleep(extra_wait)

    raise _classify_post_failure(last_response)