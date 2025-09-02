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
    
    # 도커 환경을 위한 강화된 CloudScraper 설정
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        },
        delay=1  # 요청 간 지연 추가
    )
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
    
    # User-Agent 로테이션을 위한 랜덤 선택
    import random
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
    ]
    
    # 도커 환경을 위한 더 완전한 브라우저 헤더
    headers = {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
        'Sec-CH-UA': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'Sec-CH-UA-Mobile': '?0',
        'Sec-CH-UA-Platform': '"Windows"'
    }
    
    # 프록시를 사용하는 경우
    if use_proxy and proxies:
        # print(f"[LOG] 지정된 프록시로 파싱 시도: {proxies}")
        try:
            direct_link, html_content = _parse_with_connection(scraper, url, password, headers, proxies, wait_time_limit=90, proxy_addr=proxy_addr)
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
            direct_link, html_content = _parse_with_connection(scraper, url, password, headers, None, wait_time_limit=90)
            return direct_link  # 기존 호환성 유지
        except requests.exceptions.SSLError as e:
            print(f"[LOG] SSL 에러 발생, 인증서 검증 비활성화하여 재시도: {e}")
            # SSL 에러인 경우 인증서 검증을 완전히 비활성화하고 재시도
            scraper.verify = False
            import urllib3
            urllib3.disable_warnings()
            try:
                direct_link, html_content = _parse_with_connection(scraper, url, password, headers, None, wait_time_limit=90)
                return direct_link
            except Exception as retry_e:
                print(f"[LOG] SSL 비활성화 후에도 실패: {retry_e}")
                raise retry_e
        except requests.exceptions.ConnectionError as e:
            print(f"[LOG] 연결 에러 발생: {e}")
            raise e
        except Exception as e:
            print(f"[LOG] 로컬 파싱 실패: {e}")
            raise e


def parse_direct_link_with_file_info(url, password=None, use_proxy=False, proxy_addr=None):
    """파일 정보와 함께 Direct Link 파싱 - 파일명을 최대한 빨리 추출하여 보존"""
    
    print(f"[LOG] 파일 정보 우선 파싱 시작: {url}")
    
    # 도커 환경을 위한 강화된 CloudScraper 설정
    scraper = cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        },
        delay=1  # 요청 간 지연 추가
    )
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
    
    # User-Agent 로테이션을 위한 랜덤 선택
    import random
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15'
    ]
    
    # 도커 환경을 위한 더 완전한 브라우저 헤더
    headers = {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
        'Sec-CH-UA': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'Sec-CH-UA-Mobile': '?0',
        'Sec-CH-UA-Platform': '"Windows"'
    }
    
    # 프록시 설정
    proxies = None
    if use_proxy and proxy_addr:
        proxies = {
            'http': f'http://{proxy_addr}',
            'https': f'http://{proxy_addr}'
        }
    
    try:
        # STEP 1: 먼저 페이지에 접근하여 파일 정보를 최대한 빨리 추출
        print(f"[LOG] 1단계: 파일명 우선 추출을 위한 초기 페이지 로드")
        try:
            initial_response = scraper.get(url, headers=headers, proxies=proxies, timeout=15)
            if initial_response.status_code == 200:
                print(f"[LOG] 초기 페이지 로드 성공 - 파일 정보 추출 시도")
                
                # 파일 정보를 가능한 한 빨리 추출
                early_file_info = fichier_parser.extract_file_info(initial_response.text)
                if early_file_info and early_file_info.get('name'):
                    print(f"[LOG] ★ 파일명 조기 추출 성공: '{early_file_info['name']}'")
                    
                    # URL로 DB에서 해당 다운로드 요청을 찾아 파일명 즉시 저장
                    try:
                        from .db import SessionLocal
                        from .models import DownloadRequest
                        temp_db = SessionLocal()
                        
                        # URL로 다운로드 요청 찾기 (최신 순)
                        download_req = temp_db.query(DownloadRequest).filter(
                            DownloadRequest.url == url
                        ).order_by(DownloadRequest.requested_at.desc()).first()
                        
                        if download_req and (not download_req.file_name or download_req.file_name.strip() == ''):
                            download_req.file_name = early_file_info['name']
                            temp_db.commit()
                            print(f"[LOG] ★ 파일명 DB 조기 저장 완료: '{early_file_info['name']}'")
                            
                            # WebSocket으로 파일명 업데이트 전송
                            try:
                                from core.shared import status_queue
                                import json
                                message = json.dumps({
                                    "type": "filename_update",
                                    "data": {
                                        "id": download_req.id,
                                        "file_name": download_req.file_name,
                                        "url": download_req.url,
                                        "status": download_req.status.value if hasattr(download_req.status, 'value') else str(download_req.status)
                                    }
                                }, ensure_ascii=False)
                                status_queue.put(message)
                            except Exception as ws_e:
                                print(f"[LOG] WebSocket 파일명 업데이트 전송 실패: {ws_e}")
                        
                        temp_db.close()
                        
                    except Exception as db_e:
                        print(f"[LOG] 파일명 DB 조기 저장 실패: {db_e}")
                else:
                    print(f"[LOG] 초기 페이지에서 파일명을 추출할 수 없음")
            else:
                print(f"[LOG] 초기 페이지 로드 실패: {initial_response.status_code}")
                
        except Exception as early_e:
            print(f"[LOG] 파일명 조기 추출 실패: {early_e}")
        
        # STEP 2: 이제 정상적인 다운로드 링크 파싱 진행
        print(f"[LOG] 2단계: 다운로드 링크 파싱 진행")
        wait_time_limit = 90 if use_proxy else 90
        direct_link, html_content = _parse_with_connection(scraper, url, password, headers, proxies, wait_time_limit, proxy_addr=proxy_addr)
        
        if direct_link and html_content:
            # Direct Link 유효성 체크
            if is_direct_link_expired(direct_link, use_proxy=use_proxy, proxy_addr=proxy_addr):
                print(f"[LOG] parse_direct_link_with_file_info에서 만료된 링크 감지: {direct_link}")
                return None, None
                
            # 파일 정보 추출 (최종 확인 및 보완)
            file_info = fichier_parser.extract_file_info(html_content)
            
            # 조기 추출한 정보와 비교하여 더 완전한 정보 사용
            if not file_info.get('name') and 'early_file_info' in locals() and early_file_info.get('name'):
                file_info['name'] = early_file_info['name']
                print(f"[LOG] ★ 조기 추출한 파일명 복원: '{file_info['name']}'")
            
            return direct_link, file_info
        
        # 다운로드 링크를 찾지 못했지만 파일 정보는 있는 경우
        if 'early_file_info' in locals() and early_file_info.get('name'):
            print(f"[LOG] 다운로드 링크 실패, 하지만 파일명은 보존: '{early_file_info['name']}'")
            return None, early_file_info
        
        return None, None
        
    except Exception as e:
        print(f"[LOG] 파일 정보와 함께 파싱 실패: {e}")
        raise e


