"""
1fichier 파싱 서비스 모듈
- Direct Link 파싱
- 링크 만료 확인
- 파싱 로직 관리
"""

import os
import requests
import cloudscraper
import time
from .parser import fichier_parser


def get_or_parse_direct_link(req, proxies=None, use_proxy=False, force_reparse=False, proxy_addr=None):
    """다운로드 요청에서 직접 링크를 가져오거나 파싱하는 함수"""
    
    # proxy_addr이 있으면 proxies 생성 (CONNECT 터널링 사용)
    if proxy_addr and use_proxy:
        proxies = {
            'http': f'http://{proxy_addr}',
            'https': f'http://{proxy_addr}'
        }
        # print(f"[LOG] 프록시 설정: {proxy_addr}")
    
    # 강제 재파싱이 요청되었거나 기존 링크가 없는 경우
    if force_reparse or not req.direct_link:
        print(f"[LOG] direct_link 새로 파싱 (force_reparse: {force_reparse}, proxy: {proxy_addr})")
        return parse_direct_link_simple(req.url, req.password, proxies=proxies, use_proxy=use_proxy, proxy_addr=proxy_addr)
    
    # 기존 링크가 있는 경우 만료 여부 확인
    if is_direct_link_expired(req.direct_link, use_proxy=use_proxy, proxy_addr=proxy_addr):
        print(f"[LOG] 기존 direct_link가 만료됨. 재파싱 시작: {req.direct_link} (proxy: {proxy_addr})")
        return parse_direct_link_simple(req.url, req.password, proxies=proxies, use_proxy=use_proxy, proxy_addr=proxy_addr)
    
    print(f"[LOG] 기존 direct_link 재사용: {req.direct_link}")
    return req.direct_link


def parse_direct_link_simple(url, password=None, proxies=None, use_proxy=False, proxy_addr=None):
    """단순화된 1fichier Direct Link 파싱"""
    # print(f"[LOG] Direct Link 파싱 시작: {url}")
    
    scraper = cloudscraper.create_scraper()
    scraper.verify = False  # SSL 검증 비활성화
    
    # SSL 컨텍스트 설정 (hostname 체크 비활성화)
    import ssl
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # requests 세션의 SSL 설정 변경
    from requests.adapters import HTTPAdapter
    from urllib3.util.ssl_ import create_urllib3_context
    
    class NoSSLVerifyHTTPAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            context = create_urllib3_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            kwargs['ssl_context'] = context
            return super().init_poolmanager(*args, **kwargs)
    
    scraper.mount('https://', NoSSLVerifyHTTPAdapter())
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    # 프록시를 사용하는 경우
    if use_proxy and proxies:
        # print(f"[LOG] 지정된 프록시로 파싱 시도: {proxies}")
        try:
            direct_link, html_content = _parse_with_connection(scraper, url, password, headers, proxies, wait_time_limit=10, proxy_addr=proxy_addr)
            return direct_link  # 기존 호환성 유지
        except (requests.exceptions.ConnectTimeout, 
                requests.exceptions.ReadTimeout, 
                requests.exceptions.Timeout) as e:
            print(f"[LOG] 타임아웃: {e}")
            raise e  # 프록시 순환 로직에서 처리하도록 raise
        except requests.exceptions.ProxyError as e:
            error_msg = str(e)
            proxy_display = proxy_addr if proxy_addr else 'Unknown'
            if "Tunnel connection failed: 400 Bad Request" in error_msg:
                print(f"[LOG] 프록시 HTTPS 터널링 실패: {proxy_display}")
            elif "Unable to connect to proxy" in error_msg:
                print(f"[LOG] 프록시 연결 불가: {proxy_display}")
            else:
                print(f"[LOG] 프록시 연결 오류 ({proxy_display}): {e}")
            raise e  # 프록시 순환 로직에서 처리하도록 raise
        except Exception as e:
            print(f"[LOG] 파싱 예외: {e}")
            raise e
    
    # 로컬 연결을 사용하는 경우
    else:
        print(f"[LOG] 로컬 연결로 파싱 시도")
        try:
            direct_link, html_content = _parse_with_connection(scraper, url, password, headers, None, wait_time_limit=65)
            return direct_link  # 기존 호환성 유지
        except Exception as e:
            print(f"[LOG] 로컬 파싱 실패: {e}")
            raise e


