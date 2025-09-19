# -*- coding: utf-8 -*-
"""
1fichier 간단한 파싱 로직
1. 파일명/용량 추출
2. 대기시간 파싱 (버튼 텍스트에서 정확히)
3. 대기 후 클릭 시뮬레이션
"""

import re
import time
import httpx
import cloudscraper
import asyncio
import datetime
from bs4 import BeautifulSoup
from services.sse_manager import sse_manager
from core.db import SessionLocal
from core.models import DownloadRequest, StatusEnum


def parse_1fichier_simple_sync(url, password=None, proxies=None, proxy_addr=None, download_id=None, sse_callback=None):
    """
    1fichier 단순 파싱 로직
    1. 파일정보 추출
    2. 대기시간 추출
    3. 대기 후 다운로드 링크 획득
    """
    
    # CloudScraper 설정
    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
    )
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }
    
    try:
        # 1단계: 페이지 로드
        print(f"[LOG] 1fichier 페이지 로드: {url}")
        response = scraper.get(url, headers=headers, proxies=proxies, timeout=(10, 30))
        
        if response.status_code != 200:
            raise Exception(f"페이지 로드 실패: HTTP {response.status_code}")
        
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

            # 4단계: 정확히 대기 (SSE로 카운트다운 전송)
            print(f"[LOG] {wait_seconds}초 대기 시작...")

            # 대기 상태로 변경
            if sse_callback:
                try:
                    sse_callback("status_update", {
                        "id": download_id,
                        "status": "waiting",
                        "progress": 0,
                        "message": f"1fichier 대기 중... {wait_seconds}초"
                    })
                except Exception as sse_error:
                    print(f"[WARNING] SSE 대기 상태 전송 실패: {sse_error}")

            # SSE로 대기시간 카운트다운 전송
            if download_id:

                for remaining in range(wait_seconds, 0, -1):
                    # 다운로드 상태 확인 (정지되었는지 체크)
                    try:
                        with SessionLocal() as db:
                            req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
                            if req and req.status == StatusEnum.stopped:
                                print(f"[LOG] 대기 중 정지 감지, 카운트다운 중단")

                                # 정지 상태 확인
                                print(f"[LOG] 다운로드 중지 확인: download_id={download_id}")

                                return None  # 정지된 경우 파싱 중단
                    except Exception as e:
                        print(f"[WARNING] 상태 확인 실패: {e}")

                    # SSE 콜백으로 대기시간 전송
                    if sse_callback and remaining % 5 == 0:  # 5초마다만 전송
                        try:
                            sse_callback("waiting", {
                                "id": download_id,
                                "remaining": remaining,
                                "total": wait_seconds,
                                "message": f"1fichier 대기 중... {remaining}초 남음"
                            })
                        except Exception as sse_error:
                            print(f"[WARNING] SSE 대기시간 전송 실패: {sse_error}")

                    print(f"[DEBUG] 대기 중: {remaining}초 남음")
                    time.sleep(1)

                # 대기 완료
                print(f"[LOG] 대기 완료: download_id={download_id}")
            else:
                time.sleep(wait_seconds)

            print(f"[LOG] 대기 완료!")
        
        # 5단계: 다운로드 버튼 클릭 시뮬레이션 (POST 요청)
        download_link = None
        try:
            download_link = simulate_download_click(scraper, url, response.text, password, headers, proxies)
            print(f"[LOG] 다운로드 링크 획득 성공: {download_link}")
        except Exception as download_error:
            print(f"[ERROR] 다운로드 링크 추출 실패: {download_error}")
            # 프록시/네트워크 관련 에러나 일시적 오류면 재시도 가능
            retry_keywords = ['proxy', 'timeout', 'connection', 'read timed out', 'network', 'http', 'ssl', 'certificate']
            if any(keyword in str(download_error).lower() for keyword in retry_keywords):
                raise download_error  # 재시도 가능한 오류
            else:
                # 명확한 파싱 실패만 재시도 불가로 처리
                raise Exception(f"파싱 실패 (재시도 불가): {download_error}")

        # 다운로드 링크가 없으면 실패
        if not download_link:
            raise Exception("다운로드 링크를 찾을 수 없음")

        result = {
            'download_link': download_link,
            'file_info': file_info,
            'wait_time': wait_seconds
        }
        print(f"[DEBUG] 파싱 결과 반환: download_link={download_link is not None}, file_info={file_info is not None}, wait_time={wait_seconds}")
        return result
        
    except Exception as e:
        print(f"[ERROR] 1fichier 파싱 실패: {e}")
        raise e


