# -*- coding: utf-8 -*-
"""
1fichier 간단한 파싱 로직
1. 파일명/용량 추출
2. 대기시간 파싱 (버튼 텍스트에서 정확히)
3. 대기 후 클릭 시뮬레이션
"""

import re
import time
import asyncio
import httpx
import cloudscraper
from bs4 import BeautifulSoup
from services.sse_manager import sse_manager


async def parse_1fichier_simple(url, password=None, proxies=None, proxy_addr=None, download_id=None):
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

            # 텔레그램 대기시간 알림 (5분 이상인 경우)
            if wait_seconds >= 300:  # 5분 이상
                wait_minutes = wait_seconds // 60
                try:
                    from services.notification_service import send_telegram_wait_notification
                    file_name = file_info.get('name', 'Unknown File') if file_info else 'Unknown File'
                    file_size = file_info.get('size') if file_info else None
                    send_telegram_wait_notification(file_name, wait_minutes, "ko", file_size)
                except Exception as telegram_error:
                    print(f"[WARNING] 텔레그램 알림 실패: {telegram_error}")

            # 4단계: 정확히 대기 (SSE로 카운트다운 전송)
            print(f"[LOG] {wait_seconds}초 대기 시작...")

            # SSE로 대기시간 카운트다운 전송
            if download_id:
                from core.db import SessionLocal
                from core.models import DownloadRequest, StatusEnum

                for remaining in range(wait_seconds, 0, -1):
                    # 다운로드 상태 확인 (정지되었는지 체크)
                    try:
                        with SessionLocal() as db:
                            req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
                            if req and req.status == StatusEnum.stopped:
                                print(f"[LOG] 대기 중 정지 감지, 카운트다운 중단")

                                # 정지 상태 SSE 전송
                                try:
                                    await sse_manager.broadcast_message("download_stopped", {
                                        "id": download_id,
                                        "status": "stopped",
                                        "message": "download_stopped"
                                    })
                                except Exception as sse_error:
                                    print(f"[WARNING] 정지 SSE 전송 실패: {sse_error}")

                                return None  # 정지된 경우 파싱 중단
                    except Exception as e:
                        print(f"[WARNING] 상태 확인 실패: {e}")

                    try:
                        await sse_manager.broadcast_message("wait_countdown", {
                            "id": download_id,
                            "remaining_time": remaining,
                            "wait_message": "parsing_wait"
                        })
                    except Exception as e:
                        print(f"[WARNING] SSE 전송 실패: {e}")

                    await asyncio.sleep(1)

                # 대기 완료 메시지
                try:
                    await sse_manager.broadcast_message("wait_countdown_complete", {
                        "id": download_id,
                        "message": "parsing_wait_complete"
                    })
                except Exception as e:
                    print(f"[WARNING] SSE 전송 실패: {e}")
            else:
                await asyncio.sleep(wait_seconds)

            print(f"[LOG] 대기 완료!")
        
        # 5단계: 다운로드 버튼 클릭 시뮬레이션 (POST 요청)
        download_link = None
        try:
            download_link = simulate_download_click(scraper, url, response.text, password, headers, proxies)
            print(f"[LOG] 다운로드 링크 획득 성공: {download_link}")
        except Exception as download_error:
            print(f"[ERROR] 다운로드 링크 추출 실패: {download_error}")
            # 파일 정보와 대기시간은 성공했으므로 계속 진행

        return {
            'download_link': download_link,
            'file_info': file_info,
            'wait_time': wait_seconds
        }
        
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
        import cloudscraper

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
    """버튼 텍스트에서 정확한 대기시간 추출"""
    try:
        # JavaScript var ct 변수에서 추출 (우선순위 높음)
        ct_patterns = [
            r'var\s+ct\s*=\s*(\d+)',
            r'ct\s*=\s*(\d+)',
            r'countdown\s*=\s*(\d+)',
        ]

        for pattern in ct_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE)
            if match:
                wait_time = int(match.group(1))
                # 합리적인 범위 체크 (5초~7200초)
                if 5 <= wait_time <= 7200:
                    print(f"[LOG] JavaScript ct 변수에서 대기시간 추출: {wait_time}초")
                    return wait_time

        # dlw 버튼에서 대기시간 추출 (백업)
        button_patterns = [
            # "Free download in ⏳ 888" 형태
            r'Free\s+download\s+in\s+[^\d]*(\d+)',
            # dlw 버튼 내부의 숫자
            r'id="dlw"[^>]*>.*?(\d+)',
            # disabled 버튼의 숫자
            r'disabled[^>]*>.*?(\d+)',
        ]

        for pattern in button_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE | re.DOTALL)
            if match:
                wait_time = int(match.group(1))
                # 합리적인 범위 체크 (5초~7200초)
                if 5 <= wait_time <= 7200:
                    print(f"[LOG] 버튼에서 대기시간 추출: {wait_time}초")
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
                              proxies=proxies, timeout=(30, 60), allow_redirects=False)
        
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
            download_patterns = [
                r'https://a-\d+\.1fichier\.com/[a-zA-Z0-9_\-/]+',
                r'https://cdn-\d+\.1fichier\.com/[a-zA-Z0-9_\-/]+',
            ]
            
            for pattern in download_patterns:
                matches = re.findall(pattern, response.text)
                if matches:
                    print(f"[LOG] HTML에서 다운로드 링크 발견: {matches[0]}")
                    return matches[0]
        
        raise Exception("다운로드 링크를 찾을 수 없음")
        
    except Exception as e:
        print(f"[ERROR] 다운로드 클릭 시뮬레이션 실패: {e}")
        raise e