def parse_direct_link_with_file_info(url, password=None, use_proxy=False, proxy_addr=None):
    """파일 정보와 함께 Direct Link 파싱"""
    scraper = cloudscraper.create_scraper()
    scraper.verify = False  # SSL 검증 비활성화
    
    # SSL 컨텍스트 설정 (hostname 체크 비활성화)
    import ssl
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # requests 세션의 SSL 설정 변경
    from requests.adapters import HTTPAdapter
    from urllib3.util.ssl_ import create_urllib3_context
    
    class NoSSLVerifyHTTPAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            context = create_urllib3_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            kwargs['ssl_context'] = context
            return super().init_poolmanager(*args, **kwargs)
    
    scraper.mount('https://', NoSSLVerifyHTTPAdapter())
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    # 프록시 설정
    proxies = None
    if use_proxy and proxy_addr:
        proxies = {
            'http': f'http://{proxy_addr}',
            'https': f'http://{proxy_addr}'
        }
    
    try:
        wait_time_limit = 10 if use_proxy else 65
        direct_link, html_content = _parse_with_connection(scraper, url, password, headers, proxies, wait_time_limit, proxy_addr=proxy_addr)
        
        if direct_link and html_content:
            # 파일 정보 추출
            file_info = fichier_parser.extract_file_info(html_content)
            return direct_link, file_info
        
        return None, None
        
    except Exception as e:
        print(f"[LOG] 파일 정보와 함께 파싱 실패: {e}")
        raise e