def extract_file_info_simple(html_content):
    """파일 정보 추출 (이름, 크기) - 1fichier premium table 구조 기준"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        file_info = {}

        # 1. premium table에서 파일명과 크기 추출
        premium_table = soup.find('table', class_='premium')
        if premium_table:
            # 파일명: <span style="font-weight:bold">파일명</span>
            filename_span = premium_table.find('span', style=lambda x: x and 'font-weight:bold' in x)
            if filename_span:
                filename = filename_span.get_text(strip=True)
                if filename and not any(x in filename.lower() for x in ['1fichier', 'cloud storage', 'error']):
                    file_info['name'] = filename
                    print(f"[DEBUG] premium table에서 파일명 추출: {filename}")

            # 파일크기: <span style="font-size:0.9em;font-style:italic">크기</span>
            size_span = premium_table.find('span', style=lambda x: x and 'font-size:0.9em' in x and 'font-style:italic' in x)
            if size_span:
                size = size_span.get_text(strip=True)
                if size:
                    file_info['size'] = size
                    print(f"[DEBUG] premium table에서 파일크기 추출: {size}")

        # 2. premium table이 없으면 기존 패턴 사용 (백업)
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
                    if filename and not any(x in filename.lower() for x in ['1fichier', 'cloud storage', 'error']):
                        file_info['name'] = filename
                        print(f"[DEBUG] 정규식으로 파일명 추출: {filename}")
                        break

        if not file_info.get('size'):
            size_patterns = [
                r'File size[^:]*:\s*([^\n\r<]+)',
                r'Taille[^:]*:\s*([^\n\r<]+)',
                r'Size[^:]*:\s*([^\n\r<]+)',
                r'(\d+(?:\.\d+)?\s*[KMGT]?B)',
            ]

            for pattern in size_patterns:
                match = re.search(pattern, html_content, re.IGNORECASE)
                if match:
                    file_info['size'] = match.group(1).strip()
                    print(f"[DEBUG] 정규식으로 파일크기 추출: {file_info['size']}")
                    break

        return file_info if file_info else None

    except Exception as e:
        print(f"[ERROR] 파일 정보 추출 실패: {e}")
        return None


def preparse_1fichier_standalone(url):
    """1fichier URL 사전파싱 - cloudscraper 사용, 단독 실행"""
    try:

        print(f"[LOG] 사전파싱 시작: {url}")

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

        # JavaScript countdown 변수 (가장 정확함)
        ct_patterns = [
            r'var\s+ct\s*=\s*(\d+)',
            r'ct\s*=\s*(\d+)',
        ]

        for pattern in ct_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                wait_time = int(match.group(1))
                # 1초~24시간(86400초) 범위면 그대로 사용
                if 1 <= wait_time <= 86400:
                    print(f"[LOG] JavaScript ct 변수에서 대기시간 추출: {wait_time}초 ({wait_time//3600}시간 {(wait_time%3600)//60}분 {wait_time%60}초)")
                    return wait_time

        # 버튼 텍스트에서 숫자 추출
        button_patterns = [
            r'Free\s+download\s+in\s+.*?(\d+)',
            r'Please\s+wait\s+(\d+)',
            r'Download\s+in\s+(\d+)',
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


def simulate_download_click(scraper, url, html_content, password, headers, proxies):
    """다운로드 버튼 클릭 시뮬레이션"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 폼 찾기 (주로 id="f1")
        form = soup.find('form', {'id': 'f1'}) or soup.find('form')

        if not form:
            raise Exception("다운로드 폼을 찾을 수 없음")
        
        # 폼 데이터 수집
        form_data = {}

        # 모든 input 필드 수집
        for input_elem in form.find_all('input'):
            name = input_elem.get('name')
            value = input_elem.get('value', '')
            input_type = input_elem.get('type', 'text')

            if name:
                if input_type == 'password' and password:
                    form_data[name] = password
                elif input_type in ['submit', 'hidden'] or value:
                    form_data[name] = value
        
        # submit 버튼이 없으면 기본값 추가
        if not any('submit' in key.lower() for key in form_data.keys()):
            form_data['submit'] = 'Download'

        print(f"[LOG] 폼 데이터: {form_data}")

        # POST 요청으로 다운로드 링크 획득
        post_headers = headers.copy()
        post_headers.update({
            'Content-Type': 'application/x-www-form-urlencoded',
            'Referer': url,
            'Origin': 'https://1fichier.com'
        })

        response = scraper.post(url, data=form_data, headers=post_headers,
                              proxies=proxies, timeout=(10, 30), allow_redirects=False)

        # 리다이렉트 처리
        if response.status_code in [301, 302, 303, 307, 308]:
            location = response.headers.get('Location')
            if location and location.startswith('/'):
                location = f"https://1fichier.com{location}"

            if location and 'a-' in location:
                print(f"[LOG] 다운로드 링크 획득: {location}")
                return location

        # HTML 응답에서 다운로드 링크 찾기
        if response.status_code == 200:
            print(f"[DEBUG] POST 응답 내용 (처음 1000자):")
            print(response.text[:1000])
            print(f"[DEBUG] POST 응답 내용 끝")

            download_patterns = [
                r'https://a-\d+\.1fichier\.com/[a-zA-Z0-9_\-/]+',
                r'https://cdn-\d+\.1fichier\.com/[a-zA-Z0-9_\-/]+',
            ]

            for pattern in download_patterns:
                matches = re.findall(pattern, response.text)
                if matches:
                    print(f"[LOG] HTML에서 다운로드 링크 발견: {matches[0]}")
                    return matches[0]

            print(f"[DEBUG] 다운로드 링크 패턴 매칭 실패")

            # 응답에 실제 오류 메시지가 있는지 확인 (limit는 정상 상황이므로 제외)
            error_keywords = ['error', 'expired', 'invalid', 'not found']
            for keyword in error_keywords:
                if keyword.lower() in response.text.lower():
                    print(f"[DEBUG] 응답에서 오류 키워드 발견: {keyword}")

            # limit는 대기 후 정상 다운로드 가능한 상황이므로 별도 처리
            limit_keywords = ['limite', 'limit']
            for keyword in limit_keywords:
                if keyword.lower() in response.text.lower():
                    print(f"[DEBUG] 응답에서 제한 키워드 발견 (정상): {keyword} - 대기시간 후 다운로드 가능")

            # JavaScript 리다이렉트나 다른 패턴 확인
            js_patterns = [
                r'location\.href\s*=\s*["\']([^"\']+)["\']',
                r'window\.location\s*=\s*["\']([^"\']+)["\']',
                r'document\.location\s*=\s*["\']([^"\']+)["\']'
            ]

            for js_pattern in js_patterns:
                js_matches = re.findall(js_pattern, response.text, re.IGNORECASE)
                if js_matches:
                    print(f"[DEBUG] JavaScript 리다이렉트 패턴 발견: {js_matches[0]}")

        raise Exception("다운로드 링크를 찾을 수 없음")
        
    except Exception as e:
        print(f"[ERROR] 다운로드 클릭 시뮬레이션 실패: {e}")
        raise e