def _parse_with_connection(scraper, url, password, headers, proxies, wait_time_limit=10, proxy_addr=None, retry_count=5):
    """공통 파싱 로직"""
    last_exception = None
    
    # 재시도 로직
    for attempt in range(retry_count):
        try:
            print(f"[LOG] GET 요청 시도 {attempt + 1}/{retry_count}: {url}")
            # 1단계: GET 요청으로 페이지 로드
            r1 = scraper.get(url, headers=headers, proxies=proxies, timeout=30)
            print(f"[LOG] GET 응답: {r1.status_code}")
            break  # 성공하면 재시도 루프 탈출
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.SSLError) as e:
            last_exception = e
            print(f"[LOG] GET 요청 실패 (시도 {attempt + 1}/{retry_count}): {e}")
            if attempt < retry_count - 1:
                import time
                wait_seconds = min(2 ** attempt, 10)  # 지수 백오프: 1, 2, 4, 8, 10초
                print(f"[LOG] {wait_seconds}초 대기 후 재시도...")
                time.sleep(wait_seconds)
                continue
            else:
                print(f"[LOG] 모든 재시도 실패")
                raise last_exception
    
    if r1.status_code not in [200, 404, 500]:
        print(f"[LOG] GET 실패: {r1.status_code}")
        return None, None
    
    # 404 에러인 경우 특별 처리
    if r1.status_code == 404:
        print(f"[LOG] GET 404 에러 - URL이 존재하지 않거나 잘못됨: {url}")
        # 404인 경우 파일이 삭제되었거나 URL이 잘못된 것으로 간주
        return None, None
    
    # cgu.html, cgv.html 등으로 리다이렉트 체크 (1fichier 안티봇 대응)
    if any(x in r1.url.lower() for x in ['cgu.html', 'cgv.html', 'tarifs.html', 'mentions.html']):
        print(f"[LOG] 1fichier 안티봇/약관 페이지로 리다이렉트 감지: {r1.url}")
        print(f"[LOG] IP 차단 또는 약관 동의 필요 - 프록시 변경 또는 대기 필요")
        return None, None
    
    # 페이지 내용에서도 약관 페이지 확인
    content_lower = r1.text.lower()
    if any(x in content_lower for x in ['conditions générales', 'terms of service', 'mentions légales']):
        print(f"[LOG] 페이지 내용이 약관/법적고지 페이지로 판단됨")
        return None, None
    
    # 대기 시간 확인 및 실제 남은 시간 계산
    import re
    
    # 1단계: 초기 대기시간 설정 값 찾기
    timer_matches = re.findall(r'setTimeout\s*\([^,]+,\s*(\d+)', r1.text)
    initial_wait_ms = 0
    for match in timer_matches:
        time_ms = int(match)
        if 1000 <= time_ms <= 65000:  # 1초~65초
            initial_wait_ms = max(initial_wait_ms, time_ms)
    
    # 2단계: 가장 신뢰할 수 있는 방법으로 남은 시간 추출 (안정화)
    remaining_time = 0
    time_extraction_method = "none"
    
    print(f"[DEBUG] 대기시간 추출 시작 - 초기 설정: {initial_wait_ms}ms")
    
    # 2025년 실제 1fichier 구조 기반 카운트다운 감지 (실제 확인됨)
    js_countdown_patterns = [
        (r'var\s+ct\s*=\s*(\d+)', 'JavaScript ct 변수 (메인)'),  # 실제 사용되는 패턴
        (r'ct\s*=\s*(\d+)', '간소화된 ct 변수'),               # var 없이 사용될 수 있음
        (r'countdown\s*=\s*(\d+)', 'countdown 변수'),
        (r'timer\s*=\s*(\d+)', 'timer 변수'),
        # 추가: 실제 확인된 패턴들
        (r'let\s+ct\s*=\s*(\d+)', 'let ct 변수'),            # 모던 JavaScript
        (r'const\s+ct\s*=\s*(\d+)', 'const ct 변수'),
    ]
    
    for pattern, method_name in js_countdown_patterns:
        match = re.search(pattern, r1.text, re.IGNORECASE)
        if match:
            js_remaining = int(match.group(1))
            if 5 <= js_remaining <= 120:  # 합리적인 범위
                remaining_time = js_remaining
                time_extraction_method = method_name
                print(f"[DEBUG] {method_name}에서 대기시간 추출: {remaining_time}초")
                break
    
    # JavaScript에서 찾지 못한 경우에만 다른 방법 시도
    if remaining_time == 0:
        # HTML 텍스트 패턴 (두 번째 우선순위)
        html_patterns = [
            (r'(\d+)\s*seconds?\s*remaining', 'HTML seconds remaining'),
            (r'wait["\']?\s*:\s*(\d+)', 'HTML wait 속성'),
            (r'timeLeft["\']?\s*:\s*(\d+)', 'HTML timeLeft 속성'),
        ]
        
        for pattern, method_name in html_patterns:
            match = re.search(pattern, r1.text, re.IGNORECASE)
            if match:
                html_remaining = int(match.group(1))
                if 5 <= html_remaining <= 120:
                    remaining_time = html_remaining
                    time_extraction_method = method_name
                    print(f"[DEBUG] {method_name}에서 대기시간 추출: {remaining_time}초")
                    break
    
    # 위 방법들이 모두 실패한 경우에만 초기값 기반 계산
    if remaining_time == 0 and initial_wait_ms > 0:
        initial_wait_seconds = initial_wait_ms / 1000
        # 페이지 로딩 시간 추정 (1-3초)
        estimated_loading_time = 2
        remaining_time = max(5, initial_wait_seconds - estimated_loading_time)  # 최소 5초
        time_extraction_method = "초기값 기반 추정"
        print(f"[DEBUG] {time_extraction_method}: {remaining_time}초 (원래 {initial_wait_seconds}초 - {estimated_loading_time}초 로딩시간)")
    
    # 최종 검증 및 안정화
    if remaining_time > 0:
        # 합리적인 범위로 제한
        remaining_time = min(max(remaining_time, 5), 120)  # 5초~120초
        print(f"[LOG] 대기시간 확정: {remaining_time}초 (방법: {time_extraction_method})")
    
    # 5단계: 실제 대기 처리
    if remaining_time > 0:
        actual_wait = min(remaining_time, wait_time_limit)
        print(f"[LOG] 남은 대기 시간: {remaining_time:.1f}초 (실제 대기: {actual_wait:.1f}초)")
        
        # WebSocket으로 대기시간 전송
        try:
            from .download_core import send_websocket_message
            send_websocket_message("wait_countdown", {
                "remaining_time": int(remaining_time),
                "total_wait_time": int(initial_wait_seconds) if initial_wait_ms > 0 else int(remaining_time),
                "proxy_addr": proxy_addr,
                "url": url
            })
        except Exception as e:
            print(f"[LOG] 대기시간 WebSocket 전송 실패: {e}")
        
        # 안정화된 카운트다운으로 대기
        import time
        wait_duration = remaining_time if proxies is None else actual_wait
        total_wait_time = int(remaining_time)
        
        print(f"[LOG] 안정화된 카운트다운 시작: {wait_duration}초")
        
        # 안정화된 카운트다운 (정수로 고정)
        for i in range(int(wait_duration)):
            time.sleep(1)
            
            # 정지 상태 체크 (URL로 request 찾아서 체크)
            temp_db = None
            try:
                from .db import SessionLocal
                from .models import StatusEnum, DownloadRequest
                temp_db = SessionLocal()
                
                # URL로 다운로드 요청 찾기 (모든 상태)
                active_req = temp_db.query(DownloadRequest).filter(
                    DownloadRequest.url == url
                ).order_by(DownloadRequest.requested_at.desc()).first()
                
                if active_req and active_req.status == StatusEnum.stopped:
                    print(f"[LOG] 대기 중 정지됨: URL {url}")
                    temp_db.close()
                    return None  # 정지된 경우 파싱 중단
                    
            except Exception as e:
                print(f"[LOG] 정지 상태 체크 실패: {e}")
            finally:
                if temp_db:
                    temp_db.close()
            
            # 안정화된 카운트다운 계산 (정수만 사용)
            remaining_seconds = total_wait_time - i - 1
            if remaining_seconds >= 0:
                try:
                    send_websocket_message("wait_countdown", {
                        "remaining_time": remaining_seconds,
                        "total_wait_time": total_wait_time,
                        "proxy_addr": proxy_addr,
                        "url": url
                    })
                    print(f"[DEBUG] 카운트다운: {remaining_seconds}초 남음")
                except Exception as e:
                    print(f"[LOG] 실시간 카운트다운 WebSocket 전송 실패: {e}")
        
        # 남은 소수점 시간 대기
        remaining_fraction = wait_duration - int(wait_duration)
        if remaining_fraction > 0:
            time.sleep(remaining_fraction)
    else:
        print(f"[LOG] 대기 시간 없음 - 즉시 진행")
    
    # 2단계: POST 요청으로 다운로드 링크 획득 (2025년 1fichier 구조 기반)
    payload = {}
    
    try:
        # BeautifulSoup으로 정확한 폼 파싱 (정규식보다 안정적)
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r1.text, 'html.parser')
        
        # 실제 확인된 폼 ID로 찾기
        download_form = soup.find('form', {'id': 'f1'})
        if not download_form:
            # ID가 없다면 다른 방법으로 찾기
            download_form = soup.find('form')
        
        if download_form:
            print(f"[LOG] 다운로드 폼 발견: {download_form.get('id', '무명폼')}")
            
            # 폼 내 모든 input 요소 파싱
            inputs = download_form.find_all('input')
            for input_elem in inputs:
                name = input_elem.get('name')
                value = input_elem.get('value', '')
                input_type = input_elem.get('type', 'text')
                
                if name:
                    print(f"[DEBUG] Input: {name} ({input_type}) = '{value}'")
                    
                    # 패스워드 입력
                    if input_type == 'password' or name.lower() in ['pass', 'password']:
                        if password:
                            payload[name] = password
                            print(f"[LOG] 패스워드 설정: {name}")
                    # submit 버튼이나 hidden 필드
                    elif input_type in ['submit', 'hidden'] or name.lower() in ['submit', 'download']:
                        payload[name] = value if value else 'Download'
                    # 기타 필드들 (CSRF 토큰 등)
                    else:
                        if value:
                            payload[name] = value
            
            print(f"[LOG] 최종 POST 파라미터: {payload}")
            
        else:
            print(f"[LOG] 폼을 찾지 못함, 기본 파라미터 사용")
            payload = {'submit': 'Download'}
            if password:
                payload['pass'] = password
                
    except Exception as e:
        print(f"[DEBUG] 폼 파싱 실패, 최소한의 파라미터 사용: {e}")
        payload = {'submit': 'Download'}
        if password:
            payload['pass'] = password
    
    headers_post = headers.copy()
    headers_post['Referer'] = str(url)
    
    # 2단계: POST 요청 (쿠키 세팅을 위해 좀 더 구체적인 헤더 사용)
    headers_post['Content-Type'] = 'application/x-www-form-urlencoded'
    headers_post['Origin'] = 'https://1fichier.com'
    headers_post['Sec-Fetch-Dest'] = 'document'
    headers_post['Sec-Fetch-Mode'] = 'navigate'
    headers_post['Sec-Fetch-Site'] = 'same-origin'
    headers_post['Sec-Fetch-User'] = '?1'
    
    # 도커 환경에서 안정성을 위한 세션 쿠키 관리
    import time
    time.sleep(0.5)  # 1차 요청 후 잠시 대기
    r2 = scraper.post(url, data=payload, headers=headers_post, proxies=proxies, timeout=15)
    # print(f"[LOG] POST 응답: {r2.status_code}")
    
    if r2.status_code == 200:
        print(f"[DEBUG] POST 응답 크기: {len(r2.text)} 문자")
        
        # 1단계: 제한 상황 감지
        limit_detected = _detect_download_limits(r2.text, str(url))
        if limit_detected:
            limit_type, remaining_time = limit_detected
            
            # 카운트다운인 경우 대기 후 재시도
            if limit_type == "countdown" and isinstance(remaining_time, int):
                countdown_seconds = remaining_time
                proxy_info = f" (프록시: {proxy_addr})" if proxy_addr else " (로컬 연결)"
                print(f"[LOG] 카운트다운 감지{proxy_info}: {countdown_seconds}초 대기 후 재시도")
                
                # WebSocket으로 대기시간 전송
                try:
                    from .download_core import send_websocket_message
                    send_websocket_message("wait_countdown", {
                        "remaining_time": countdown_seconds,
                        "total_wait_time": countdown_seconds,
                        "proxy_addr": proxy_addr,
                        "url": url
                    })
                except Exception as e:
                    print(f"[LOG] 카운트다운 WebSocket 전송 실패: {e}")
                
                # 안전하게 몇 초 더 대기
                actual_wait = countdown_seconds + 2
                import time
                
                # 실시간 카운트다운으로 대기
                for i in range(actual_wait):
                    time.sleep(1)
                    
                    # 정지 상태 체크 (URL로 request 찾아서 체크)
                    temp_db = None
                    try:
                        from .db import SessionLocal
                        from .models import StatusEnum, DownloadRequest
                        temp_db = SessionLocal()
                        
                        # URL로 다운로드 요청 찾기 (모든 상태)
                        active_req = temp_db.query(DownloadRequest).filter(
                            DownloadRequest.url == url
                        ).order_by(DownloadRequest.requested_at.desc()).first()
                        
                        if active_req and active_req.status == StatusEnum.stopped:
                            print(f"[LOG] 카운트다운 대기 중 정지됨: URL {url}")
                            temp_db.close()
                            return None  # 정지된 경우 파싱 중단
                            
                    except Exception as e:
                        print(f"[LOG] 정지 상태 체크 실패: {e}")
                    finally:
                        if temp_db:
                            temp_db.close()
                    
                    remaining_seconds = actual_wait - i - 1
                    if remaining_seconds >= 0:
                        try:
                            send_websocket_message("wait_countdown", {
                                "remaining_time": remaining_seconds,
                                "total_wait_time": countdown_seconds,
                                "proxy_addr": proxy_addr,
                                "url": url
                            })
                        except Exception as e:
                            print(f"[LOG] 실시간 카운트다운 WebSocket 전송 실패: {e}")
                
                print(f"[LOG] 카운트다운 완료 - 재시도 중{proxy_info}")
                
                # 3단계: 재시도 (카운트다운 후 GET 요청으로 실제 다운로드 페이지 확인)
                r3 = scraper.get(url, headers=headers, proxies=proxies, timeout=15)
                
                if r3.status_code == 200:
                    print(f"[DEBUG] 재시도 POST 응답 크기: {len(r3.text)} 문자")
                    
                    # 재시도 응답에서 더 정교한 분석
                    print(f"[DEBUG] 재시도 응답 상세 분석 중...")
                    import re
                    
                    # dlw 버튼의 onclick이나 href 찾기
                    dlw_patterns = [
                        r'<[^>]*id=["\']dlw["\'][^>]*onclick=["\']([^"\']+)["\'][^>]*>',
                        r'<[^>]*id=["\']dlw["\'][^>]*href=["\']([^"\']+)["\'][^>]*>',
                        r'<[^>]*id=["\']dlw["\'][^>]*>(.*?)</[^>]*>',
                    ]
                    
                    for pattern in dlw_patterns:
                        dlw_matches = re.findall(pattern, r3.text, re.IGNORECASE | re.DOTALL)
                        if dlw_matches:
                            print(f"[DEBUG] dlw 패턴 발견: {dlw_matches}")
                            for match in dlw_matches:
                                if 'a-' in match and '.1fichier.com' in match:
                                    print(f"[LOG] dlw에서 Direct Link 발견{proxy_info}: {match}")
                                    return match, r3.text
                    
                    # JavaScript location.href 찾기
                    js_location_patterns = [
                        r"location\.href\s*=\s*['\"]([^'\"]*a-[^'\"]*)['\"]",
                        r"window\.location\s*=\s*['\"]([^'\"]*a-[^'\"]*)['\"]",
                        r"document\.location\s*=\s*['\"]([^'\"]*a-[^'\"]*)['\"]",
                    ]
                    
                    for pattern in js_location_patterns:
                        js_matches = re.findall(pattern, r3.text, re.IGNORECASE)
                        if js_matches:
                            print(f"[DEBUG] JavaScript location 패턴 발견: {js_matches}")
                            for match in js_matches:
                                if match.startswith('/'):
                                    match = f"https://1fichier.com{match}"
                                print(f"[LOG] JavaScript에서 Direct Link 발견{proxy_info}: {match}")
                                return match, r3.text
                    
                    # 폼 분석
                    forms = re.findall(r'<form[^>]*>(.*?)</form>', r3.text, re.DOTALL | re.IGNORECASE)
                    if forms:
                        print(f"[DEBUG] 재시도 응답에서 {len(forms)}개 폼 발견")
                        for i, form in enumerate(forms):
                            # 폼 내 action 찾기
                            action_match = re.search(r'action\s*=\s*[\'"]([^\'"]+)[\'"]', form, re.IGNORECASE)
                            if action_match:
                                action_url = action_match.group(1)
                                print(f"[DEBUG] 폼 {i+1} action: {action_url}")
                                if 'a-' in action_url and '.1fichier.com' in action_url:
                                    print(f"[DEBUG] 폼 {i+1}에서 a-패턴 action 발견: {action_url}")
                                    if action_url.startswith('/'):
                                        action_url = f"https://1fichier.com{action_url}"
                                    print(f"[LOG] 폼 action에서 Direct Link 발견{proxy_info}: {action_url}")
                                    return action_url, r3.text
                    
                    # 최종 시도: dlw 버튼 클릭 시뮬레이션으로 직접 다운로드
                    print(f"[DEBUG] dlw 버튼 클릭 시뮬레이션 - 직접 다운로드 시도...")
                    
                    # dlw 버튼과 연결된 폼 찾기
                    form_match = re.search(r'<form[^>]*id=["\']f1["\'][^>]*>(.*?)</form>', r3.text, re.DOTALL | re.IGNORECASE)
                    if form_match:
                        form_content = form_match.group(1)
                        print(f"[DEBUG] f1 폼 발견, 다운로드 클릭 시뮬레이션")
                        
                        # 폼 데이터 수집
                        form_data = {}
                        input_matches = re.findall(r'<input[^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\'][^>]*>', form_content, re.IGNORECASE)
                        for name, value in input_matches:
                            form_data[name] = value
                        
                        print(f"[DEBUG] 폼 데이터: {form_data}")
                        
                        # 다운로드 헤더 설정 (파일 다운로드용)
                        download_headers = headers_post.copy()
                        download_headers.update({
                            'Accept': '*/*',
                            'Accept-Encoding': 'identity',  # 압축 비활성화
                        })
                        
                        # 폼 submit - 리다이렉트 추적하지 않고 Location 헤더 확인
                        try:
                            r4 = scraper.post(url, data=form_data, headers=download_headers, proxies=proxies, timeout=30, allow_redirects=False)
                            print(f"[DEBUG] 폼 submit 응답: {r4.status_code}")
                            print(f"[DEBUG] Response Headers: {dict(r4.headers)}")
                            
                            # 리다이렉트인 경우 Location 헤더에서 다운로드 링크 추출
                            if r4.status_code in [302, 301, 303, 307, 308]:
                                location = r4.headers.get('Location')
                                if location:
                                    # 상대 URL을 절대 URL로 변환
                                    if location.startswith('/'):
                                        location = f"https://1fichier.com{location}"
                                    print(f"[LOG] 리다이렉트 다운로드 링크 발견{proxy_info}: {location}")
                                    return location, r4.text
                            elif r4.status_code == 200:
                                # 직접 다운로드인 경우
                                content_type = r4.headers.get('Content-Type', '').lower()
                                if not content_type.startswith('text/html'):
                                    print(f"[LOG] 직접 파일 다운로드 성공{proxy_info}! Content-Type: {content_type}")
                                    # 실제 응답을 직접 처리할 수 있도록 특별한 반환값
                                    return "DIRECT_FILE_RESPONSE", r4
                                else:
                                    print(f"[DEBUG] HTML 응답 받음 - 추가 분석 필요")
                                    # HTML 응답에서 다운로드 링크 다시 찾기
                                    final_link = fichier_parser.parse_download_link(r4.text, str(url))
                                    if final_link:
                                        print(f"[LOG] 최종 HTML에서 다운로드 링크 발견{proxy_info}: {final_link}")
                                        return final_link, r4.text
                                
                        except Exception as e:
                            print(f"[DEBUG] 폼 submit 실패: {e}")
                    
                    # 재시도 후 Direct Link 파싱
                    direct_link = fichier_parser.parse_download_link(r3.text, str(url))
                    if direct_link:
                        print(f"[LOG] 재시도 후 Direct Link 발견{proxy_info}: {direct_link}")
                        return direct_link, r3.text
                    else:
                        print(f"[LOG] 재시도 후에도 Direct Link를 찾을 수 없음{proxy_info}")
                        # 재시도 후에도 실패하면 파싱 실패로 명확히 처리 (재시도 방지)
                        raise Exception(f"다운로드 링크 파싱 실패 - {countdown_seconds}초 대기 후에도 링크를 찾을 수 없음")
                else:
                    print(f"[LOG] 재시도 POST 실패{proxy_info}: {r3.status_code}")
                    raise Exception(f"다운로드 링크 파싱 실패 - 카운트다운 후 서버 응답 실패 (HTTP {r3.status_code})")
            else:
                # 카운트다운이 아닌 다른 제한사항
                error_msg = f"1fichier 제한 감지: {limit_type}"
                if remaining_time:
                    error_msg += f" (남은 시간: {remaining_time})"
                print(f"[LOG] {error_msg}")
                raise Exception(error_msg)
        
        # 2단계: 새로운 파서 사용 (제한이 없는 경우)
        else:
            print(f"[DEBUG] 제한 없음 - 즉시 파싱 시도")
            direct_link = fichier_parser.parse_download_link(r2.text, str(url))
            if direct_link:
                print(f"[LOG] Direct Link 발견: {direct_link}")
                return direct_link, r2.text  # HTML도 함께 반환하여 파일명 추출용
            else:
                print(f"[LOG] Direct Link를 찾을 수 없음")
                # 파싱 실패를 명확히 표시하여 재시도 방지
                raise Exception("다운로드 링크 파싱 실패 - 1fichier 페이지에서 다운로드 링크를 찾을 수 없음")
    else:
        print(f"[LOG] POST 실패: {r2.status_code}")
    
    return None, None