def _parse_with_connection(scraper, url, password, headers, proxies, wait_time_limit=10, proxy_addr=None):
    """공통 파싱 로직"""
    # 1단계: GET 요청으로 페이지 로드
    r1 = scraper.get(url, headers=headers, proxies=proxies, timeout=15)
    # print(f"[LOG] GET 응답: {r1.status_code}")
    
    if r1.status_code not in [200, 500]:
        print(f"[LOG] GET 실패: {r1.status_code}")
        return None
    
    # 대기 시간 확인 및 실제 남은 시간 계산
    import re
    
    # 1단계: 초기 대기시간 설정 값 찾기
    timer_matches = re.findall(r'setTimeout\s*\([^,]+,\s*(\d+)', r1.text)
    initial_wait_ms = 0
    for match in timer_matches:
        time_ms = int(match)
        if 1000 <= time_ms <= 65000:  # 1초~65초
            initial_wait_ms = max(initial_wait_ms, time_ms)
    
    # 2단계: 현재 남은 시간을 화면에서 추출
    remaining_time = 0
    
    # countdown, timer 관련 요소에서 남은 시간 추출
    countdown_patterns = [
        r'countdown["\']?\s*:\s*(\d+)',  # countdown: 60
        r'timer["\']?\s*:\s*(\d+)',     # timer: 45
        r'(\d+)\s*seconds?\s*remaining', # 30 seconds remaining
        r'wait["\']?\s*:\s*(\d+)',      # wait: 25
        r'timeLeft["\']?\s*:\s*(\d+)',  # timeLeft: 20
    ]
    
    for pattern in countdown_patterns:
        matches = re.findall(pattern, r1.text, re.IGNORECASE)
        for match in matches:
            remaining_seconds = int(match)
            if 0 <= remaining_seconds <= 65:
                remaining_time = max(remaining_time, remaining_seconds)
                break
        if remaining_time > 0:
            break
    
    # 3단계: JavaScript에서 동적 계산되는 시간 추출
    if remaining_time == 0:
        # 현재 시간과 시작 시간의 차이로 계산하는 패턴
        js_time_patterns = [
            r'var\s+startTime\s*=\s*(\d+)',
            r'startTime\s*=\s*(\d+)',
            r'var\s+endTime\s*=\s*(\d+)',
            r'endTime\s*=\s*(\d+)',
        ]
        
        current_timestamp = int(time.time() * 1000)  # 현재 시간 (밀리초)
        
        for pattern in js_time_patterns:
            matches = re.findall(pattern, r1.text)
            for match in matches:
                start_or_end_time = int(match)
                # 시작 시간이라면
                if start_or_end_time <= current_timestamp:
                    elapsed_ms = current_timestamp - start_or_end_time
                    if initial_wait_ms > elapsed_ms:
                        remaining_time = (initial_wait_ms - elapsed_ms) / 1000
                        break
                # 끝나는 시간이라면
                else:
                    remaining_ms = start_or_end_time - current_timestamp
                    if 0 < remaining_ms <= 65000:
                        remaining_time = remaining_ms / 1000
                        break
            if remaining_time > 0:
                break
    
    # 4단계: 남은 시간이 없다면 초기 설정값의 일부만 사용
    if remaining_time == 0 and initial_wait_ms > 0:
        initial_wait_seconds = initial_wait_ms / 1000
        # 페이지 로딩에 걸린 시간을 추정 (보통 1-3초)
        estimated_loading_time = 2
        remaining_time = max(0, initial_wait_seconds - estimated_loading_time)
    
    # 5단계: 실제 대기 처리
    if remaining_time > 0:
        actual_wait = min(remaining_time, wait_time_limit)
        print(f"[LOG] 남은 대기 시간: {remaining_time:.1f}초 (실제 대기: {actual_wait:.1f}초)")
        
        # 로컬 연결인 경우 남은 전체 시간을 기다림
        if proxies is None:
            time.sleep(remaining_time)
        else:
            time.sleep(actual_wait)
    else:
        print(f"[LOG] 대기 시간 없음 - 즉시 진행")
    
    # 2단계: POST 요청으로 다운로드 링크 획득
    payload = {'submit': 'Download'}
    if password:
        payload['pass'] = password
    
    headers_post = headers.copy()
    headers_post['Referer'] = str(url)
    
    # 2단계: POST 요청
    r2 = scraper.post(url, data=payload, headers=headers_post, proxies=proxies, timeout=15)
    # print(f"[LOG] POST 응답: {r2.status_code}")
    
    if r2.status_code == 200:
        # 1단계: 제한 상황 감지
        limit_detected = _detect_download_limits(r2.text, str(url))
        if limit_detected:
            limit_type, remaining_time = limit_detected
            
            # 카운트다운인 경우 대기 후 재시도
            if limit_type == "countdown" and isinstance(remaining_time, int):
                countdown_seconds = remaining_time
                proxy_info = f" (프록시: {proxy_addr})" if proxy_addr else " (로컬 연결)"
                print(f"[LOG] 카운트다운 감지{proxy_info}: {countdown_seconds}초 대기 후 재시도")
                
                # 안전하게 몇 초 더 대기
                actual_wait = countdown_seconds + 2
                time.sleep(actual_wait)
                
                print(f"[LOG] 카운트다운 완료 - 재시도 중{proxy_info}")
                
                # 3단계: 재시도 (같은 폼으로 POST 요청)
                r3 = scraper.post(url, data=payload, headers=headers_post, proxies=proxies, timeout=15)
                
                if r3.status_code == 200:
                    # 재시도 후 Direct Link 파싱
                    direct_link = fichier_parser.parse_download_link(r3.text, str(url))
                    if direct_link:
                        print(f"[LOG] 재시도 후 Direct Link 발견{proxy_info}: {direct_link}")
                        return direct_link, r3.text
                    else:
                        print(f"[LOG] 재시도 후에도 Direct Link를 찾을 수 없음{proxy_info}")
                        # 재시도 후에도 실패하면 카운트다운 에러로 처리
                        raise Exception(f"카운트다운 감지: {countdown_seconds}초 대기 후에도 파싱 실패")
                else:
                    print(f"[LOG] 재시도 POST 실패{proxy_info}: {r3.status_code}")
                    raise Exception(f"카운트다운 감지: {countdown_seconds}초 대기 후 재시도 실패 (HTTP {r3.status_code})")
            else:
                # 카운트다운이 아닌 다른 제한사항
                error_msg = f"1fichier 제한 감지: {limit_type}"
                if remaining_time:
                    error_msg += f" (남은 시간: {remaining_time})"
                print(f"[LOG] {error_msg}")
                raise Exception(error_msg)
        
        # 2단계: 새로운 파서 사용 (제한이 없는 경우)
        else:
            direct_link = fichier_parser.parse_download_link(r2.text, str(url))
            if direct_link:
                print(f"[LOG] Direct Link 발견: {direct_link}")
                return direct_link, r2.text  # HTML도 함께 반환하여 파일명 추출용
            else:
                print(f"[LOG] Direct Link를 찾을 수 없음")
    else:
        print(f"[LOG] POST 실패: {r2.status_code}")
    
    return None, None


