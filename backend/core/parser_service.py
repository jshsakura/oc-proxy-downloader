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


def get_or_parse_direct_link(req, proxies=None, use_proxy=True, force_reparse=False, proxy_addr=None):
    """다운로드 요청에서 직접 링크를 가져오거나 파싱하는 함수"""
    
    # proxy_addr이 있으면 proxies 생성
    if proxy_addr and use_proxy:
        proxies = {
            'http': f'http://{proxy_addr}',
            'https': f'http://{proxy_addr}'
        }
        # print(f"[LOG] 프록시 설정: {proxy_addr}")
    
    # 강제 재파싱이 요청되었거나 기존 링크가 없는 경우
    if force_reparse or not req.direct_link:
        print(f"[LOG] direct_link 새로 파싱 (force_reparse: {force_reparse}, proxy: {proxy_addr})")
        return parse_direct_link_simple(req.url, req.password, proxies=proxies, use_proxy=use_proxy)
    
    # 기존 링크가 있는 경우 만료 여부 확인
    if is_direct_link_expired(req.direct_link, use_proxy=use_proxy, proxy_addr=proxy_addr):
        print(f"[LOG] 기존 direct_link가 만료됨. 재파싱 시작: {req.direct_link} (proxy: {proxy_addr})")
        return parse_direct_link_simple(req.url, req.password, proxies=proxies, use_proxy=use_proxy)
    
    print(f"[LOG] 기존 direct_link 재사용: {req.direct_link}")
    return req.direct_link


def parse_direct_link_simple(url, password=None, proxies=None, use_proxy=True):
    """단순화된 1fichier Direct Link 파싱"""
    # print(f"[LOG] Direct Link 파싱 시작: {url}")
    
    scraper = cloudscraper.create_scraper()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    # 프록시가 제공된 경우 해당 프록시만 사용
    if proxies:
        # print(f"[LOG] 지정된 프록시로 파싱 시도: {proxies}")
        try:
            # 1단계: GET 요청으로 페이지 로드
            r1 = scraper.get(url, headers=headers, proxies=proxies, timeout=3)
            # print(f"[LOG] GET 응답: {r1.status_code}")
            
            if r1.status_code not in [200, 500]:
                print(f"[LOG] GET 실패: {r1.status_code}")
                return None
            
            # 대기 시간 확인
            import re
            timer_matches = re.findall(r'setTimeout\s*\([^,]+,\s*(\d+)', r1.text)
            wait_time = 0
            for match in timer_matches:
                time_ms = int(match)
                if 1000 <= time_ms <= 60000:  # 1초~60초
                    wait_time = max(wait_time, time_ms / 1000)
            
            if wait_time > 0:
                print(f"[LOG] 대기 시간: {wait_time}초")
                time.sleep(min(wait_time, 10))  # 최대 10초만 대기
            
            # 2단계: POST 요청으로 다운로드 링크 획득
            payload = {'submit': 'Download'}
            if password:
                payload['pass'] = password
            
            headers_post = headers.copy()
            headers_post['Referer'] = str(url)
            
            r2 = scraper.post(url, data=payload, headers=headers_post, proxies=proxies, timeout=3)
            # print(f"[LOG] POST 응답: {r2.status_code}")
            
            if r2.status_code == 200:
                # 새로운 파서 사용
                direct_link = fichier_parser.parse_download_link(r2.text, str(url))
                if direct_link:
                    print(f"[LOG] Direct Link 발견: {direct_link}")
                    return direct_link
                else:
                    print(f"[LOG] Direct Link를 찾을 수 없음")
            else:
                print(f"[LOG] POST 실패: {r2.status_code}")
                
        except (requests.exceptions.ConnectTimeout, 
                requests.exceptions.ReadTimeout, 
                requests.exceptions.Timeout) as e:
            print(f"[LOG] 타임아웃: {e}")
            raise e  # 프록시 순환 로직에서 처리하도록 raise
        except requests.exceptions.ProxyError as e:
            print(f"[LOG] 프록시 연결 오류: {e}")
            raise e  # 프록시 순환 로직에서 처리하도록 raise
        except Exception as e:
            print(f"[LOG] 파싱 예외: {e}")
            raise e
    
    print(f"[LOG] 프록시 파싱 실패")
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