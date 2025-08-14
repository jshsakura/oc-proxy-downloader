#!/usr/bin/env python3
import requests
import urllib3
import time
import re
import sys
import os

# backend 모듈 경로 추가
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from backend.core.parser_service import parse_direct_link_simple

# SSL 검증 비활성화
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def test_backend_parser():
    """백엔드 파서를 직접 테스트"""
    url = "https://1fichier.com/?2tt0mgt7whqdx5a988wj"
    
    print(f"[BACKEND TEST] 백엔드 파서로 테스트: {url}")
    
    try:
        # 백엔드 파서 호출 (로컬 연결, 프록시 없음)
        direct_link = parse_direct_link_simple(url, password=None, proxies=None, use_proxy=False, proxy_addr=None)
        
        if direct_link:
            print(f"[BACKEND TEST] 성공! Direct Link: {direct_link}")
            return direct_link
        else:
            print(f"[BACKEND TEST] 실패: Direct Link를 얻을 수 없음")
            return None
            
    except Exception as e:
        print(f"[BACKEND TEST] 예외 발생: {e}")
        return None

def test_1fichier_parsing():
    url = "https://1fichier.com/?2tt0mgt7whqdx5a988wj"
    
    # requests 세션 생성
    session = requests.Session()
    session.verify = False
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    print(f"[TEST] 1단계: GET 요청 - {url}")
    r1 = session.get(url, headers=headers, timeout=15)
    print(f"[TEST] GET 응답: {r1.status_code}")
    
    if r1.status_code not in [200, 500]:
        print(f"[TEST] GET 실패: {r1.status_code}")
        return
    
    print(f"[TEST] 2단계: POST 요청 준비")
    payload = {'submit': 'Download'}
    
    headers_post = headers.copy()
    headers_post['Referer'] = str(url)
    
    print(f"[TEST] POST 요청 실행")
    r2 = session.post(url, data=payload, headers=headers_post, timeout=15)
    print(f"[TEST] POST 응답: {r2.status_code}")
    
    if r2.status_code == 200:
        html_content = r2.text
        print(f"[TEST] HTML 길이: {len(html_content)} 글자")
        
        # HTML 샘플 출력
        if len(html_content) > 500:
            sample_start = html_content[:500]
            sample_middle = html_content[len(html_content)//2:len(html_content)//2+300] 
            print(f"[TEST] HTML 시작 부분:")
            print(sample_start)
            print(f"[TEST] HTML 중간 부분:")
            print(sample_middle)
        
        # 키워드 검사
        keywords = ['dlw', 'disabled', 'Free download', 'button', '1fichier', 'premium', 'countdown']
        for keyword in keywords:
            if keyword.lower() in html_content.lower():
                print(f"[TEST] '{keyword}' 발견됨")
            else:
                print(f"[TEST] '{keyword}' 없음")
        
        # dlw 버튼 특별 검사
        if 'id="dlw"' in html_content:
            print(f"[TEST] id='dlw' 발견됨!")
            dlw_match = re.search(r'<button[^>]*id="dlw"[^>]*>([^<]*)<', html_content, re.IGNORECASE | re.DOTALL)
            if dlw_match:
                button_text = dlw_match.group(1).strip()
                print(f"[TEST] dlw 버튼 텍스트: '{button_text}'")
            else:
                # 더 넓은 범위로 검색
                dlw_context = re.search(r'.{0,200}id="dlw".{0,200}', html_content, re.IGNORECASE | re.DOTALL)
                if dlw_context:
                    print(f"[TEST] dlw 주변 컨텍스트: {dlw_context.group()}")
        
        # JavaScript 카운트다운 변수 검사 (새로운 방법)
        js_countdown_match = re.search(r'var\s+ct\s*=\s*(\d+)', html_content)
        if js_countdown_match:
            countdown_seconds = int(js_countdown_match.group(1))
            print(f"[TEST] JavaScript 카운트다운 감지: var ct = {countdown_seconds}")
        else:
            print(f"[TEST] JavaScript 카운트다운 변수(var ct)를 찾을 수 없음")
        
        # 기존 숫자 패턴 검사
        number_patterns = [
            r'Free download in.*?(\d+)',
            r'download in.*?(\d+)',
            r'⏳\s*(\d+)',
            r'disabled.*?(\d+)',
        ]
        
        for pattern in number_patterns:
            matches = re.findall(pattern, html_content, re.IGNORECASE)
            if matches:
                print(f"[TEST] 패턴 '{pattern}' 매칭: {matches}")
        
    else:
        print(f"[TEST] POST 실패: {r2.status_code}")

if __name__ == "__main__":
    print("=" * 50)
    print("백엔드 파서 테스트")
    print("=" * 50)
    test_backend_parser()
    
    print("\n" + "=" * 50)
    print("직접 파싱 테스트")  
    print("=" * 50)
    test_1fichier_parsing()