def _detect_download_limits(html_content, original_url):
    """1fichier 다운로드 제한 상황 감지"""
    try:
        import re
        
        # HTML 내용 디버깅
        print(f"[DEBUG] HTML 길이: {len(html_content)} 글자")
        
        # HTML 일부 출력해서 실제 내용 확인
        if len(html_content) > 500:
            sample_start = html_content[:500]
            sample_middle = html_content[len(html_content)//2:len(html_content)//2+300] 
            print(f"[DEBUG] HTML 시작 부분: {sample_start}")
            print(f"[DEBUG] HTML 중간 부분: {sample_middle}")
        
        if 'dlw' in html_content:
            print(f"[DEBUG] HTML에서 'dlw' 발견됨")
        if 'disabled' in html_content:
            print(f"[DEBUG] HTML에서 'disabled' 발견됨")
        if 'Free download' in html_content:
            print(f"[DEBUG] HTML에서 'Free download' 발견됨")
        if 'button' in html_content.lower():
            print(f"[DEBUG] HTML에서 'button' 발견됨")
        if '1fichier' in html_content:
            print(f"[DEBUG] HTML에서 '1fichier' 발견됨")
        else:
            print(f"[DEBUG] HTML에서 '1fichier'를 찾을 수 없음 - 다른 사이트로 리다이렉트된 것 같음")
        
        # 1단계: JavaScript에서 카운트다운 시간 추출 (가장 우선순위)
        if 'id="dlw"' in html_content and 'disabled' in html_content:
            print(f"[DEBUG] dlw 버튼이 disabled 상태로 발견됨")
            
            # JavaScript 코드에서 카운트다운 시간 추출
            js_countdown_match = re.search(r'var\s+ct\s*=\s*(\d+)', html_content)
            if js_countdown_match:
                countdown_seconds = int(js_countdown_match.group(1))
                print(f"[LOG] JavaScript에서 카운트다운 감지: {countdown_seconds}초 (var ct = {countdown_seconds})")
                return ("countdown", countdown_seconds)
            
            # 다른 JavaScript 패턴도 시도
            js_patterns = [
                r'countdown["\']?\s*[:=]\s*(\d+)',  # countdown: 60 또는 countdown = 60
                r'timer["\']?\s*[:=]\s*(\d+)',     # timer: 45
                r'wait["\']?\s*[:=]\s*(\d+)',      # wait: 25
            ]
            
            for pattern in js_patterns:
                js_match = re.search(pattern, html_content, re.IGNORECASE)
                if js_match:
                    countdown_seconds = int(js_match.group(1))
                    print(f"[LOG] JavaScript 패턴에서 카운트다운 감지: {countdown_seconds}초")
                    return ("countdown", countdown_seconds)
                    
            print(f"[DEBUG] JavaScript에서 카운트다운 시간을 찾을 수 없음")
        else:
            print(f"[DEBUG] dlw 버튼이나 disabled 속성을 찾을 수 없음")
        
        # 기존 패턴들도 시도
        countdown_patterns = [
            r'Free download in.*?(\d+)',      # Free download in 47 or Free download in ⏳ 47
            r'download in.*?(\d+)',           # download in 25
            r'disabled.*?(\d+)',              # disabled button with countdown
        ]
        
        for pattern in countdown_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                countdown_seconds = int(match.group(1))
                print(f"[LOG] 카운트다운 패턴 매칭됨: '{pattern}' -> {countdown_seconds}초")
                return ("countdown", countdown_seconds)
        
        # 2단계: "You must wait X minutes" 형태의 메시지
        wait_patterns = [
            (r'You must wait\s+(\d+)\s+minutes?', "대기 시간"),
            (r'must wait\s+(\d+)\s+minutes?', "대기 시간"), 
            (r'wait\s+(\d+)\s+minutes?', "대기 시간"),
            (r'vous devez attendre\s+(\d+)', "대기 시간"),
        ]
        
        for pattern, limit_type in wait_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                wait_minutes = int(match.group(1))
                return (limit_type, f"{wait_minutes} 분")
        
        # 3단계: 프리미엄 페이지로 리다이렉트된 경우 (더 엄격한 조건)
        # dlw 버튼이 있으면 카운트다운 페이지이므로 프리미엄 체크 건너뛰기
        if 'id="dlw"' not in html_content:
            premium_indicators = [
                '/console/abo.pl' in html_content and 'id="dlw"' not in html_content,
                'premium required' in html_content.lower(),
                'premium account' in html_content.lower(), 
                'upgrade to premium' in html_content.lower()
            ]
            if any(premium_indicators):
                print(f"[DEBUG] 프리미엄 필요 감지됨 (dlw 버튼 없음)")
                return ("다운로드 제한 - 프리미엄 필요", None)
        
        # 4단계: 기타 시간 제한 메시지들
        time_limit_patterns = [
            (r'(\d+)\s*minutes?\s*before', "시간 제한"),
            (r'(\d+)\s*hours?\s*before', "시간 제한"),
            (r'please wait\s*(\d+)', "대기 시간"),
        ]
        
        for pattern, limit_type in time_limit_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                remaining_time = f"{match.group(1)} 분"
                return (limit_type, remaining_time)
        
        # 5단계: 일일 다운로드 제한
        daily_limit_keywords = [
            'daily limit',
            'limite quotidienne',
            '일일 제한',
            'download limit reached',
            'limite de téléchargement'
        ]
        
        for keyword in daily_limit_keywords:
            if keyword.lower() in html_content.lower():
                return ("일일 다운로드 제한", None)
        
        # 6단계: IP 제한
        ip_limit_keywords = [
            'ip address',
            'adresse ip',
            'too many connections',
            'trop de connexions'
        ]
        
        for keyword in ip_limit_keywords:
            if keyword.lower() in html_content.lower():
                return ("IP 제한", None)
        
        return None
        
    except Exception as e:
        print(f"[LOG] 제한 감지 중 오류: {e}")
        return None


def is_direct_link_expired(direct_link, use_proxy=False, proxy_addr=None):
    """direct_link가 만료되었는지 간단히 체크"""
    if not direct_link:
        return True
    
    # 프록시 설정
    proxies = None
    if use_proxy and proxy_addr:
        proxies = {
            'http': f'http://{proxy_addr}',
            'https': f'http://{proxy_addr}'
        }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Accept-Language': 'ko-KR,ko;q=0.9',
        'Connection': 'keep-alive',
    }
    
    try:
        # HEAD 요청으로 링크 유효성 확인
        response = requests.head(direct_link, headers=headers, timeout=(1, 3), allow_redirects=True, proxies=proxies)
        print(f"[LOG] Direct Link 유효성 검사: {response.status_code}")
        
        if response.status_code in [200, 206]:  # 200 OK 또는 206 Partial Content
            return False
        elif response.status_code in [403, 404, 410, 429]:  # 만료되거나 접근 불가
            print(f"[LOG] Direct Link 만료 감지: {response.status_code}")
            return True
        else:
            print(f"[LOG] 예상치 못한 응답: {response.status_code}")
            return True
    except Exception as e:
        print(f"[LOG] Direct Link 유효성 검사 실패: {e}")
        return True