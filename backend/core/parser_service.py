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
                        
                        if download_req:
                            updated = False
                            
                            # 파일명과 크기가 모두 없는 경우에만 업데이트 (덮어쓰기 방지)
                            has_filename = download_req.file_name and download_req.file_name.strip() != ''
                            has_filesize = download_req.file_size and download_req.file_size.strip() != ''
                            
                            # 둘 다 없는 경우에만 새로 설정
                            if not has_filename and not has_filesize and early_file_info.get('name'):
                                download_req.file_name = early_file_info['name']
                                updated = True
                                print(f"[LOG] ★ 파일명 최초 설정: '{early_file_info['name']}'")
                                
                                if early_file_info.get('size'):
                                    download_req.file_size = early_file_info['size']
                                    updated = True
                                    print(f"[LOG] ★ 파일크기 최초 설정: '{early_file_info['size']}'")
                            elif has_filename or has_filesize:
                                print(f"[LOG] ★ 파일 정보 이미 존재 - 덮어쓰기 방지 (이름: {has_filename}, 크기: {has_filesize})")
                            
                            if updated:
                                temp_db.commit()
                                
                                # WebSocket으로 파일명과 크기 업데이트 전송
                                try:
                                    from core.shared import status_queue
                                    import json
                                    message = json.dumps({
                                        "type": "filename_update",
                                        "data": {
                                            "id": download_req.id,
                                            "file_name": download_req.file_name,
                                            "file_size": download_req.file_size,
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
        wait_time_limit = 86400 if use_proxy else 86400  # 24시간 (최대 대기시간)
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
    """간단한 1fichier 파싱 로직 - 정확한 대기시간만 기다리고 클릭"""
    import re
    from bs4 import BeautifulSoup
    import time
    
    try:
        # 1단계: 페이지 로드
        print(f"[LOG] 1fichier 페이지 로드")
        response = scraper.get(url, headers=headers, proxies=proxies, timeout=30)
        
        if response.status_code != 200:
            print(f"[LOG] 페이지 로드 실패: HTTP {response.status_code}")
            return None, None
        
        # 2단계: 버튼에서 정확한 대기시간 추출
        wait_seconds = None
        button_patterns = [
            r'Free\s+download\s+in\s+[^\d]*(\d+)\s*minutes?',  # Free download in ⏳ 16 minutes
            r'Free\s+download\s+in\s+[^\d]*(\d+)',             # Free download in ⏳ 888 (초)
            r'id="dlw"[^>]*>.*?(\d+)',                          # dlw 버튼 내부 숫자
            r'disabled[^>]*>.*?(\d+)',                          # disabled 버튼 숫자
        ]
        
        for i, pattern in enumerate(button_patterns):
            match = re.search(pattern, response.text, re.IGNORECASE | re.DOTALL)
            if match:
                wait_value = int(match.group(1))
                # 첫 번째 패턴은 분 단위
                if i == 0:  # minutes 패턴
                    wait_seconds = wait_value * 60
                    print(f"[LOG] 버튼에서 분 단위 대기시간 추출: {wait_value}분 ({wait_seconds}초)")
                else:  # 초 단위
                    wait_seconds = wait_value
                    print(f"[LOG] 버튼에서 초 단위 대기시간 추출: {wait_seconds}초")
                
                if 5 <= wait_seconds <= 14400:  # 5초~4시간 범위
                    break
                else:
                    wait_seconds = None  # 범위 밖이면 무시
        
        # 3단계: 대기시간이 있으면 정확히 대기
        if wait_seconds:
            print(f"[LOG] {wait_seconds}초 정확히 대기 시작...")
            
            # 최적화된 카운트다운 (웹소켓 부하 최소화)
            for i in range(wait_seconds):
                time.sleep(1)
                remaining = wait_seconds - i - 1
                
                # 웹소켓 메시지 전송 최적화: 중요한 시점에만 전송
                should_send_update = (
                    remaining == 0 or  # 완료시
                    remaining <= 10 or  # 마지막 10초
                    remaining % 30 == 0 or  # 30초마다
                    (remaining > 300 and remaining % 60 == 0) or  # 5분 이상이면 1분마다
                    (remaining > 60 and remaining % 10 == 0)  # 1분 이상이면 10초마다
                )
                
                if should_send_update:
                    # 웹소켓으로 카운트다운 전송
                    try:
                        from .download_core import send_websocket_message
                        send_websocket_message("wait_countdown", {
                            "remaining_time": remaining,
                            "total_wait_time": wait_seconds,
                            "proxy_addr": proxy_addr,
                            "url": url
                        })
                    except Exception as e:
                        print(f"[LOG] 카운트다운 WebSocket 전송 실패: {e}")
                    
                    # 로그는 10초마다만 출력 (너무 많은 로그 방지)
                    if remaining % 10 == 0:
                        print(f"[LOG] 남은 시간: {remaining}초")
            
            print(f"[LOG] 대기 완료! 다운로드 시작")
        
        # 4단계: 폼 데이터 수집 및 POST 요청
        soup = BeautifulSoup(response.text, 'html.parser')
        form = soup.find('form', {'id': 'f1'}) or soup.find('form')
        
        if not form:
            print(f"[LOG] 다운로드 폼을 찾을 수 없음")
            return None, None
        
        # 폼 데이터 수집
        form_data = {}
        for input_elem in form.find_all('input'):
            name = input_elem.get('name')
            value = input_elem.get('value', '')
            input_type = input_elem.get('type', 'text')
            
            if name:
                if input_type == 'password' and password:
                    form_data[name] = password
                elif input_type in ['submit', 'hidden'] or value:
                    form_data[name] = value
        
        # submit이 없으면 추가
        if not any('submit' in key.lower() for key in form_data.keys()):
            form_data['submit'] = 'Download'
        
        print(f"[LOG] POST 요청 시작...")
        
        # POST 헤더 설정
        post_headers = headers.copy()
        post_headers.update({
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': url,
            'Origin': 'https://1fichier.com'
        })
        
        # POST 요청
        post_response = scraper.post(url, data=form_data, headers=post_headers, 
                                   proxies=proxies, timeout=30, allow_redirects=False)
        
        # 5단계: 다운로드 링크 추출
        download_link = None
        
        # 리다이렉트인 경우
        if post_response.status_code in [301, 302, 303, 307, 308]:
            location = post_response.headers.get('Location')
            if location:
                if location.startswith('/'):
                    location = f"https://1fichier.com{location}"
                
                if 'a-' in location and '1fichier.com' in location:
                    download_link = location
                    print(f"[LOG] 리다이렉트에서 다운로드 링크: {download_link}")
        
        # HTML 응답인 경우
        elif post_response.status_code == 200:
            download_patterns = [
                r'https://a-\d+\.1fichier\.com/[a-zA-Z0-9_\-/]+',
                r'https://cdn-\d+\.1fichier\.com/[a-zA-Z0-9_\-/]+',
            ]
            
            for pattern in download_patterns:
                matches = re.findall(pattern, post_response.text)
                if matches:
                    download_link = matches[0]
                    print(f"[LOG] HTML에서 다운로드 링크: {download_link}")
                    break
        
        if download_link:
            return download_link, post_response.text
        else:
            print(f"[LOG] 다운로드 링크를 찾을 수 없음")
            return None, None
    
    except Exception as e:
        print(f"[LOG] 파싱 실패: {e}")
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
            # 2025년 1fichier 최신 패턴들 추가
            r'function\s+ctt\s*\(\s*\)\s*\{.*?ct\s*=\s*(\d+)',     # function ctt() { ct = 60; }
            r'var\s+ct\s*=\s*(\d+)',                                # var ct = 60
            r'ct\s*=\s*(\d+)',                                      # ct = 60
            r'let\s+ct\s*=\s*(\d+)',                               # let ct = 60
            r'const\s+ct\s*=\s*(\d+)',                             # const ct = 60
            r'ctt\s*\(\s*\).*?(\d+)',                              # ctt() function reference with number
            r'Free download.*?(\d+).*?second',                      # Free download ... 60 ... seconds
            r'wait.*?(\d+).*?second',                              # wait 60 seconds
            r'(\d+)\s*second.*?download',                          # 60 seconds ... download
            r'var\s+ct\s*=\s*(\d+)\s*\*\s*(\d+)',                 # var ct = 1*60 -> 곱셈 결과 계산
            r'ct\s*=\s*(\d+)\s*\*\s*(\d+)',                       # ct = 1*60 -> 곱셈 결과 계산
            r'countdown\s*=\s*(\d+)',                              # countdown = 45
            r'timer\s*=\s*(\d+)',                                 # timer = 30
            r'waitTime\s*=\s*(\d+)',                              # waitTime = 25
            r'delay\s*=\s*(\d+)',                                 # delay = 15
            r'var\s+\w*[tT]ime\w*\s*=\s*(\d+)',                   # var waitTime = 60, var countTime = 45
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
                
                # 합리적인 범위 체크 (5초~3600초 = 1시간까지)
                if 5 <= countdown_seconds <= 7200:
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
            # 실제 1fichier dlw 버튼 패턴 (최우선) - 제공된 HTML 기준
            r'Free\s+download\s+in\s+⏳\s+(\d+)',                        # Free download in ⏳ 888 (실제 패턴)
            r'Free\s+download\s+in\s+[^\d]*(\d+)',                       # Free download in [아무거나] 888
            r'>Free\s+download\s+in\s+.*?(\d+)</button>',                # 버튼 태그 내부의 패턴
            r'id=[\'"]dlw[\'"][^>]*>.*?Free\s+download\s+in\s+.*?(\d+)', # dlw 버튼의 정확한 패턴
            
            # 기존 패턴들 (백업용)
            r'Free\s+download\s+is\s+available\s+in\s+(\d+)\s+seconds?', # Free download is available in 60 seconds
            r'Please\s+wait\s+(\d+)\s+seconds?',                         # Please wait 60 seconds
            r'Download\s+will\s+be\s+available\s+in\s+(\d+)\s+seconds?', # Download will be available in 60 seconds
            r'Wait\s+(\d+)\s+seconds?',                                   # Wait 60 seconds
            r'Attendez\s+(\d+)\s+secondes?',                             # French: Attendez 60 secondes
            r'Téléchargement.*?(\d+)\s+secondes?',                       # French: Téléchargement dans 60 secondes
            r'disabled[^>]*>.*?(\d+).*?second',                          # disabled button with seconds
            r'id=[\'"]dlw[\'"][^>]*>.*?(\d+)',                          # dlw button with number
            r'button[^>]*disabled[^>]*>.*?(\d+)',                        # disabled button with number
            r'(\d+)\s*seconds?',                                         # "60 seconds" 형태
            r'(\d+)\s*sec',                                              # "60 sec" 형태  
            r'wait.*?(\d+)',                                             # "wait 45" 형태
            r'countdown.*?(\d+)',                                        # "countdown 30" 형태
            r'(\d+)\s*(?:초|seconds?|sec)',                              # 한국어/영어 초 표시
        ]
        
        for pattern in html_countdown_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                countdown_seconds = int(match.group(1))
                # 합리적인 시간 범위인지 확인 (5초~7200초 = 2시간까지)
                if 5 <= countdown_seconds <= 7200:
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
                # 합리적인 범위 체크 (5초~3600초 = 1시간까지)
                if 5 <= countdown_seconds <= 7200:
                    print(f"[LOG] HTML 텍스트에서 카운트다운 감지: {countdown_seconds}초 (패턴: {pattern})")
                    return ("countdown", countdown_seconds)
        
        # 5단계: 숫자 패턴 광범위 검색 (마지막 시도)
        # 모든 숫자를 찾아서 카운트다운 후보 검사 (최대 4자리까지 - 7200초 지원)
        all_numbers = re.findall(r'\b(\d{1,4})\b', html_content)
        reasonable_countdown_numbers = [int(n) for n in all_numbers if 10 <= int(n) <= 7200]
        
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
                # 파일이 존재하는지 확인
                if any(indicator in html_content.lower() for indicator in [
                    'file not found', 'fichier introuvable', '파일을 찾을 수 없', 
                    'does not exist', 'n\'existe pas', 'error 404'
                ]):
                    print(f"[LOG] 파일이 존재하지 않거나 삭제됨")
                    return ("not_found", "파일이 존재하지 않음")
                
                # dlw 버튼이 있으면 카운트다운 적용
                if 'id="dlw"' in html_content or 'dlw' in html_content:
                    print(f"[LOG] 표준 1fichier URL 패턴 + dlw 버튼 존재 - 기본 카운트다운 60초 적용")
                    return ("countdown", 60)
                else:
                    print(f"[LOG] 1fichier URL이지만 dlw 버튼 없음 - 추가 분석 필요")
                    return (None, None)
        
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
        # HEAD 요청으로 링크 유효성 확인 (타임아웃 늘림)
        response = requests.head(direct_link, headers=headers, timeout=(5, 10), allow_redirects=True, proxies=proxies)
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