def _detect_download_limits(html_content, original_url):
    """1fichier 다운로드 제한 상황 감지"""
    try:
        import re
        
        # HTML 내용 디버깅
        print(f"[DEBUG] HTML 길이: {len(html_content)} 글자")
        
        # HTML 전체 구조 분석을 위한 더 상세한 디버깅
        if len(html_content) > 500:
            # HTML 전체를 여러 구간으로 나누어 분석
            total_len = len(html_content)
            chunk_size = 1000
            
            print(f"[DEBUG] ===== HTML 전체 분석 (총 {total_len}자) =====")
            
            # 첫 번째 1000자 (안전한 출력)
            try:
                print(f"[DEBUG] HTML 첫 1000자:")
                safe_content = html_content[:chunk_size].encode('utf-8', 'ignore').decode('utf-8')
                print(safe_content)
            except:
                print("[DEBUG] HTML 첫 부분 출력 실패 (인코딩 문제)")
            
            # 중간 1000자  
            try:
                middle_start = total_len // 2 - chunk_size // 2
                middle_end = middle_start + chunk_size
                print(f"[DEBUG] HTML 중간 1000자 ({middle_start}-{middle_end}):")
                safe_content = html_content[middle_start:middle_end].encode('utf-8', 'ignore').decode('utf-8')
                print(safe_content)
            except:
                print("[DEBUG] HTML 중간 부분 출력 실패 (인코딩 문제)")
            
            # 마지막 1000자
            try:
                print(f"[DEBUG] HTML 마지막 1000자:")
                safe_content = html_content[-chunk_size:].encode('utf-8', 'ignore').decode('utf-8')
                print(safe_content)
            except:
                print("[DEBUG] HTML 마지막 부분 출력 실패 (인코딩 문제)")
            
            # 특별한 요소들 검사
            script_matches = re.findall(r'<script[^>]*>(.*?)</script>', html_content, re.IGNORECASE | re.DOTALL)
            if script_matches:
                print(f"[DEBUG] 발견된 script 태그 수: {len(script_matches)}")
                for i, script in enumerate(script_matches[:3]):  # 처음 3개 스크립트만
                    print(f"[DEBUG] Script {i+1}: {script[:500]}...")
            
            # form, input, button 등 중요 요소들 검사
            forms = re.findall(r'<form[^>]*>.*?</form>', html_content, re.IGNORECASE | re.DOTALL)
            buttons = re.findall(r'<(?:button|input)[^>]*(?:button|submit)[^>]*>', html_content, re.IGNORECASE)
            
            print(f"[DEBUG] 발견된 form 수: {len(forms)}")
            print(f"[DEBUG] 발견된 button/input 수: {len(buttons)}")
            
            if buttons:
                print(f"[DEBUG] 버튼들: {buttons}")
        
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
        
        # 1단계: JavaScript에서 카운트다운 시간 추출 (최우선)
        # 먼저 JavaScript 카운트다운 변수를 찾기 (dlw 버튼 유무와 관계없이)
        js_countdown_patterns = [
            r'var\s+ct\s*=\s*(\d+)\s*\*\s*(\d+)',  # var ct = 1*60 -> 곱셈 결과 계산
            r'var\s+ct\s*=\s*(\d+)',               # var ct = 60
            r'ct\s*=\s*(\d+)\s*\*\s*(\d+)',       # ct = 1*60 -> 곱셈 결과 계산
            r'ct\s*=\s*(\d+)',                     # ct = 60
            r'countdown\s*=\s*(\d+)',              # countdown = 45
            r'timer\s*=\s*(\d+)',                 # timer = 30
            r'waitTime\s*=\s*(\d+)',              # waitTime = 25
            r'delay\s*=\s*(\d+)',                 # delay = 15
            r'var\s+\w*[tT]ime\w*\s*=\s*(\d+)',   # var waitTime = 60, var countTime = 45
            r'setTimeout\s*\(\s*\w+\s*,\s*(\d+)\s*\*\s*1000\s*\)', # setTimeout(func, 60 * 1000)
            r'setInterval\s*\(\s*\w+\s*,\s*1000\s*\).*?(\d+)',     # setInterval과 함께 사용되는 숫자
        ]
        
        for pattern in js_countdown_patterns:
            js_match = re.search(pattern, html_content, re.IGNORECASE)
            if js_match:
                # 곱셈 패턴인 경우 계산
                if len(js_match.groups()) >= 2 and js_match.group(2):
                    countdown_seconds = int(js_match.group(1)) * int(js_match.group(2))
                    print(f"[LOG] JavaScript 곱셈 패턴 감지: {js_match.group(1)} * {js_match.group(2)} = {countdown_seconds}초")
                else:
                    countdown_seconds = int(js_match.group(1))
                    print(f"[LOG] JavaScript 단순 패턴 감지: {countdown_seconds}초")
                
                # 합리적인 범위 체크 (5초~300초)
                if 5 <= countdown_seconds <= 300:
                    print(f"[LOG] JavaScript 패턴에서 카운트다운 감지: {countdown_seconds}초 (패턴: {pattern})")
                    return ("countdown", countdown_seconds)
        
        # 2단계: dlw 버튼 확인 (JavaScript 시간이 없는 경우에만)
        if 'id="dlw"' in html_content and 'disabled' in html_content:
            print(f"[DEBUG] dlw 버튼이 disabled 상태로 발견됨 (JavaScript 시간 없음)")
        else:
            print(f"[DEBUG] dlw 버튼이나 disabled 속성을 찾을 수 없음")
        
        # JavaScript 또는 HTML에 특정 키워드가 있는지 확인
        countdown_keywords = ['countdown', 'timer', 'wait', 'delay', 'second', 'sec', '초']
        found_keywords = [kw for kw in countdown_keywords if kw in html_content.lower()]
        if found_keywords:
            print(f"[DEBUG] 카운트다운 관련 키워드 발견: {found_keywords}")
        else:
            print(f"[DEBUG] 카운트다운 관련 키워드를 찾을 수 없음")
        
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
        
        # 3단계: HTML에서 직접 텍스트 패턴 찾기 (더 넓은 범위)
        html_countdown_patterns = [
            r'(\d+)\s*seconds?',               # "60 seconds" 형태
            r'(\d+)\s*sec',                    # "60 sec" 형태  
            r'wait.*?(\d+)',                   # "wait 45" 형태
            r'countdown.*?(\d+)',              # "countdown 30" 형태
            r'(\d+)\s*(?:초|seconds?|sec)',     # 한국어/영어 초 표시
        ]
        
        for pattern in html_countdown_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                countdown_seconds = int(match.group(1))
                # 합리적인 시간 범위인지 확인 (5초~300초)
                if 5 <= countdown_seconds <= 300:
                    print(f"[LOG] HTML 패턴에서 카운트다운 감지: {countdown_seconds}초")
                    return ("countdown", countdown_seconds)
        
        # 4단계: 더 광범위한 텍스트 기반 카운트다운 감지
        # HTML 텍스트에서 시간 표시를 찾기
        text_time_patterns = [
            r'(\d+)\s*second',                    # "60 second" 
            r'(\d+)\s*sec',                       # "45 sec"
            r'(\d+)\s*\s*초',                     # "30 초" (한국어)
            r'Free\s+download\s+in\s+(\d+)',      # "Free download in 60"
            r'Download\s+in\s+(\d+)',             # "Download in 45"
            r'Please\s+wait\s+(\d+)',             # "Please wait 30"
            r'Wait\s+(\d+)',                      # "Wait 25"
            r'Countdown:\s*(\d+)',                # "Countdown: 20"
        ]
        
        for pattern in text_time_patterns:
            text_match = re.search(pattern, html_content, re.IGNORECASE)
            if text_match:
                countdown_seconds = int(text_match.group(1))
                # 합리적인 범위 체크 (5초~300초)
                if 5 <= countdown_seconds <= 300:
                    print(f"[LOG] HTML 텍스트에서 카운트다운 감지: {countdown_seconds}초 (패턴: {pattern})")
                    return ("countdown", countdown_seconds)
        
        # 5단계: 숫자 패턴 광범위 검색 (마지막 시도)
        # 모든 숫자를 찾아서 카운트다운 후보 검사
        all_numbers = re.findall(r'\b(\d{1,3})\b', html_content)
        reasonable_countdown_numbers = [int(n) for n in all_numbers if 10 <= int(n) <= 120]
        
        if reasonable_countdown_numbers:
            print(f"[DEBUG] HTML에서 발견된 카운트다운 후보 숫자들: {reasonable_countdown_numbers[:10]}")
            # 가장 흔한 숫자나 특정 범위의 숫자를 카운트다운으로 추정
            from collections import Counter
            counter = Counter(reasonable_countdown_numbers)
            most_common = counter.most_common(1)
            if most_common:
                candidate_countdown = most_common[0][0]
                print(f"[LOG] 추정 카운트다운 시간: {candidate_countdown}초 (HTML 내 빈도 기반)")
                return ("countdown", candidate_countdown)
        
        # 6단계: 다른 접근 - URL 패턴 분석
        # 1fichier URL에서 특별한 패턴이나 파라미터 확인
        if '1fichier.com' in original_url:
            print(f"[DEBUG] 1fichier URL 확인됨. URL 패턴 분석...")
            
            # URL에서 특별한 매개변수나 패턴 확인
            if '?download=' in original_url or '&download=' in original_url:
                print(f"[DEBUG] Direct download URL 패턴 감지")
                return (None, None)  # 제한 없음으로 처리
            
            # 일반적인 1fichier 파일 URL 패턴인 경우 기본 대기시간 적용
            if re.match(r'https?://1fichier\.com/\?\w+', original_url):
                print(f"[LOG] 표준 1fichier URL 패턴 - 기본 카운트다운 60초 적용")
                return ("countdown", 60)
        
        # 7단계: 프리미엄 페이지로 리다이렉트된 경우 (최종 체크)
        premium_indicators = [
            '/console/abo.pl' in html_content,
            'premium required' in html_content.lower(),
            'premium account' in html_content.lower(), 
            'upgrade to premium' in html_content.lower(),
            'subscription' in html_content.lower() and 'payment' in html_content.lower()
        ]
        
        # 매우 확실한 프리미엄 페이지 표시가 있는 경우에만
        if any(premium_indicators) and 'countdown' not in html_content.lower() and 'timer' not in html_content.lower():
            print(f"[DEBUG] 프리미엄 필요 감지됨 (카운트다운 관련 단어 없음)")
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
        
        # 최종 fallback: 1fichier 사이트인데 명확한 다운로드 링크가 없다면 기본 대기시간 적용
        if '1fichier.com' in original_url and 'download' not in html_content.lower():
            print(f"[LOG] 1fichier 사이트에서 다운로드 링크를 찾을 수 없음 - 기본 대기시간 60초 적용")
            return ("countdown", 60)
        
        print(f"[DEBUG] 어떤 제한도 감지되지 않음")
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
        error_str = str(e)
        print(f"[LOG] Direct Link 유효성 검사 실패: {e}")
        
        # DNS 오류인 경우 확실히 만료된 것으로 판단
        if any(dns_error in error_str for dns_error in [
            "NameResolutionError", "Failed to resolve", "Name or service not known", 
            "No address associated with hostname", "nodename nor servname provided",
            "dstorage.fr"  # 특별히 dstorage.fr DNS 오류 감지
        ]):
            print(f"[LOG] DNS 해상도 오류로 인한 링크 만료 확정: {error_str}")
            
        return True  # 기타 에러 시 만료로 간주