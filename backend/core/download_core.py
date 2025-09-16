"""
핵심 다운로드 로직 모듈
- 1fichier 파일 다운로드
- 프록시 순환 다운로드
- 파일 관리
"""

import os
import re
import time
import threading
import httpx
import json
import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from urllib.parse import urlparse, unquote
import asyncio

from .db import get_db, SessionLocal
from .models import DownloadRequest, StatusEnum
from .config import get_download_path, get_config
from .proxy_manager import get_unused_proxies, mark_proxy_used, get_working_proxy_batch, test_proxy_batch
from .parser_service import get_or_parse_direct_link, parse_direct_link_with_file_info, is_direct_link_expired, parse_filename_only_with_proxy, parse_direct_link_simple
from .local_transfer import download_local
from .proxy_transfer import download_with_proxy, download_with_proxy_cycling
from services.download_manager import download_manager
from .i18n import get_message
from utils.sse import send_sse_message
from services.sse_manager import sse_manager

def safe_status_queue_put(message):
    """임시 대체 함수 - 로그만 출력"""
    print(f"[LOG] Status message: {message}")


def format_file_size(bytes_size):
    """파일 크기를 적절한 단위로 포맷팅"""
    if bytes_size == 0:
        return "0 B"
    
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    unit_index = 0
    size = float(bytes_size)
    
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    
    # 소수점 2자리까지 표시, 불필요한 0 제거
    if unit_index == 0:  # Bytes
        return f"{int(size)} {units[unit_index]}"
    else:
        return f"{size:.2f} {units[unit_index]}".rstrip('0').rstrip('.')


def get_unique_filepath(path: Path) -> Path:
    """
    파일 경로가 존재할 경우, 괄호 안에 숫자를 붙여 고유한 경로를 생성합니다.
    (예: 'file.txt' -> 'file (1).txt')
    """
    if not path.exists():
        return path

    counter = 1
    original_stem = path.stem
    original_suffix = path.suffix
    directory = path.parent

    while True:
        new_stem = f"{original_stem} ({counter})"
        new_path = directory / (new_stem + original_suffix)
        if not new_path.exists():
            return new_path
        counter += 1






def get_translations(lang: str = "ko") -> dict:
    """번역 데이터 가져오기"""
    try:
        import os
        locale_file = os.path.join(os.path.dirname(__file__), "..", "locales", f"{lang}.json")
        if os.path.exists(locale_file):
            with open(locale_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception:
        return {}


def send_telegram_wait_notification(file_name: str, wait_minutes: int, lang: str = "ko", file_size: str = None):
    """대기시간 텔레그램 알림 전송 (5분 이상 대기시간)"""
    try:
        config = get_config()
        
        bot_token = config.get("telegram_bot_token", "").strip()
        chat_id = config.get("telegram_chat_id", "").strip()
        notify_wait = config.get("telegram_notify_wait", True)  # 대기시간 알림 설정
        
        # 설정이 없거나 대기시간 알림이 비활성화된 경우
        if not bot_token or not chat_id or not notify_wait:
            return
        
        # 번역 가져오기
        translations = get_translations(lang)
        
        # HTML 형식으로 예쁜 메시지 작성
        if lang == "ko":
            # 한국어일 때만 KST로 표시
            current_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            # 영어 등 다른 언어는 UTC로 표시
            current_time = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        wait_text = translations.get("telegram_wait_detected", "Wait Time Detected")
        filename_text = translations.get("telegram_filename", "Filename")
        wait_time_text = translations.get("telegram_wait_time", "Wait Time")
        filesize_text = translations.get("telegram_filesize", "File Size")
        
        message = f"""⏱️ <b>OC-Proxy: {wait_text}</b> ⏳

📁 <b>{filename_text}</b>
<code>{file_name}</code>

📊 <b>{filesize_text}</b>
<code>{file_size or ('알 수 없음' if lang == 'ko' else 'Unknown')}</code>

⏰ <b>{wait_time_text}</b>
<code>{wait_minutes}분</code>"""
        
        # 텔레그램 API 호출 (비동기)
        import threading
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        def send_async():
            try:
                response = httpx.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    print(f"[LOG] 텔레그램 대기시간 알림 전송 성공: {file_name} ({wait_minutes}분)")
                else:
                    print(f"[WARN] 텔레그램 대기시간 알림 전송 실패: {response.status_code}")
            except Exception as e:
                print(f"[WARN] 텔레그램 대기시간 알림 전송 오류: {e}")
        
        threading.Thread(target=send_async, daemon=True).start()
        
    except Exception as e:
        print(f"[WARN] 텔레그램 대기시간 알림 설정 오류: {e}")


def utc_to_kst(utc_time_str: str) -> str:
    """UTC 시간 문자열을 KST로 변환"""
    try:
        # ISO 형식의 UTC 시간을 파싱
        if utc_time_str.endswith('Z'):
            utc_time_str = utc_time_str[:-1]
        
        utc_dt = datetime.datetime.fromisoformat(utc_time_str)
        # UTC+9 (한국 시간) 적용
        kst_dt = utc_dt + datetime.timedelta(hours=9)
        return kst_dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return utc_time_str or "알 수 없음"

def send_telegram_start_notification(file_name: str, download_mode: str, lang: str = "ko", file_size: str = None, requested_at = None):
    """텔레그램 다운로드 시작 알림 전송"""
    try:
        config = get_config()
        
        bot_token = config.get("telegram_bot_token", "").strip()
        chat_id = config.get("telegram_chat_id", "").strip()
        notify_start = config.get("telegram_notify_start", False)  # 시작 알림 설정
        
        # 설정이 없거나 시작 알림이 비활성화된 경우
        if not bot_token or not chat_id or not notify_start:
            return
        
        # 번역 데이터 가져오기
        translations = get_translations(lang)
        
        # HTML 형식으로 예쁜 메시지 작성
        # 요청시간 사용 (requested_at이 없으면 현재 시간)
        if requested_at:
            if lang == "ko":
                # 한국어일 때만 KST로 표시
                if isinstance(requested_at, str):
                    # 문자열이면 파싱
                    try:
                        dt = datetime.datetime.fromisoformat(requested_at.replace('Z', '+00:00'))
                    except ValueError as e:
                        print(f"[LOG] Date parsing error: {e}")
                        dt = datetime.datetime.utcnow()
                else:
                    dt = requested_at
                current_time = (dt + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
            else:
                # 영어 등 다른 언어는 UTC로 표시
                if isinstance(requested_at, str):
                    try:
                        dt = datetime.datetime.fromisoformat(requested_at.replace('Z', '+00:00'))
                    except ValueError as e:
                        print(f"[LOG] Date parsing error: {e}")
                        dt = datetime.datetime.utcnow()
                else:
                    dt = requested_at
                current_time = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            # requested_at이 없으면 현재 시간 사용 (기존 로직)
            if lang == "ko":
                current_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
            else:
                current_time = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        start_text = translations.get("telegram_download_started", "Download Started")
        filename_text = translations.get("telegram_filename", "Filename")
        started_time_text = translations.get("telegram_started_time", "Started At")
        filesize_text = translations.get("telegram_filesize", "File Size")
        mode_text = translations.get("telegram_download_mode", "Download Mode")
        
        # 다운로드 모드 번역
        if download_mode == "proxy":
            mode_display = "🌐 프록시 모드" if lang == "ko" else "🌐 Proxy Mode"
        else:
            mode_display = "💻 로컬 모드" if lang == "ko" else "💻 Local Mode"
        
        # 디버그 로그 추가
        print(f"[DEBUG] 텔레그램 메시지 생성 - file_size 파라미터: {file_size}, lang: {lang}")
        
        message = f"""🚀 <b>OC-Proxy: {start_text}</b> ⬇️

📁 <b>{filename_text}</b>
<code>{file_name}</code>

📊 <b>{filesize_text}</b>
<code>{file_size or ('알 수 없음' if lang == 'ko' else 'Unknown')}</code>

⚙️ <b>{mode_text}</b>
<code>{mode_display}</code>

🕐 <b>{started_time_text}</b>
<code>{current_time}</code>"""
        
        # 텔레그램 API 호출 (비동기)
        import threading
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        def send_async():
            try:
                response = httpx.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    print(f"[LOG] 텔레그램 다운로드 시작 알림 전송 성공: {file_name}")
                else:
                    print(f"[WARN] 텔레그램 다운로드 시작 알림 전송 실패: {response.status_code}")
            except Exception as e:
                print(f"[WARN] 텔레그램 다운로드 시작 알림 전송 오류: {e}")
        
        threading.Thread(target=send_async, daemon=True).start()
        
    except Exception as e:
        print(f"[WARN] 텔레그램 다운로드 시작 알림 설정 오류: {e}")

def send_telegram_notification(file_name: str, status: str, error: str = None, lang: str = "ko", file_size: str = None, download_time: str = None, save_path: str = None, requested_time: str = None):
    """텔레그램 알림 전송"""
    try:
        config = get_config()
        
        bot_token = config.get("telegram_bot_token", "").strip()
        chat_id = config.get("telegram_chat_id", "").strip()
        notify_success = config.get("telegram_notify_success", False)
        notify_failure = config.get("telegram_notify_failure", True)
        
        # 설정이 없으면 알림 전송하지 않음
        if not bot_token or not chat_id:
            return
            
        # 알림 설정에 따라 전송 여부 결정
        if status == "done" and not notify_success:
            return
        if status == "failed" and not notify_failure:
            return
        
        # 번역 데이터 가져오기
        translations = get_translations(lang)
        
        # HTML 형식으로 예쁜 메시지 작성
        
        # 현재 시간 처리 (시간대 고려)
        if lang == "ko":
            # 한국어일 때는 KST 시간 사용 (UTC+9)
            kst_time = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
            current_time = kst_time.strftime("%Y-%m-%d %H:%M:%S KST")
        else:
            # 영어 등 다른 언어는 UTC 시간 사용
            utc_time = datetime.datetime.utcnow()
            current_time = utc_time.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        if status == "done":
            success_text = translations.get("telegram_download_success", "Download Complete")
            filename_text = translations.get("telegram_filename", "Filename")
            filesize_text = translations.get("telegram_filesize", "파일크기")
            requested_time_text = translations.get("telegram_requested_time", "요청시간")
            completed_time_text = translations.get("telegram_completed_time", "완료시간")
            save_path_text = translations.get("telegram_save_path", "저장경로")

            message = f"""✅ <b>OC-Proxy: {success_text}</b> 🎉

📁 <b>{filename_text}</b>
<code>{file_name}</code>

📊 <b>{filesize_text}</b>
<code>{file_size or '알 수 없음'}</code>

🕐 <b>{requested_time_text}</b>
<code>{requested_time or '알 수 없음'}</code>

✅ <b>{completed_time_text}</b>
<code>{download_time or current_time}</code>

💾 <b>{save_path_text}</b>
<code>{save_path or '기본경로'}</code>"""

        elif status == "failed":
            failed_text = translations.get("telegram_download_failed", "Download Failed")
            filename_text = translations.get("telegram_filename", "Filename")
            error_text = translations.get("telegram_error", "Error")
            failed_time_text = translations.get("telegram_failed_time", "실패시간")

            error_msg = error[:200] + '...' if error and len(error) > 200 else error or '알 수 없는 오류'

            message = f"""🔔 <b>OC-Proxy: {failed_text}</b> ❌

📁 <b>{filename_text}</b>
<code>{file_name}</code>

⚠️ <b>{error_text}</b>
<code>{error_msg}</code>

🕐 <b>{failed_time_text}</b>
<code>{current_time}</code>"""
        else:
            return
            
        # 텔레그램 API 호출
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        # 백그라운드에서 전송 (블로킹 방지)
        def send_async():
            try:
                response = httpx.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    print(f"[LOG] 텔레그램 알림 전송 성공: {file_name}")
                else:
                    print(f"[WARN] 텔레그램 알림 전송 실패: {response.status_code}")
            except Exception as e:
                print(f"[WARN] 텔레그램 알림 전송 오류: {e}")
        
        threading.Thread(target=send_async, daemon=True).start()
        
    except Exception as e:
        print(f"[WARN] 텔레그램 알림 설정 오류: {e}")


def should_retry_download(retry_count: int, error_message: str) -> bool:
    """다운로드 재시도 여부를 판단하는 함수"""
    
    # 네트워크 오류 검사 먼저 수행
    retry_network_errors = [
        "nameresolutionerror",
        "getaddrinfo failed",
        "failed to resolve",
        "connection timeout",
        "connection refused",
        "network is unreachable",
        "temporary failure in name resolution",
        "max retries exceeded",
        "connection aborted",
        "connection reset",
        "httpsconnectionpool",
        "errno 11001",
        "name or service not known",
        "nodename nor servname provided",
        "dns resolution failed"
    ]
    
    error_lower = error_message.lower()
    is_network_error = any(retry_error in error_lower for retry_error in retry_network_errors)
    
    # 최대 10번까지 재시도 허용
    max_retries_for_error = 10
    
    # 재시도 한도 확인
    if retry_count >= max_retries_for_error:
        print(f"[LOG] 재시도 한도 초과: {retry_count}/{max_retries_for_error}")
        return False
    
    # dstorage.fr DNS 오류는 1fichier 링크 만료를 의미하므로 재시도하지 않음
    if "dstorage.fr" in error_lower:
        print(f"[LOG] dstorage.fr DNS 오류 - 1fichier 링크 만료로 판단, 재시도 중단")
        return False
    
    # 일반적인 DNS 해결 실패도 재시도하지 않음 (링크 만료 가능성 높음)
    if any(dns_error in error_lower for dns_error in [
        "failed to resolve", "name or service not known", 
        "no address associated with hostname", "nameresolutionerror"
    ]):
        print(f"[LOG] DNS 해결 실패 - 링크 만료로 판단, 재시도 중단")
        return False
    
    # 재시도 불가능한 오류들
    no_retry_errors = [
        "404",  # 파일을 찾을 수 없음
        "not found",
        "file not found",
        "invalid url",
        "파싱 실패",  # 파싱 실패 시 재시도하지 않음
        "direct link를 찾을 수 없",  # 다운로드 링크 파싱 실패
        "다운로드 링크를 찾을 수 없",  # 다운로드 링크 파싱 실패
        "parsing failed",  # 영문 파싱 실패
        "link expired",  # 링크 만료
        "invalid link",
        "파일을 찾을 수 없습니다",
        "잘못된 링크",
        "permission denied",
        "access denied",
        "unauthorized",
        "forbidden"
    ]
    
    # 네트워크 오류인지 이미 위에서 확인했으므로, 재시도 불가능한 오류만 체크
    for no_retry_error in no_retry_errors:
        if no_retry_error in error_lower:
            print(f"[LOG] 재시도 불가능한 오류: {error_message}")
            return False
    
    if is_network_error:
        print(f"[LOG] 재시도 가능한 네트워크 오류: {error_message}")
    else:
        print(f"[LOG] 재시도 가능한 일반 오류: {error_message}")
    
    return True


def should_1fichier_auto_retry(url: str, file_name: str, file_size: str, fichier_retry_count: int, error_message: str) -> bool:
    """1fichier 무료 다운로드 실패 시 자동 재시도 여부를 판단하는 함수"""
    
    # 1fichier URL이 아니면 재시도하지 않음
    if "1fichier.com" not in url.lower():
        return False
    
    # 파일명과 용량이 존재하지 않으면 유효하지 않은 파일이므로 재시도하지 않음
    if not file_name or not file_size:
        print(f"[LOG] 1fichier 자동 재시도 불가: 파일명({file_name}) 또는 용량({file_size}) 없음")
        return False
    
    # 파일명이 기본값이면 재시도하지 않음
    if file_name in ['1fichier.com: Cloud Storage', '알 수 없음']:
        print(f"[LOG] 1fichier 자동 재시도 불가: 파일명이 기본값({file_name})")
        return False
    
    # 최대 10회까지 재시도 허용
    if fichier_retry_count >= 10:
        print(f"[LOG] 1fichier 자동 재시도 한도 초과: {fichier_retry_count}/10")
        return False
    
    # 재시도 불가능한 오류들 (링크 만료, 권한 문제 등)
    no_retry_errors = [
        "404",
        "not found", 
        "file not found",
        "invalid url",
        "link expired",
        "invalid link",
        "permission denied",
        "access denied", 
        "unauthorized",
        "forbidden",
        "dstorage.fr",
        "파싱 실패",
        "direct link를 찾을 수 없",
        "다운로드 링크를 찾을 수 없"
    ]
    
    error_lower = error_message.lower()
    for no_retry_error in no_retry_errors:
        if no_retry_error in error_lower:
            print(f"[LOG] 1fichier 자동 재시도 불가능한 오류: {error_message}")
            return False
    
    print(f"[LOG] 1fichier 자동 재시도 가능: {fichier_retry_count + 1}/10")
    return True


async def download_1fichier_file(request_id: int, lang: str = "ko", use_proxy: bool = True, retry_count: int = 0, fichier_retry_count: int = 0):
    """
    새로운 프록시 순환 로직을 사용한 1fichier 다운로드 함수
    """
    print("=" * 80)
    print(f"[LOG] *** 새로운 다운로드 시스템 시작 ***")
    print(f"[LOG] Request ID: {request_id}")
    print(f"[LOG] Use Proxy: {use_proxy}")
    print(f"[LOG] 시작 시간: {time.strftime('%H:%M:%S')}")
    print(f"[LOG] 재시도 카운터: {retry_count}, 1fichier 재시도 카운터: {fichier_retry_count}")
    print("=" * 80)
    
    # 다운로드 매니저 import
    
    # 새로운 DB 세션 생성
    db = SessionLocal()
    req = None
    
    try:
        # 즉시 정지 체크 (시작 시점)
        if download_manager.is_download_stopped(request_id):
            print(f"[LOG] 다운로드 시작 전 정지 플래그 감지: ID {request_id}")
            return
        
        # 요청 정보 조회
        req = db.query(DownloadRequest).filter(DownloadRequest.id == request_id).first()
        if req is None:
            print(f"[LOG] 다운로드 요청을 찾을 수 없음: ID {request_id}")
            return
        
        # 다운로드 매니저에 등록 (정지 플래그 생성을 위해 필수)
        download_manager.register_download(request_id, req.url, use_proxy)
        print(f"[LOG] 다운로드 매니저에 등록 완료: ID {request_id}")
        
        # 등록 후 즉시 한 번 더 정지 체크
        if download_manager.is_download_stopped(request_id):
            print(f"[LOG] 다운로드 등록 후 정지 플래그 감지: ID {request_id}")
            download_manager.unregister_download(request_id, auto_start_next=False)
            return
        
        # 즉시 정지 플래그만 초기화 (등록은 실제 다운로드 시작 시점에)
        with download_manager._lock:
            download_manager.stop_events[request_id] = threading.Event()
        print(f"[LOG] 다운로드 {request_id} 정지 플래그 초기화 완료 (등록은 나중에)")
            
        # 지연 시간 체크 (5번 이후 재시도에서 3분 지연)
        if req.error and "delay_until:" in req.error:
            try:
                delay_part = req.error.split("delay_until:")[1].strip()
                delay_until = datetime.datetime.fromisoformat(delay_part)
                current_time = datetime.datetime.utcnow()
                
                if current_time < delay_until:
                    remaining_seconds = int((delay_until - current_time).total_seconds())
                    print(f"[LOG] 재시도 지연 시간 대기 중: {remaining_seconds}초 남음 - ID {request_id}")
                    # 지연 시간이 남아있으면 다시 대기 상태로 유지
                    req.status = StatusEnum.pending
                    req.error = req.error.replace("delay_until:", f"지연대기 중 ({remaining_seconds}초 남음) delay_until:")
                    db.commit()
                    return
                else:
                    # 지연 시간이 지났으면 delay_until 부분 제거
                    req.error = req.error.split(" | delay_until:")[0] if " | delay_until:" in req.error else req.error
                    db.commit()
                    print(f"[LOG] 지연 시간 완료, 다운로드 진행 - ID {request_id}")
            except Exception as delay_error:
                print(f"[LOG] 지연 시간 파싱 오류: {delay_error}")
                # 파싱 오류 시 그냥 진행
        
        # 정지 상태 체크
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드가 이미 정지된 상태: ID {request_id}")
            return
        
        print(f"[LOG] URL: {req.url}")
        print(f"[LOG] 파일명: {req.file_name}")
        print(f"[DEBUG] ★ DB에서 조회한 req.file_name 타입: {type(req.file_name)}")
        print(f"[DEBUG] ★ DB에서 조회한 req.file_name 값: '{req.file_name}'")
        
        # 프록시가 아닌 경우 다운로드 제한 체크
        if not use_proxy:
            if not download_manager.can_start_download(req.url):
                # 사용자가 명시적으로 정지하거나 완료된 경우는 대기 상태로 변경하지 않음
                db.refresh(req)
                if req.status not in [StatusEnum.stopped, StatusEnum.done]:
                    print(f"[LOG] 다운로드 제한에 걸림. 대기 상태로 설정: ID {request_id}")
                    req.status = StatusEnum.pending
                    db.commit()
                    
                    # 대기 이유와 예상 시간 계산
                    wait_message = "다운로드 제한 대기 중..."
                    estimated_wait_time = 30  # 기본 30초
                    
                    # 제한 종류별 대기 시간 추정
                    if len(download_manager.all_downloads) >= download_manager.MAX_TOTAL_DOWNLOADS:
                        wait_message = f"전체 다운로드 제한 ({download_manager.MAX_TOTAL_DOWNLOADS}개) 대기 중..."
                        estimated_wait_time = 60  # 1분
                    elif '1fichier.com' in req.url and len(download_manager.local_downloads) >= download_manager.MAX_LOCAL_DOWNLOADS:
                        cooldown_remaining = download_manager.get_1fichier_cooldown_remaining()
                        if cooldown_remaining > 0:
                            wait_message = f"1fichier 쿨다운 대기 중..."
                            estimated_wait_time = int(cooldown_remaining)
                        else:
                            wait_message = f"1fichier 다운로드 제한 ({download_manager.MAX_LOCAL_DOWNLOADS}개) 대기 중..."
                            estimated_wait_time = 120  # 2분
                    
                    # wait_countdown 메시지 전송
                    send_sse_message("wait_countdown", {
                        "id": req.id,
                        "remaining_time": estimated_wait_time,
                        "wait_message": wait_message,
                        "url": req.url,
                        "file_name": req.file_name
                    })
                    
                    # SSE로 대기 상태 알림
                    send_sse_message("status_update", {
                        "id": req.id,
                        "url": req.url,
                        "file_name": req.file_name,
                        "status": "waiting", 
                        "message": "다운로드 대기 중",
                        "requested_at": req.requested_at.isoformat() if req.requested_at else None
                    })
                
                # 매니저가 자동으로 시작해주므로 여기서는 그냥 종료
                print(f"[LOG] 매니저의 자동 시작 기능에 의해 대기: ID {request_id}")
                return
        
        # 다운로드 등록 (제한에 걸리지 않은 경우만)
        download_manager.register_download(request_id, req.url, use_proxy)
        
        
        # 다운로드 경로 설정
        download_path = get_download_path()
        
        # ★ 디버그: 파일명 상태 확인
        # DB에서 최신 상태 새로고침 (파일명이 업데이트되었을 수 있음)
        db.refresh(req)
        
        print(f"[DEBUG] 다운로드 실행 전 req.file_name (새로고침 후): '{req.file_name}'")
        print(f"[DEBUG] req.file_name 타입: {type(req.file_name)}")
        print(f"[DEBUG] req.file_name이 None인가: {req.file_name is None}")
        print(f"[DEBUG] req.file_name이 빈 문자열인가: {req.file_name == '' if req.file_name else 'N/A'}")
        print(f"[DEBUG] req.file_name.strip()이 비어있나: {req.file_name.strip() == '' if req.file_name else 'N/A'}")
        
        # DB에서 가져온 파일명이 있으면 그것을 사용, 없으면 fallback
        print(f"[CRITICAL_DEBUG] === 파일명 결정 로직 ===")
        print(f"[CRITICAL_DEBUG] request_id: {request_id}")
        print(f"[CRITICAL_DEBUG] req.file_name 원본: '{req.file_name}' (type: {type(req.file_name)})")
        print(f"[CRITICAL_DEBUG] req.file_name is None: {req.file_name is None}")
        print(f"[CRITICAL_DEBUG] req.file_name == '': {req.file_name == '' if req.file_name is not None else 'N/A'}")
        if req.file_name:
            print(f"[CRITICAL_DEBUG] req.file_name.strip(): '{req.file_name.strip()}' (길이: {len(req.file_name.strip())})")
            print(f"[CRITICAL_DEBUG] req.file_name.strip() == '': {req.file_name.strip() == ''}")
        print(f"[CRITICAL_DEBUG] 조건 (req.file_name and req.file_name.strip()): {bool(req.file_name and req.file_name.strip())}")
        
        if req.file_name and req.file_name.strip():
            base_filename = req.file_name.strip()
            print(f"[LOG] ★★★ DB에서 가져온 파일명 사용: '{base_filename}' ★★★")
        else:
            base_filename = f"1fichier_{request_id}.unknown"
            print(f"[LOG] ★★★ DB에 파일명이 없어서 fallback 사용: '{base_filename}' ★★★")
            print(f"[CRITICAL_DEBUG] === 이 경우는 사전파싱 실패를 의미함! ===")
        print(f"[DEBUG] 결정된 base_filename: '{base_filename}'")
        
        # Windows에서 파일명에 사용할 수 없는 문자 제거 (간단하게)
        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', base_filename)
        safe_filename = safe_filename.strip('. ')  # 앞뒤 공백과 점 제거
        
        # 빈 파일명 방지 (실제 파일명이 없는 경우만)
        if not safe_filename:
            safe_filename = f"1fichier_{request_id}.unknown"
            print(f"[DEBUG] 빈 파일명 방지로 fallback: '{safe_filename}'")
            
        print(f"[LOG] 원본 파일명: '{base_filename}', 안전한 파일명: '{safe_filename}'")
        
        # 중복 파일명 방지
        final_path = get_unique_filepath(download_path / safe_filename)
        
        file_path = final_path
        part_file_path = download_path / (final_path.name + ".part")
        
        # DB에 저장 경로 업데이트
        req.save_path = str(file_path)
        db.commit()
        print(f"[LOG] 저장 경로 설정: {file_path}")
        
        # SSE로 저장 경로 업데이트 전송
        send_sse_message("status_update", {
            "id": req.id,
            "url": req.url,
            "file_name": req.file_name,
            "status": req.status.value if hasattr(req.status, 'value') else str(req.status),
            "save_path": req.save_path,
            "total_size": req.total_size or 0,
            "downloaded_size": req.downloaded_size or 0,
            "use_proxy": req.use_proxy
        })
        
        # 기존 파일 확인 (재시도/재개 여부에 따라 메시지 구분)
        initial_downloaded_size = 0
        is_resume = (retry_count > 0 or req.status == StatusEnum.stopped)  # 재시도이거나 정지 상태에서 재개
        
        if part_file_path.exists():
            file_path = part_file_path
            initial_downloaded_size = part_file_path.stat().st_size
            if is_resume:
                print(f"[LOG] 이어받기: {initial_downloaded_size} bytes")
            else:
                print(f"[LOG] 기존 미완료 파일 발견 - 새 다운로드로 계속: {initial_downloaded_size} bytes")
        elif file_path.exists():
            initial_downloaded_size = file_path.stat().st_size
            if is_resume:
                print(f"[LOG] 기존 파일 발견 - 이어받기: {initial_downloaded_size} bytes")
            else:
                # 완전히 다운로드된 파일이면 100% 완료 처리하고 종료
                print(f"[LOG] 기존 완료 파일 발견: {initial_downloaded_size} bytes - 완료 처리")
                req.status = StatusEnum.done
                req.downloaded_size = initial_downloaded_size
                req.total_size = initial_downloaded_size
                req.finished_at = datetime.datetime.utcnow()
                db.commit()
                
                # SSE로 완료 알림
                send_sse_message("status_update", {
                    "id": req.id,
                    "status": "done",
                    "progress": 100.0,
                    "downloaded_size": initial_downloaded_size,
                    "total_size": initial_downloaded_size,
                    "message": "기존 완료 파일 발견 - 완료 처리됨"
                })
                return  # 다운로드 종료
        else:
            file_path = part_file_path
            print(f"[LOG] 새 다운로드 시작")
        
        # 정지 상태 재체크
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 정지됨 (파싱 시작 전): ID {request_id}")
            return
        
        # 1단계: Direct Link 파싱
        direct_link = None
        used_proxy_addr = None
        
        if use_proxy:
            print(f"[LOG] 프록시 모드로 다운로드 링크 파싱 시작")
            
            # 즉시 정지 체크 - proxying 상태 변경 전에
            if download_manager.is_download_stopped(request_id):
                print(f"[LOG] proxying 상태 변경 전 즉시 정지 플래그 감지: ID {request_id}")
                return
            
            req.status = StatusEnum.proxying
            db.commit()
            
            # 즉시 정지 체크 - WebSocket 메시지 전송 전에
            if download_manager.is_download_stopped(request_id):
                print(f"[LOG] WebSocket 메시지 전송 전 즉시 정지 플래그 감지: ID {request_id}")
                return
            
            # SSE로 상태 업데이트 알림
            send_sse_message("status_update", {
                "id": req.id,
                "url": req.url,
                "file_name": req.file_name,
                "status": "proxying",
                "error": None
            })
            force_reparse = initial_downloaded_size > 0
            print(f"[LOG] 강제 재파싱 모드: {force_reparse} (이어받기: {initial_downloaded_size > 0})")
            direct_link, used_proxy_addr = parse_with_proxy_cycling(req, db, force_reparse=force_reparse)
        else:
            print(f"[LOG] 로컬 모드로 Direct Link 파싱")
            req.status = StatusEnum.downloading
            db.commit()
            
            # SSE로 상태 업데이트 알림 
            send_sse_message("status_update", {
                "id": req.id,
                "url": req.url,
                "file_name": req.file_name,
                "status": "downloading",
                "error": None
            })
            
            # 재시도이거나 이어받기인 경우 항상 강제 재파싱 (원본 URL로 새로 파싱)
            force_reparse = initial_downloaded_size > 0
            print(f"[LOG] 강제 재파싱 모드: {force_reparse} (이어받기: {initial_downloaded_size > 0})")
            
            # 로컬 모드에서는 파일 정보와 함께 파싱
            print(f"[LOG] parse_direct_link_with_file_info 시작: {req.url}")
            direct_link, file_info = parse_direct_link_with_file_info(
                req.url, req.password, use_proxy=False
            )
            print(f"[LOG] parse_direct_link_with_file_info 결과: direct_link={direct_link}, file_info={file_info}")
            
            # 파일 정보가 추출되면 DB에 저장 (먼저 처리하여 파일명 보존)
            if file_info and file_info['name'] and (not req.file_name or req.file_name.strip() == ''):
                req.file_name = file_info['name']
                print(f"[LOG] 파일명 추출: {file_info['name']}")
                db.commit()
            
            # 파일 정보 파싱 실패 시 기존 파싱 로직 사용 (단, 파일명은 보존)
            if not direct_link:
                # 재시도 전에 정지 플래그 체크
                if download_manager.is_download_stopped(request_id):
                    print(f"[LOG] 기존 파싱 로직 재시도 전 정지 플래그 감지: ID {request_id}")
                    return
                
                print(f"[LOG] Direct Link 실패. 기존 파싱 로직으로 재시도 (파일명 보존)")
                direct_link = get_or_parse_direct_link(req, use_proxy=False, force_reparse=force_reparse)
                
                # SSE로 파일명 업데이트 전송
                send_sse_message("filename_update", {
                    "id": req.id,
                    "file_name": req.file_name,
                    "url": req.url,
                    "status": req.status.value if hasattr(req.status, 'value') else str(req.status)
                })
            
        
        # 파싱 완료 후 정지 플래그 체크 (다운로드 진행 전)
        if download_manager.is_download_stopped(request_id):
            print(f"[LOG] 파싱 완료 후 정지 플래그 감지: ID {request_id}")
            return
        
        # 파싱 완료 후 파일명 확인 (프록시/로컬 공통)
        print(f"[LOG] 파싱 완료 후 파일명 체크: req.file_name='{req.file_name}', type={type(req.file_name)}, len={len(req.file_name) if req.file_name else 'None'}")
        print(f"[LOG] 파일명 조건 체크: not req.file_name={not req.file_name}, strip()==''{req.file_name.strip() == '' if req.file_name else 'N/A'}, equals_cloud_storage={req.file_name == '1fichier.com: Cloud Storage' if req.file_name else 'N/A'}")
        
        # 파일명이 없거나 기본값인 경우 fallback 로직 시도 (fallback은 최소화)
        if not req.file_name or req.file_name.strip() == '' or req.file_name == '1fichier.com: Cloud Storage':
            print(f"[WARNING] 파싱된 파일명이 없습니다. fallback 로직 시작")
            
            # URL에서 파일명 추출 시도
            parsed_url = urlparse(req.url)
            url_filename = None
            
            # URL 경로에서 파일명 추출
            if parsed_url.path and '/' in parsed_url.path:
                url_filename = unquote(parsed_url.path.split('/')[-1])
                if url_filename and len(url_filename) > 3 and '.' in url_filename:
                    print(f"[LOG] URL에서 파일명 추출: '{url_filename}'")
                    req.file_name = url_filename
                    db.commit()
            
            # 여전히 파일명이 없다면 임시 파일명 사용 (다운로드 중 Content-Disposition에서 업데이트됨)
            if not req.file_name or req.file_name.strip() == '' or req.file_name == '1fichier.com: Cloud Storage':
                print(f"[WARNING] 파일명을 확정할 수 없어 임시명 사용 - Content-Disposition에서 추출 시도")
                req.file_name = f"1fichier_{req.id}.tmp"  # 임시 파일명 설정
                db.commit()
        else:
            print(f"[LOG] 파싱된 파일명 사용: '{req.file_name}'")

        # 파일명이 업데이트된 경우 저장 경로도 다시 설정
        # 조건: 실제 파일명이 있고, 현재 저장 경로가 임시 파일명을 사용하고 있는 경우
        current_save_path = req.save_path or ""
        is_temp_path = ('.unknown' in current_save_path or '1fichier_' in current_save_path)
        has_real_filename = (req.file_name and req.file_name.strip() and 
                           not req.file_name.startswith('1fichier_') and 
                           not req.file_name.endswith('.tmp') and
                           not req.file_name.endswith('.unknown'))
        
        if has_real_filename and (is_temp_path or not current_save_path):
            print(f"[LOG] 임시 경로에서 실제 파일명으로 경로 재설정: '{req.file_name}'")
            
            # 안전한 파일명 생성
            safe_filename = re.sub(r'[<>:"/\\|?*]', '_', req.file_name.strip())
            safe_filename = safe_filename.strip('. ')
            
            # 중복 파일명 방지
            final_path = get_unique_filepath(download_path / safe_filename)
            
            # 저장 경로 업데이트
            req.save_path = str(final_path)
            db.commit()
            print(f"[LOG] 저장 경로 업데이트 완료: {final_path}")
            
            # SSE로 저장 경로 업데이트 전송
            send_sse_message("status_update", {
                "id": req.id,
                "url": req.url,
                "file_name": req.file_name,
                "status": req.status.value if hasattr(req.status, 'value') else str(req.status),
                "save_path": req.save_path,
                "total_size": req.total_size or 0,
                "downloaded_size": req.downloaded_size or 0,
                "use_proxy": req.use_proxy
            })

        # 정지 상태 체크 (파싱 후) - 정지 플래그 우선 확인
        if download_manager.is_download_stopped(request_id):
            print(f"[LOG] 다운로드 정지 플래그 감지됨 (파싱 후): ID {request_id}")
            return
            
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 정지됨 (파싱 후): ID {request_id}")
            return
        
        # direct_link 유효성 체크 (DNS 오류 등으로 인한 만료된 링크 감지)
        if direct_link:
            print(f"[LOG] Direct Link 유효성 체크: {direct_link}")
            if is_direct_link_expired(direct_link, use_proxy=use_proxy):
                print(f"[LOG] Direct Link 만료 감지 - 강제 재파싱 시도: {direct_link}")
                # direct_link 필드 제거됨
                
                # 강제 재파싱
                if use_proxy:
                    direct_link, used_proxy_addr = parse_with_proxy_cycling(req, db, force_reparse=True)
                else:
                    direct_link = get_or_parse_direct_link(req, use_proxy=False, force_reparse=True)
                
                print(f"[LOG] 재파싱 결과: {direct_link}")
        
        if not direct_link:
            # URL 유효성 체크를 통한 더 자세한 에러 메시지
            try:
                test_response = httpx.head(req.url, timeout=5)
                if test_response.status_code == 404:
                    error_msg = "파일이 존재하지 않거나 삭제됨 (404 에러)"
                elif test_response.status_code == 403:
                    error_msg = "파일 접근이 거부됨 (403 에러)"
                else:
                    error_msg = f"Direct Link 파싱 실패 (HTTP {test_response.status_code})"
            except:
                error_msg = "Direct Link 파싱 실패 - URL에 접근할 수 없음"
            
            print(f"[LOG] {error_msg}")
            req.status = StatusEnum.failed
            req.error = error_msg
            db.commit()
            
            # 텔레그램 알림은 아래에서 재시도 여부 확인 후 전송
            
            # SSE로 실패 상태 전송
            send_sse_message("status_update", {
                "id": req.id,
                "url": req.url,
                "file_name": req.file_name,
                "status": "failed",
                "error": error_msg,
                "downloaded_size": 0,
                "total_size": 0,
                "save_path": None,
                "requested_at": req.requested_at.isoformat() if req.requested_at else None,
                "finished_at": None,
                "password": req.password,
                "direct_link": None,  # direct_link 필드 제거됨
                "use_proxy": req.use_proxy
            })
            
            raise Exception(error_msg)
        
        # 특별한 다운로드 모드 처리
        if direct_link in ["DIRECT_DOWNLOAD_STREAM", "DIRECT_FILE_RESPONSE"]:
            print(f"[LOG] 직접 다운로드 모드: {direct_link}")
            # direct_link 필드 제거됨
            req.status = StatusEnum.downloading
            db.commit()
            
            # 실제 파일 다운로드를 위해 다시 파싱 시도
            print(f"[LOG] 실제 다운로드를 위한 재파싱 시도...")
            try:
                if use_proxy:
                    real_link, used_proxy_addr = parse_with_proxy_cycling(req, db, force_reparse=True)
                    if real_link and real_link not in ["DIRECT_DOWNLOAD_STREAM", "DIRECT_FILE_RESPONSE"]:
                        direct_link = real_link
                        print(f"[LOG] 재파싱으로 실제 링크 획득: {direct_link}")
                    else:
                        print(f"[LOG] 재파싱 실패 - 기본 다운로드 방법 사용")
                else:
                    real_link = get_or_parse_direct_link(req, use_proxy=False, force_reparse=True)
                    if real_link and real_link not in ["DIRECT_DOWNLOAD_STREAM", "DIRECT_FILE_RESPONSE"]:
                        direct_link = real_link
                        print(f"[LOG] 재파싱으로 실제 링크 획득: {direct_link}")
                    else:
                        print(f"[LOG] 재파싱 실패 - 특별 처리 모드 유지")
            except Exception as e:
                print(f"[LOG] 재파싱 중 오류: {e}")
            
        else:
            print(f"[LOG] Direct Link 획득: {direct_link}")
            # direct_link 필드 제거됨
            req.status = StatusEnum.downloading
            db.commit()
            
            # 텔레그램 다운로드 시작 알림 전송
            try:
                download_mode = "proxy" if use_proxy else "local"
                # 파일크기 - DB의 file_size 우선, 없으면 total_size 사용
                file_size_str = None
                if req.file_size and req.file_size.strip():
                    file_size_str = req.file_size  # DB에서 파싱된 파일크기 우선 사용
                elif req.total_size and req.total_size > 0:
                    file_size_str = format_file_size(req.total_size)
                
                print(f"[DEBUG] 1fichier 텔레그램 알림 - total_size: {req.total_size}, file_size_str: {file_size_str}")
                
                send_telegram_start_notification(
                    file_name=req.file_name or "Unknown File",
                    download_mode=download_mode,
                    lang=language,
                    file_size=file_size_str,
                    requested_at=req.requested_at
                )
            except Exception as e:
                print(f"[LOG] 텔레그램 시작 알림 전송 실패: {e}")
            
            # 다운로드 시작 시 즉시 WebSocket 상태 업데이트 (프로그레스바 즉시 시작)
            send_sse_message("status_update", {
                "id": req.id,
                "url": req.url,
                "file_name": req.file_name,
                "status": "downloading",
                "error": None,
                "downloaded_size": initial_downloaded_size,
                "total_size": req.total_size or 0,
                "save_path": req.save_path,
                "requested_at": req.requested_at.isoformat() if req.requested_at else None,
                "finished_at": None,
                "password": req.password,
                "direct_link": None,  # direct_link 필드 제거됨
                "use_proxy": req.use_proxy
            })
            
            # 정지 상태 체크 (다운로드 시작 전)
            db.refresh(req)
            if req.status == StatusEnum.stopped:
                print(f"[LOG] 다운로드 정지됨 (다운로드 시작 전): ID {request_id}")
                return
            
            # 2단계: 프록시 순환으로 실제 다운로드
            try:
                if use_proxy:
                    print(f"[LOG] 프록시 순환 다운로드 시작 (시작 프록시: {used_proxy_addr})")
                    await download_with_proxy_cycling(direct_link, file_path, used_proxy_addr, initial_downloaded_size, req, db)
                else:
                    print(f"[LOG] 로컬 연결로 다운로드 시작")
                    await download_local(direct_link, file_path, initial_downloaded_size, req, db)
            except Exception as download_error:
                print(f"[ERROR] 다운로드 중 오류 발생 - 서버 유지: {type(download_error).__name__}: {download_error}")
                # 특정 오류 타입에 대한 자세한 로깅
                if "decompressing" in str(download_error).lower() or "deflate" in str(download_error).lower():
                    print(f"[ERROR] 압축 해제 오류 감지: {download_error}")
                    print(f"[ERROR] 이는 보통 서버의 잘못된 압축 데이터로 인한 것입니다")
                elif "stream" in str(download_error).lower() and "closed" in str(download_error).lower():
                    print(f"[ERROR] 스트림 연결 오류 감지: {download_error}")
                    print(f"[ERROR] 네트워크 연결이 중단되었습니다")
                # 오류를 다시 발생시켜 기존 재시도 로직이 동작하도록 함
                raise download_error
        
        # 정지 상태 체크 (완료 처리 전)
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 정지됨 (완료 처리 전): ID {request_id}")
            return
        
        # 3단계: 완료 처리
        # 파일 정리 먼저 수행 (.part 제거)
        final_file_path = cleanup_download_file(file_path)
        
        # 실제 파일명이 있고 현재 파일명이 임시 파일명인 경우 실제 파일명으로 변경
        if (req.file_name and req.file_name.strip() and 
            not req.file_name.startswith('1fichier_') and 
            not req.file_name.endswith('.unknown') and
            final_file_path and '1fichier_' in str(final_file_path)):
            
            try:
                
                current_path = Path(final_file_path)
                download_dir = current_path.parent
                
                # 안전한 파일명 생성
                safe_filename = re.sub(r'[<>:"/\\|?*]', '_', req.file_name.strip())
                safe_filename = safe_filename.strip('. ')
                
                if safe_filename:
                    # 중복 파일명 방지
                    new_final_path = get_unique_filepath(download_dir / safe_filename)
                    
                    # 파일명 변경
                    os.rename(final_file_path, new_final_path)
                    final_file_path = new_final_path
                    print(f"[LOG] 임시 파일명에서 실제 파일명으로 변경: {current_path.name} -> {new_final_path.name}")
                    
            except Exception as e:
                print(f"[LOG] 파일명 변경 실패 (임시 파일명 유지): {e}")
        
        # DB 업데이트
        req.status = StatusEnum.done
        req.finished_at = datetime.datetime.utcnow()
        if final_file_path:
            req.save_path = str(final_file_path)
        db.commit()
        
        # 다운로드 완료 - 매니저에서 해제하여 다음 큐 자동 시작
        download_manager.unregister_download(request_id, is_completed=True, auto_start_next=True)
        print(f"[LOG] 다운로드 완료 - 매니저에서 해제하여 다음 큐 자동 시작: ID {request_id}")
        
        # 텔레그램 알림 전송 (완료)
        unknown_file = get_translations(lang).get("telegram_unknown_file", "알 수 없는 파일")
        
        # 파일 크기 포맷팅
        file_size_str = "알 수 없음"
        if req.total_size:
            file_size_str = format_file_size(req.total_size)

        # 시간 포맷팅
        requested_time_str = None
        if req.requested_at:
            if lang == "ko":
                # 한국어일 때는 KST 시간으로 변환 (UTC+9)
                kst_requested = req.requested_at + datetime.timedelta(hours=9)
                requested_time_str = kst_requested.strftime("%Y-%m-%d %H:%M:%S KST")
            else:
                # 영어 등 다른 언어는 UTC 그대로 표시
                requested_time_str = req.requested_at.strftime("%Y-%m-%d %H:%M:%S UTC")

        download_time_str = None
        if req.finished_at:
            if lang == "ko":
                # 한국어일 때는 KST 시간으로 변환 (UTC+9)
                kst_finished = req.finished_at + datetime.timedelta(hours=9)
                download_time_str = kst_finished.strftime("%Y-%m-%d %H:%M:%S KST")
            else:
                # 영어 등 다른 언어는 UTC 그대로 표시
                download_time_str = req.finished_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # 저장 경로 (언어별 기본값)
        if lang == "ko":
            save_path_str = req.save_path or "기본경로"
        else:
            save_path_str = req.save_path or "Default path"
        
        send_telegram_notification(
            req.file_name or unknown_file, 
            "done", 
            None, 
            lang,
            file_size=file_size_str,
            download_time=download_time_str,
            save_path=save_path_str,
            requested_time=requested_time_str
        )
        
        # SSE로 완료 상태 전송
        send_sse_message("status_update", {
            "id": req.id,
            "url": req.url,
            "file_name": req.file_name,
            "status": "done",
            "error": None,
            "downloaded_size": req.downloaded_size or 0,
            "total_size": req.total_size or 0,
            "progress": 100.0,  # 완료 시 명시적으로 100% 설정
            "save_path": req.save_path,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "finished_at": req.finished_at.isoformat() if req.finished_at else None,
            "password": req.password,
            "direct_link": None,  # direct_link 필드 제거됨
            "use_proxy": req.use_proxy
        })
        
        print(f"[LOG] 다운로드 완료: {req.file_name}")
        
    except Exception as e:
        error_str = str(e)
        print(f"[ERROR] 다운로드 실패: {error_str}")
        print(f"[DEBUG] 에러 타입: {type(e).__name__}")
        print(f"[DEBUG] 에러 세부사항: {repr(e)}")
        
        if req:
            # 정지 상태가 아닐 때만 실패로 처리
            db.refresh(req)
            if req.status != StatusEnum.stopped:
                # 재시도 로직 확인  
                error_str = str(e)
                should_retry = should_retry_download(retry_count, error_str)
                print(f"[LOG] 재시도 여부 결정: {should_retry} (현재 재시도: {retry_count})")
                
                # 완료된 다운로드는 재시도하지 않음
                if should_retry and req.status != StatusEnum.done:
                    new_retry_count = retry_count + 1
                    req.status = StatusEnum.pending  # 다시 대기 상태로
                    
                    # 5번 이후부터는 3분(180초) 지연 추가
                    import datetime
                    current_time = datetime.datetime.utcnow()
                    if new_retry_count > 5:
                        delay_until = current_time + datetime.timedelta(minutes=3)
                        req.error = f"재시도 {new_retry_count} (3분 지연 후 재시도): {str(e)} | delay_until:{delay_until.isoformat()}"
                        print(f"[LOG] 다운로드 재시도 예약 (3분 지연): {new_retry_count} - {delay_until.isoformat()}")
                    else:
                        req.error = f"재시도 {new_retry_count}: {str(e)}"
                        print(f"[LOG] 다운로드 재시도 예약: {new_retry_count}")
                    
                    db.commit()
                    
                    # SSE로 재시도 상태 전송
                    send_sse_message("status_update", {
                        "id": req.id,
                        "url": req.url,
                        "file_name": req.file_name,
                        "status": "pending",
                        "error": req.error,
                        "downloaded_size": req.downloaded_size or 0,
                        "total_size": req.total_size or 0,
                        "progress": 0.0,  # 재시도 시 진행률 초기화
                        "save_path": req.save_path,
                        "requested_at": req.requested_at.isoformat() if req.requested_at else None,
                        "finished_at": None,
                        "password": req.password,
                        "direct_link": None,  # direct_link 필드 제거됨
                        "use_proxy": req.use_proxy
                    })
                    
                    # 3초 후 재시도를 위해 상태를 pending으로 변경 (매니저가 자동으로 시작하도록)
                    print(f"[LOG] 3초 후 자동 재시도를 위해 대기 상태로 설정: ID {request_id}")
                    # 재시도 스레드를 직접 생성하지 않고 매니저의 자동 시작 기능 사용
                    
                else:
                    # 1fichier 자동 재시도 체크 (파일명과 용량이 있으면)
                    # 단, 사용자가 명시적으로 정지한 경우는 재시도하지 않음
                    db.refresh(req)
                    if (req.status != StatusEnum.stopped and req.status != StatusEnum.done and 
                        should_1fichier_auto_retry(req.url, req.file_name, req.file_size, fichier_retry_count, str(e))):
                        new_fichier_retry_count = fichier_retry_count + 1
                        print(f"[LOG] 1fichier 자동 재시도 시작: {new_fichier_retry_count}/10")
                        
                        # 상태를 pending으로 설정하여 대기 중임을 표시
                        req.status = StatusEnum.pending
                        
                        # 5번 이후부터는 3분(180초) 지연 추가
                        import datetime
                        current_time = datetime.datetime.utcnow()
                        if new_fichier_retry_count > 5:
                            delay_until = current_time + datetime.timedelta(minutes=3)
                            req.error = f"1fichier 자동 재시도 중 ({new_fichier_retry_count}/10, 3분 지연 후 재시도) - {str(e)} | delay_until:{delay_until.isoformat()}"
                            print(f"[LOG] 1fichier 자동 재시도 (3분 지연): {new_fichier_retry_count}/10 - {delay_until.isoformat()}")
                        else:
                            req.error = f"1fichier 자동 재시도 중 ({new_fichier_retry_count}/10) - {str(e)}"
                        
                        db.commit()
                        
                        # SSE로 재시도 대기 상태 전송
                        send_sse_message("status_update", {
                            "id": req.id,
                            "url": req.url,
                            "file_name": req.file_name,
                            "status": "pending",
                            "error": req.error,
                            "downloaded_size": req.downloaded_size or 0,
                            "total_size": req.total_size or 0,
                            "progress": 0.0,
                            "save_path": req.save_path,
                            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
                            "finished_at": None,
                            "password": req.password,
                            "direct_link": None,  # direct_link 필드 제거됨
                            "use_proxy": req.use_proxy
                        })
                        
                        # 3분 후 자동 재시도를 위해 대기 상태로 설정
                        print(f"[LOG] 3분 후 1fichier 자동 재시도를 위해 대기 상태로 설정: ID {request_id}")
                        # 매니저가 쿨다운 후 자동으로 시작하도록 함
                        
                    else:
                        # 재시도 한도 초과 또는 재시도 불가능한 오류
                        req.status = StatusEnum.failed
                        req.error = str(e)
                        db.commit()
                        
                        # 텔레그램 알림 전송 (최종 실패)  
                        unknown_file = get_translations(lang).get("telegram_unknown_file", "알 수 없는 파일")
                        
                        # 파일 크기 포맷팅
                        file_size_str = "알 수 없음"
                        if req.total_size:
                            if req.total_size >= 1024*1024*1024:  # GB
                                file_size_str = f"{req.total_size/(1024*1024*1024):.2f} GB"
                            elif req.total_size >= 1024*1024:  # MB
                                file_size_str = f"{req.total_size/(1024*1024):.2f} MB"
                            elif req.total_size >= 1024:  # KB
                                file_size_str = f"{req.total_size/1024:.2f} KB"
                            else:
                                file_size_str = f"{req.total_size} B"
                        
                        send_telegram_notification(
                            req.file_name or unknown_file, 
                            "failed", 
                            str(e), 
                            lang,
                            file_size=file_size_str
                        )
                        
                        # SSE로 실패 상태 전송
                        send_sse_message("status_update", {
                            "id": req.id,
                            "url": req.url,
                            "file_name": req.file_name,
                            "status": "failed",
                            "error": str(e),
                            "downloaded_size": req.downloaded_size or 0,
                            "total_size": req.total_size or 0,
                            "progress": 0.0,  # 실패 시 진행률을 0으로 설정
                            "save_path": req.save_path,
                            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
                            "finished_at": None,
                            "password": req.password,
                            "direct_link": None,  # direct_link 필드 제거됨
                            "use_proxy": req.use_proxy
                        })
                        
                        print(f"[LOG] 다운로드 실패로 매니저에서 해제됨: {request_id}")
                
            else:
                print(f"[LOG] 다운로드가 정지 상태이므로 실패 처리하지 않음: ID {request_id}")
    
    finally:
        # active_downloads에서 제거 (중복 시작 방지용)
        with download_manager._lock:
            download_manager.active_downloads.pop(request_id, None)
            
        # 다운로드 해제 - 완료 여부 확인하여 전달
        if req:
            db.refresh(req)
            is_completed = (req.status == StatusEnum.done)  # 성공적으로 완료된 경우만 True
            is_local_download = not use_proxy and '1fichier.com' in req.url  # 1fichier 로컬 다운로드인지 확인
            
            if is_completed and is_local_download:
                print(f"[LOG] 1fichier 로컬 다운로드 완료: ID {request_id}, 쿨다운 적용")
            
            download_manager.unregister_download(request_id, is_completed=(is_completed and is_local_download))
        
        db.close()


def parse_filename_with_proxy_cycling(req, db: Session):
    """프록시를 사용해서 파일명만 빠르게 파싱"""
    
    # 프록시 목록 가져오기
    all_unused_proxies = get_unused_proxies(db)
    if not all_unused_proxies:
        print(f"[LOG] 사용 가능한 프록시가 없음")
        return None
        
    print(f"[LOG] 파일명 파싱용 {len(all_unused_proxies)}개 프록시 확보")
    
    # 배치 단위로 프록시 테스트해서 성공하는 것 찾기
    batch_size = 6
    proxy_index = 0
    
    while proxy_index < len(all_unused_proxies):
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 파일명 파싱이 정지된 상태: ID {req.id}")
            return None
            
        batch_end = min(proxy_index + batch_size, len(all_unused_proxies))
        current_batch = all_unused_proxies[proxy_index:batch_end]
        
        print(f"[LOG] 파일명 파싱 배치 테스트 {proxy_index}-{batch_end-1}: {len(current_batch)}개 프록시")
        
        working_proxies = get_working_proxy_batch(current_batch)
        if not working_proxies:
            print(f"[LOG] 이 배치에서 작동하는 프록시 없음")
            proxy_index = batch_end
            continue
            
        print(f"[LOG] {len(working_proxies)}개의 검증된 프록시로 파일명 파싱 시도")
        
        # 검증된 프록시들로 파일명 파싱 시도
        for proxy_addr in working_proxies:
            if req.status == StatusEnum.stopped:
                return None
                
            try:
                print(f"[LOG] 프록시 {proxy_addr}로 파일명 파싱 시도")
                result = parse_filename_only_with_proxy(req.url, req.password, proxy_addr)
                if result and result.get('filename'):
                    print(f"[LOG] [OK] 파일명 파싱 성공: {result['filename']} (프록시: {proxy_addr})")
                    return result
                    
            except Exception as e:
                print(f"[LOG] [FAIL] 파일명 파싱 실패 (프록시: {proxy_addr}): {e}")
                continue
                
        proxy_index = batch_end
        
    print(f"[LOG] [ERROR] 모든 프록시로 파일명 파싱 실패")
    return None

def parse_with_proxy_cycling(req, db: Session, force_reparse=False):
    """프록시 배치를 병렬 테스트해서 성공한 프록시들로 파싱"""
    
    # 프록시 목록 한 번만 가져와서 캐시
    all_unused_proxies = get_unused_proxies(db)
    if not all_unused_proxies:
        print(f"[LOG] 사용 가능한 프록시가 없음")
        return None, None
        
    print(f"[LOG] 총 {len(all_unused_proxies)}개 프록시 캐시됨")
    
    # 프록시가 다 소진될 때까지 배치 단위로 계속 시도
    batch_size = 10
    batch_num = 0
    proxy_index = 0
    
    while True:
        batch_num += 1
        print(f"[LOG] 프록시 배치 {batch_num} 테스트 중...")
        
        # 배치 테스트 상태 알림 (활성 다운로드 중이 아닐 때만)
        if not download_manager.is_download_active(req.id):
            # 진행률 계산: 이미 다운로드된 부분이 있으면 그것부터, 없으면 0부터
            current_progress = 0
            if req.total_size > 0 and req.downloaded_size > 0:
                current_progress = min(95, (req.downloaded_size / req.total_size) * 100)
            
            send_sse_message("status_update", {
                "id": req.id,
                "status": "parsing",
                "message": get_message("proxy_batch_testing").format(batch=batch_num),
                "progress": current_progress,
                "url": req.url
            })
        
        # 정지 상태 체크
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 프록시 배치 테스트 중 정지됨: {req.id}")
            return None, None
        
        # 현재 배치에 사용할 프록시들 선택
        batch_proxies = all_unused_proxies[proxy_index:proxy_index + batch_size]
        
        if not batch_proxies:
            print(f"[LOG] 모든 프록시가 소진됨 - 배치 테스트 종료")
            break
            
        print(f"[LOG] 배치 {batch_num}: {len(batch_proxies)}개 프록시 테스트")
        
        # 배치 프록시를 병렬 테스트 (캐시된 목록 사용)
        # 재시작 직후 5분 이내에는 관대한 모드 사용
        server_start_time = getattr(download_manager, '_server_start_time', time.time())
        use_lenient_mode = (time.time() - server_start_time) < 300  # 5분
        
        working_proxies, failed_proxies = test_proxy_batch(db, batch_proxies, req=req, lenient_mode=use_lenient_mode)
        
        # 프록시 테스트 결과 처리 후 즉시 정지 상태 확인
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 프록시 테스트 결과 처리 중 정지됨: {req.id}")
            return None, None
        
        if working_proxies:
            print(f"[LOG] 배치 {batch_num}에서 {len(working_proxies)}개 프록시 확보")
            # 실패한 프록시들을 사용됨으로 표시
            for failed_proxy in failed_proxies:
                mark_proxy_used(db, failed_proxy, success=False)
            break
        else:
            print(f"[LOG] 배치 {batch_num} 실패 - 다음 배치로 이동")
            # 실패한 프록시들을 사용됨으로 표시
            for failed_proxy in failed_proxies:
                mark_proxy_used(db, failed_proxy, success=False)
            proxy_index += batch_size
            
            # 배치 간 지연 (차단 방지용)
            print(f"[LOG] 배치 간 지연 (차단 방지): 2초 대기")
            time.sleep(2)
            continue
    
    if not working_proxies:
        print(f"[LOG] 모든 프록시를 소진했지만 작동하는 프록시를 찾지 못함")
        return None, None
    
    print(f"[LOG] {len(working_proxies)}개의 검증된 프록시로 파싱 시도")
    
    # 성공한 프록시들을 순차적으로 시도 (각각 1회씩만)
    for i, working_proxy in enumerate(working_proxies):
        print(f"[LOG] 검증된 프록시로 파싱 시도 {i+1}/{len(working_proxies)}: {working_proxy}")
        
        # 정지 상태 체크
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 프록시 파싱 중 정지됨: {req.id}")
            return None, None
        
        try:
            # SSE로 프록시 시도 중 알림 (상세)
            send_sse_message("proxy_trying", {
                "id": req.id,
                "proxy": working_proxy,
                "step": "파싱 중 (검증됨)",
                "current": i + 1,
                "total": len(working_proxies),
                "url": req.url
            })
            
            # 상태 업데이트도 함께 (활성 다운로드 중이 아닐 때만)
            if not download_manager.is_download_active(req.id):
                send_sse_message("status_update", {
                    "id": req.id,
                    "status": "parsing",
                    "message": get_message("proxy_verified_parsing").format(current=i + 1, total=len(working_proxies)),
                    "progress": int((req.downloaded_size / req.total_size * 100) if req.total_size > 0 and req.downloaded_size > 0 else 0),
                    "url": req.url
                })
            
            # 프록시로 파싱 시도 (재시도 없이 1회만) - 파일 정보도 함께 추출
            try:
                print(f"[LOG] 프록시 {working_proxy}로 1회 파싱 시도")
                direct_link, file_info = parse_direct_link_with_file_info(
                    req.url, 
                    req.password, 
                    use_proxy=True, 
                    proxy_addr=working_proxy
                )
                
                # 파일 정보가 추출되면 DB에 저장 (기존 파일명이 없거나 빈 문자열인 경우)
                if file_info and file_info['name'] and (not req.file_name or req.file_name.strip() == ''):
                    req.file_name = file_info['name']
                    print(f"[LOG] 프록시 모드에서 파일명 추출: {file_info['name']}")
                    db.commit()
                    
                    # SSE로 파일명 업데이트 전송
                    send_sse_message("filename_update", {
                        "id": req.id,
                        "file_name": req.file_name,
                        "url": req.url,
                        "status": req.status.value if hasattr(req.status, 'value') else str(req.status)
                    })
            except Exception as e:
                error_msg = str(e)
                # 카운트다운 제한인 경우 프록시 문제가 아님
                if "카운트다운 감지" in error_msg or "countdown" in error_msg.lower():
                    print(f"[LOG] 프록시에서 카운트다운 감지 - 다른 프록시들도 동일할 가능성 높음")
                    # 카운트다운 정보 추출
                    import re
                    countdown_match = re.search(r'(\d+)초', error_msg)
                    if countdown_match:
                        countdown_seconds = int(countdown_match.group(1))
                        print(f"[LOG] 모든 프록시에서 {countdown_seconds}초 대기 예상")
                    raise e  # 카운트다운은 재발생시켜서 상위에서 처리
                else:
                    raise e  # 다른 에러는 그대로 전파
            
            if direct_link:
                print(f"[LOG] 검증된 프록시로 파싱 성공: {working_proxy}")
                mark_proxy_used(db, working_proxy, success=True)
                
                # 즉시 정지 체크 - 파싱 완료 후 상태 변경 전에
                if download_manager.is_download_stopped(req.id):
                    print(f"[LOG] 파싱 완료 후 즉시 정지 플래그 감지: ID {req.id}")
                    return result
                
                # 파싱 완료, 프록시 연결 상태로 전환
                req.status = StatusEnum.proxying
                db.commit()
                
                # 즉시 정지 체크 - WebSocket 메시지 전송 전에
                if download_manager.is_download_stopped(req.id):
                    print(f"[LOG] 파싱 완료 WebSocket 전송 전 즉시 정지 플래그 감지: ID {req.id}")
                    return result
                
                # 파싱 완료 후 다운로드 준비 단계의 진행률 (새 다운로드는 낮은 진행률 유지)
                if req.total_size > 0 and req.downloaded_size > 0:
                    # 이어받기인 경우 실제 진행률 사용
                    parsing_complete_progress = max(15, (req.downloaded_size / req.total_size) * 100)
                else:
                    # 새 다운로드인 경우 낮은 진행률 유지
                    parsing_complete_progress = 15
                
                send_sse_message("status_update", {
                    "id": req.id,
                    "status": "proxying",
                    "message": get_message("download_proxying") + f" ({working_proxy})",
                    "progress": parsing_complete_progress,
                    "url": req.url
                })
                
                return direct_link, working_proxy
                
        except Exception as e:
            print(f"[LOG] 검증된 프록시 파싱 실패 - {working_proxy}: {e}")
            mark_proxy_used(db, working_proxy, success=False)
    
    # 검증된 프록시가 없거나 실패한 경우 전체 프록시로 폴백
    unused_proxies = get_unused_proxies(db)
    
    if not unused_proxies:
        print(f"[LOG] 사용 가능한 프록시가 없음")
        return None, None
    
    print(f"[LOG] {len(unused_proxies)}개 프록시로 파싱 시도 (폴백)")
    
    for i, proxy_addr in enumerate(unused_proxies):
        # 매 프록시 시도마다 정지 상태 체크 (즉시 정지 플래그 + DB 상태)
        if download_manager.is_download_stopped(req.id):
            print(f"[LOG] 프록시 파싱 중 즉시 정지 플래그 감지: {req.id}")
            return None, None
        
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 프록시 파싱 중 정지됨: {req.id}")
            return None, None
        
        try:
            # print(f"[LOG] 파싱 시도 {i+1}/{len(unused_proxies)}: {proxy_addr}")
            
            # SSE로 프록시 시도 중 알림
            send_sse_message("proxy_trying", {
                "id": req.id,
                "proxy": proxy_addr,
                "step": "파싱 중",
                "current": i + 1,
                "total": len(unused_proxies),
                "url": req.url
            })
            
            # 프록시로 파싱 시도 (카운트다운 감지) - 파일 정보도 함께 추출
            try:
                direct_link, file_info = parse_direct_link_with_file_info(
                    req.url, 
                    req.password, 
                    use_proxy=True, 
                    proxy_addr=proxy_addr
                )
                
                # 파일 정보가 추출되면 DB에 저장 (기존 파일명이 없거나 빈 문자열인 경우)
                if file_info and file_info['name'] and (not req.file_name or req.file_name.strip() == ''):
                    req.file_name = file_info['name']
                    print(f"[LOG] 프록시 모드에서 파일명 추출: {file_info['name']}")
                    db.commit()
                    
                    # SSE로 파일명 업데이트 전송
                    send_sse_message("filename_update", {
                        "id": req.id,
                        "file_name": req.file_name,
                        "url": req.url,
                        "status": req.status.value if hasattr(req.status, 'value') else str(req.status)
                    })
            except Exception as e:
                error_msg = str(e)
                # 카운트다운 제한인 경우 모든 프록시에서 동일할 것
                if "카운트다운 감지" in error_msg or "countdown" in error_msg.lower():
                    print(f"[LOG] 프록시 {proxy_addr}에서 카운트다운 감지 - 프록시 순환 중단")
                    # 카운트다운은 전체적인 사이트 제한이므로 다른 프록시 시도 중단
                    raise e
                else:
                    # 일반적인 프록시 오류는 계속 진행
                    raise e
            
            # 파싱 완료 후 정지 상태 체크
            db.refresh(req)
            if req.status == StatusEnum.stopped:
                print(f"[LOG] 프록시 파싱 완료 후 정지됨: {req.id}")
                return None, None
            
            if direct_link:
                print(f"[LOG] 파싱 성공 - 프록시: {proxy_addr}")
                mark_proxy_used(db, proxy_addr, success=True)
                
                # SSE로 프록시 성공 알림
                send_sse_message("proxy_success", {
                    "proxy": proxy_addr,
                    "step": "파싱 완료",
                    "url": req.url
                })
                
                return direct_link, proxy_addr
                
        except (httpx.ConnectTimeout, 
                httpx.ReadTimeout, 
                httpx.TimeoutException, 
                httpx.ProxyError) as e:
            
            print(f"[LOG] 파싱 실패 - 프록시 {proxy_addr}: {e}")
            mark_proxy_used(db, proxy_addr, success=False)
            
            # SSE로 프록시 실패 알림
            send_sse_message("proxy_failed", {
                "proxy": proxy_addr,
                "step": "파싱 실패",
                "error": str(e),
                "url": req.url
            })
            
            continue
            
        except Exception as e:
            print(f"[LOG] 파싱 오류 - 프록시 {proxy_addr}: {e}")
            mark_proxy_used(db, proxy_addr, success=False)
            
            # SSE로 프록시 실패 알림
            send_sse_message("proxy_failed", {
                "proxy": proxy_addr,
                "step": "파싱 오류",
                "error": str(e),
                "url": req.url
            })
            
            continue
    
    print(f"[LOG] 모든 프록시에서 파싱 실패")
    return None, None


async def download_from_stream(proxy_addr, file_path, initial_size, req, db, use_proxy):
    """직접 다운로드 스트림에서 파일 다운로드"""
    print(f"[LOG] 직접 스트림 다운로드 시작 (프록시: {proxy_addr})")
    
    # 스트림 다운로드는 parser_service에서 이미 시작되었으므로
    # 여기서는 재시도 메커니즘을 구현
    try:
        # 새로운 요청으로 다운로드 재시작
        
        if use_proxy and proxy_addr:
            # 프록시 사용하여 다운로드 재시작
            print(f"[LOG] 프록시 {proxy_addr}로 스트림 다운로드 재시작")
            await download_with_proxy("STREAM_RETRY", file_path, proxy_addr, initial_size, req, db)
        else:
            # 로컬 연결로 다운로드 재시작
            print(f"[LOG] 로컬 연결로 스트림 다운로드 재시작")
            await download_local("STREAM_RETRY", file_path, initial_size, req, db)
            
    except Exception as e:
        print(f"[LOG] 스트림 다운로드 실패: {e}")
        raise e


def cleanup_download_file(file_path):
    """다운로드 완료 후 파일 정리 - .part 확장자 제거"""
    try:
        file_path_str = str(file_path)
        
        if file_path_str.endswith('.part'):
            final_path = file_path_str[:-5]  # .part 제거
            print(f"[LOG] .part 파일을 최종 파일명으로 변경: {file_path} -> {final_path}")
            
            # 파일 크기 확인
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                print(f"[LOG] 최종 파일 크기: {file_size} bytes")
                
                # 파일이 매우 작거나 빈 경우 내용 검증
                if file_size < 1024:
                    print(f"[LOG] 작은 파일 검증 중... ({file_size} bytes)")
                    try:
                        with open(file_path, 'rb') as f:
                            content = f.read(500)
                            try:
                                text_content = content.decode('utf-8', errors='ignore').lower()
                                error_indicators = ['<html', '<body', 'error', '404', '403', 'not found']
                                if any(indicator in text_content for indicator in error_indicators):
                                    print(f"[LOG] 에러 파일 감지 - 삭제함: {text_content[:100]}...")
                                    os.remove(file_path)
                                    raise Exception(f"다운로드 실패 - 에러 페이지 받음 ({file_size} bytes)")
                            except UnicodeDecodeError:
                                # 바이너리 파일인 경우 통과
                                pass
                    except Exception as e:
                        if "에러 페이지" in str(e):
                            raise e  # 에러 페이지인 경우 예외 전파
                        pass  # 기타 파일 읽기 에러는 무시
                
                # .part 확장자 제거하여 최종 파일명으로 변경
                if os.path.exists(final_path):
                    # 중복 파일 처리
                    counter = 1
                    base_name, ext = os.path.splitext(final_path)
                    while os.path.exists(f"{base_name}_{counter}{ext}"):
                        counter += 1
                    final_path = f"{base_name}_{counter}{ext}"
                    print(f"[LOG] 중복 파일 방지: {final_path}")
                
                os.rename(file_path, final_path)
                print(f"[LOG] 파일명 정리 완료: {final_path}")
                return final_path
            else:
                print(f"[LOG] 파일이 존재하지 않음: {file_path}")
                return None
        else:
            print(f"[LOG] .part 확장자가 아닌 파일은 그대로 유지: {file_path}")
            return file_path
    except Exception as e:
        print(f"[LOG] 파일 정리 실패: {e}")
        raise e


async def download_general_file(request_id, language="ko", use_proxy=False):
    """일반 파일 다운로드 (non-1fichier) - URL에서 직접 다운로드 (비동기)"""
    from .models import DownloadRequest, StatusEnum

    db = SessionLocal()
    req = None

    # 최상위 예외 경계 - 어떤 오류도 프로세스를 죽이지 않음
    try:
        # 다운로드 요청 조회
        req = db.query(DownloadRequest).filter(DownloadRequest.id == request_id).first()
        if not req:
            print(f"[LOG] 일반 다운로드 요청을 찾을 수 없음: {request_id}")
            return
        
        # 즉시 정지 플래그만 초기화 (일반 파일은 제한 없으므로 바로 등록)
        with download_manager._lock:
            download_manager.stop_events[request_id] = threading.Event()
        
        download_manager.register_download(request_id, req.url, use_proxy)
        print(f"[LOG] 일반 다운로드 {request_id} 등록 완료 - 즉시 정지 플래그 초기화됨")
        
        print(f"[LOG] 일반 다운로드 시작: {req.url}")
        
        # 먼저 HEAD 요청으로 파일 정보 확인 (파일명 생성 전)
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            async with httpx.AsyncClient(follow_redirects=True) as client:
                head_response = await client.head(req.url, headers=headers, timeout=30)
            if head_response.status_code == 200:
                # Content-Type 체크 - 다운로드 가능한 파일인지 먼저 확인
                content_type = head_response.headers.get('Content-Type', '').lower()
                
                # HTML 페이지나 일반 웹페이지는 다운로드하지 않음 (파일명 생성 전에 차단)
                if any(web_type in content_type for web_type in ['text/html', 'text/xml', 'application/json', 'text/plain']):
                    print(f"[LOG] 웹페이지 Content-Type 감지: {content_type} - 다운로드 불가")
                    req.status = StatusEnum.failed
                    req.error_message = f"웹페이지는 다운로드할 수 없습니다. (Content-Type: {content_type})"
                    db.commit()
                    return
                
                print(f"[LOG] 다운로드 가능한 Content-Type: {content_type}")
                
            else:
                print(f"[LOG] HEAD 요청 실패: {head_response.status_code}")
                req.status = StatusEnum.failed
                req.error_message = f"서버 응답 오류: {head_response.status_code}"
                db.commit()
                return
                
        except Exception as head_e:
            print(f"[LOG] HEAD 요청 중 오류: {head_e}")
            req.status = StatusEnum.failed
            req.error_message = f"HEAD 요청 실패: {str(head_e)}"
            db.commit()
            return
        
        # Content-Type 확인 후 파일명 생성
        # URL에서 파일명 추출
        parsed_url = urlparse(req.url)
        if parsed_url.path and '/' in parsed_url.path:
            url_filename = unquote(parsed_url.path.split('/')[-1])
            if url_filename and len(url_filename) > 3 and '.' in url_filename:
                print(f"[LOG] URL에서 파일명 추출: '{url_filename}'")
                req.file_name = url_filename
                db.commit()
        
        # Content-Disposition에서 파일명 재추출 시도
        content_disposition = head_response.headers.get('Content-Disposition')
        if content_disposition and 'filename=' in content_disposition:
            filename_match = re.search(r'filename[*]?=(?:UTF-8\'\')?["\']?([^"\';]+)["\']?', content_disposition, re.IGNORECASE)
            if filename_match:
                extracted_filename = unquote(filename_match.group(1))
                req.file_name = extracted_filename
                print(f"[LOG] Content-Disposition에서 파일명 추출: '{extracted_filename}'")
                db.commit()
                
                # SSE로 파일명 업데이트 즉시 전송
                await sse_manager.broadcast_message("status_update", {
                    "id": req.id,
                    "file_name": req.file_name,
                    "url": req.url,
                    "status": req.status.value if hasattr(req.status, 'value') else str(req.status),
                    "file_size": req.file_size,
                    "total_size": req.total_size or 0
                })
        
        # 파일명이 없으면 임시명 설정
        if not req.file_name or req.file_name.strip() == '':
            req.file_name = f"general_{request_id}.tmp"
            print(f"[LOG] 파일명을 추출할 수 없어 임시명 사용: {req.file_name}")
            db.commit()
            
        # Content-Length에서 파일 크기 추출
        content_length = head_response.headers.get('Content-Length')
        if content_length:
            bytes_size = int(content_length)
            
            # 1fichier처럼 포맷팅된 크기를 문자열로 저장
            formatted_size = format_file_size(bytes_size)
            req.file_size = formatted_size
            req.total_size = bytes_size  # total_size도 설정
            print(f"[LOG] ★ 파일크기 최초 설정: '{formatted_size}' ({content_length} bytes)")
        
        # 상태를 다운로드 중으로 변경
        req.status = StatusEnum.downloading
        db.commit()
        
        # 텔레그램 다운로드 시작 알림 전송 (일반 다운로드)
        try:
            download_mode = "proxy" if use_proxy else "local"
            # 파일크기 - DB의 file_size 우선, 없으면 total_size 사용
            file_size_str = None
            if req.file_size and req.file_size.strip():
                file_size_str = req.file_size  # DB에서 파싱된 파일크기 우선 사용
            elif req.total_size and req.total_size > 0:
                file_size_str = format_file_size(req.total_size)
            
            print(f"[DEBUG] 일반 다운로드 텔레그램 알림 - total_size: {req.total_size}, file_size_str: {file_size_str}")
            
            send_telegram_start_notification(
                file_name=req.file_name or "Unknown File",
                download_mode=download_mode,
                lang=language,
                file_size=file_size_str,
                requested_at=req.requested_at
            )
        except Exception as e:
            print(f"[LOG] 텔레그램 시작 알림 전송 실패 (일반): {e}")
        
        # SSE로 상태 업데이트 알림
        send_sse_message("status_update", {
            "id": req.id,
            "url": req.url,
            "file_name": req.file_name,
            "file_size": req.file_size,
            "status": "downloading",
            "error": None,
            "progress": 0,
            "downloaded_size": 0,
            "total_size": 0, # 실제 크기는 다운로드 시작 시 업데이트됨
            "save_path": None,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "finished_at": None,
            "password": req.password,
            "direct_link": None,
            "use_proxy": req.use_proxy
        })
        
        # 다운로드 경로 설정
        download_path = get_download_path()
        
        # Windows에서 파일명에 사용할 수 없는 문자 제거
        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', req.file_name.strip())
        safe_filename = safe_filename.strip('. ')
        
        if not safe_filename:
            safe_filename = f"general_{request_id}.unknown"
            
        # 중복 파일명 방지
        final_path = download_path / safe_filename
        counter = 1
        while final_path.exists():
            name, ext = os.path.splitext(safe_filename)
            safe_filename = f"{name}_{counter}{ext}"
            final_path = download_path / safe_filename
            counter += 1
            
        file_path = final_path
        part_file_path = download_path / (safe_filename + ".part")
        
        # DB에 저장 경로 업데이트
        req.save_path = str(file_path)
        db.commit()
        print(f"[LOG] 저장 경로 설정: {file_path}")
        
        # SSE로 저장 경로 업데이트 전송
        send_sse_message("status_update", {
            "id": req.id,
            "url": req.url,
            "file_name": req.file_name,
            "status": req.status.value if hasattr(req.status, 'value') else str(req.status),
            "save_path": req.save_path,
            "total_size": req.total_size or 0,
            "downloaded_size": req.downloaded_size or 0,
            "use_proxy": req.use_proxy
        })
        
        # 기존 파일 확인 (일반 파일 다운로드)
        initial_size = 0
        if part_file_path.exists():
            file_path = part_file_path
            initial_size = part_file_path.stat().st_size
            print(f"[LOG] 기존 미완료 파일 발견 - 이어받기: {initial_size} bytes")
        elif file_path.exists():
            initial_size = file_path.stat().st_size
            # 완전히 다운로드된 파일이면 100% 완료 처리하고 종료
            print(f"[LOG] 기존 완료 파일 발견: {initial_size} bytes - 완료 처리")
            req.status = StatusEnum.done
            req.downloaded_size = initial_size
            req.total_size = initial_size
            req.finished_at = datetime.datetime.utcnow()
            db.commit()
            
            # SSE로 완료 알림
            send_sse_message("status_update", {
                "id": req.id,
                "status": "done", 
                "progress": 100.0,
                "downloaded_size": initial_size,
                "total_size": initial_size,
                "message": "기존 완료 파일 발견 - 완료 처리됨"
            })
            return  # 다운로드 종료
        else:
            file_path = part_file_path
            print(f"[LOG] 새 다운로드 시작")
        
        # 정지 상태 체크 (다운로드 시작 전)
        if download_manager.is_download_stopped(request_id):
            print(f"[LOG] 일반 다운로드 시작 전 정지 플래그 감지: ID {request_id}")
            return
            
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 일반 다운로드 시작 전 정지 상태 감지: ID {request_id}")
            return

        # 다운로드 상태로 변경 및 SSE 전송
        req.status = StatusEnum.downloading
        db.commit()
        
        send_sse_message("status_update", {
            "id": req.id,
            "url": req.url,
            "file_name": req.file_name,
            "status": "downloading",
            "save_path": req.save_path,
            "total_size": req.total_size or 0,
            "downloaded_size": req.downloaded_size or 0,
            "progress": 0.0,
            "use_proxy": req.use_proxy
        })

        # 실제 다운로드는 기존 다운로드 로직 재사용
        if use_proxy:
            print(f"[LOG] 프록시 모드로 일반 파일 다운로드")
            await download_with_proxy_cycling(req.url, file_path, None, initial_size, req, db)
        else:
            print(f"[LOG] 로컬 모드로 일반 파일 다운로드")
            await download_local(req.url, file_path, initial_size, req, db)
            
        # 3단계: 완료 처리
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 정지됨 (완료 처리 전): ID {request_id}")
            return

        final_file_path = cleanup_download_file(file_path)

        req.status = StatusEnum.done
        req.finished_at = datetime.datetime.utcnow()
        if final_file_path:
            req.save_path = str(final_file_path)
        db.commit()

        # 텔레그램 알림 전송 (완료)
        unknown_file = get_translations(language).get("telegram_unknown_file", "알 수 없는 파일")
        
        # 파일 크기 포맷팅 (1fichier와 동일한 방식)
        file_size_str = "알 수 없음"
        if req.total_size:
            file_size_str = format_file_size(req.total_size)
        elif req.file_size:
            file_size_str = req.file_size
        
        download_time_str = None
        if req.finished_at:
            if language == "ko":
                # 한국어일 때만 KST로 변환
                kst_finished = req.finished_at + datetime.timedelta(hours=9)
                download_time_str = kst_finished.strftime("%Y-%m-%d %H:%M:%S")
            else:
                # 영어 등 다른 언어는 UTC 그대로 표시
                download_time_str = req.finished_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # 저장 경로 (언어별 기본값)
        if language == "ko":
            save_path_str = req.save_path or "기본경로"
        else:
            save_path_str = req.save_path or "Default path"
        
        send_telegram_notification(
            req.file_name or unknown_file, 
            "done", 
            None, 
            language,
            file_size=file_size_str,
            download_time=download_time_str,
            save_path=save_path_str
        )
        
        # SSE로 완료 상태 전송
        send_sse_message("status_update", {
            "id": req.id,
            "url": req.url,
            "file_name": req.file_name,
            "status": "done",
            "error": None,
            "downloaded_size": req.downloaded_size or 0,
            "total_size": req.total_size or 0,
            "progress": 100.0,
            "save_path": req.save_path,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "finished_at": req.finished_at.isoformat() if req.finished_at else None,
            "password": req.password,
            "direct_link": None,  # direct_link 필드 제거됨
            "use_proxy": req.use_proxy
        })
        
        # 다운로드 완료 - 매니저에서 해제하여 다음 큐 자동 시작 (일반 파일)
        download_manager.unregister_download(request_id, is_completed=True, auto_start_next=True)
        print(f"[LOG] 일반 다운로드 완료: {req.file_name} - 다음 큐 자동 시작")
            
    except Exception as e:
        print(f"[LOG] 일반 다운로드 중 오류: {e}")
        try:
            if req:
                req.status = StatusEnum.failed
                req.error_message = str(e)
                db.commit()
                
                # SSE로 실패 상태 전송
                send_sse_message("status_update", {
                    "id": req.id,
                    "url": req.url,
                    "file_name": req.file_name,
                    "status": "failed",
                    "error": str(e),
                    "downloaded_size": req.downloaded_size or 0,
                    "total_size": req.total_size or 0,
                    "progress": 0.0
                })
        except Exception as update_error:
            print(f"[ERROR] 다운로드 실패 상태 업데이트 중 오류: {update_error}")
        
        # 예외를 전파하지 않고 여기서 처리 완료
    finally:
        # 다운로드 종료 시 항상 매니저에서 해제하여 다음 큐가 진행되도록 보장
        try:
            if req:
                db.refresh(req) # 최신 상태 확인
                is_completed = (req.status == StatusEnum.done)
                download_manager.unregister_download(request_id, is_completed=is_completed, auto_start_next=True)
                print(f"[LOG] 일반 다운로드 스레드 종료 - 매니저에서 해제: ID {request_id}, 완료: {is_completed}")
        except Exception as final_e:
            print(f"[ERROR] 다운로드 해제 최종 단계에서 오류 발생: {final_e}")
        
        db.close()

class DownloadManager:
    def __init__(self):
        self.active_downloads = {}  # {download_id: Thread}
        self.local_downloads = set()  # 로컬 다운로드 ID 집합 (1fichier만)
        self.all_downloads = set()  # 전체 다운로드 ID 집합 (모든 도메인)
        self.MAX_LOCAL_DOWNLOADS = 1  # 최대 로컬 다운로드 수 (1fichier만)
        self.MAX_TOTAL_DOWNLOADS = 5  # 최대 전체 동시 다운로드 수
        
        # 1fichier 다운로드 쿨다운 관리
        self.last_1fichier_completion_time = 0  # 마지막 1fichier 다운로드 완료 시간
        self.FICHIER_COOLDOWN_SECONDS = 5  # 1fichier 다운로드 간 대기 시간 (초) - 서버 연결 안정성 확보
        
        # 전역 정지 플래그 시스템 (안전한 즉시 정지)
        self.stop_events = {}  # {download_id: threading.Event}
        
        # 스레드 안전성을 위한 락
        self._lock = threading.Lock()
        
        # 서버 시작 시간 기록 (재시작 복구 판단용)
        self._server_start_time = time.time()
        
        # DB 쿼리 캐시 (부하 감소)
        self._last_check_time = 0
        self._check_interval = 5.0  # 5초 간격으로 DB 체크 (적절한 반응성과 성능 균형)
        
        # 쿨다운 타이머 중복 생성 방지
        self._cooldown_timer_running = False
    
    @property
    def download_stop_events(self):
        """하위 호환성을 위한 별칭 속성"""
        return self.stop_events

    def can_start_download(self, url=None):
        """다운로드를 시작할 수 있는지 확인 (전체 제한 + 1fichier 개별 제한 + 쿨다운)"""
        with self._lock:
            # 전체 다운로드 수 체크
            print(f"[LOG] can_start_download 체크 - 전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS}, 로컬: {len(self.local_downloads)}/{self.MAX_LOCAL_DOWNLOADS}")
            if len(self.all_downloads) >= self.MAX_TOTAL_DOWNLOADS:
                print(f"[LOG] 전체 다운로드 제한으로 시작 불가 ({self.MAX_TOTAL_DOWNLOADS}개)")
                return False
            
            # 1fichier인 경우 개별 제한도 체크
            if url and '1fichier.com' in url:
                if len(self.local_downloads) >= self.MAX_LOCAL_DOWNLOADS:
                    print(f"[LOG] 1fichier 로컬 다운로드 제한으로 시작 불가 ({self.MAX_LOCAL_DOWNLOADS}개)")
                    return False
                
                # 1fichier 로컬 다운로드 실행중이거나 대기 중인 것이 있는지 체크 (downloading/proxying/parsing 상태, 로컬만)
                db = None
                try:
                    db = next(get_db())
                    active_local_fichier = db.query(DownloadRequest).filter(
                        DownloadRequest.status.in_([StatusEnum.downloading, StatusEnum.proxying, StatusEnum.parsing]),
                        DownloadRequest.url.contains('1fichier.com'),
                        DownloadRequest.use_proxy == False  # 로컬 다운로드만 체크
                    ).first()
                    if active_local_fichier:
                        print(f"[LOG] 1fichier 로컬 다운로드 실행/대기중 있음: ID {active_local_fichier.id}, 상태: {active_local_fichier.status}")
                        return False
                except Exception as e:
                    print(f"[LOG] 1fichier 대기 상태 체크 실패: {e}")
                finally:
                    if db:
                        try:
                            db.close()
                        except:
                            pass
                
                # 1fichier 쿨다운 시간 체크
                current_time = time.time()
                if self.last_1fichier_completion_time > 0:
                    time_since_completion = current_time - self.last_1fichier_completion_time
                    if time_since_completion < self.FICHIER_COOLDOWN_SECONDS:
                        remaining_time = self.FICHIER_COOLDOWN_SECONDS - time_since_completion
                        print(f"[LOG] 1fichier 쿨다운 중. 남은 시간: {remaining_time:.1f}초")
                        return False
            
            return True
    
    def get_1fichier_cooldown_remaining(self):
        """1fichier 쿨다운 남은 시간 반환 (초)"""
        with self._lock:
            if self.last_1fichier_completion_time == 0:
                return 0
            
            current_time = time.time()
            time_since_completion = current_time - self.last_1fichier_completion_time
            
            if time_since_completion >= self.FICHIER_COOLDOWN_SECONDS:
                return 0
            
            return self.FICHIER_COOLDOWN_SECONDS - time_since_completion
    
    def _send_cooldown_updates(self, db):
        """1fichier 쿨다운 중인 대기 다운로드들에 쿨다운 상태 메시지 전송"""
        try:
            cooldown_remaining = self.get_1fichier_cooldown_remaining()
            if cooldown_remaining <= 0:
                return
            
            # 1fichier 로컬 다운로드 중에서 다음에 실행될 1개만 찾기 (가장 먼저 요청된 것)
            next_fichier_download = db.query(DownloadRequest).filter(
                DownloadRequest.status == StatusEnum.pending,
                DownloadRequest.use_proxy == False,
                DownloadRequest.url.contains('1fichier.com')
            ).order_by(DownloadRequest.requested_at.asc()).first()
            
            if next_fichier_download:
                import json
                cooldown_message = f"1fichier 쿨다운 대기 중: {int(cooldown_remaining)}초 남음"
                
                # DB에서 다운로드 상태를 cooldown으로 변경 (처음 한 번만)
                if next_fichier_download.status != StatusEnum.cooldown:
                    next_fichier_download.status = StatusEnum.cooldown
                    db.commit()
                
                # 다음에 실행될 1fichier 다운로드에만 쿨다운 상태 전송
                cooldown_data = {
                    "type": "status_update",
                    "data": {
                        "id": next_fichier_download.id,
                        "status": "cooldown",
                        "message": cooldown_message,
                        "cooldown_remaining": int(cooldown_remaining)
                    }
                }
                print(f"[LOG] 🕐 쿨다운 메시지 생성: ID={next_fichier_download.id}, 남은시간={int(cooldown_remaining)}초")
                print(f"[LOG] 🔄 쿨다운 메시지 내용: {json.dumps(cooldown_data)}")
                safe_status_queue_put(json.dumps(cooldown_data))
                
                print(f"[LOG] 다음 1fichier 다운로드 ID {next_fichier_download.id}에 쿨다운 상태 전송: {int(cooldown_remaining)}초 남음")
        except Exception as e:
            print(f"[LOG] 쿨다운 상태 전송 실패: {e}")
    
    def check_immediate_cooldown(self, download_id):
        """새 다운로드 추가 시 즉시 쿨다운 상태 확인 및 설정"""
        try:
            cooldown_remaining = self.get_1fichier_cooldown_remaining()
            if cooldown_remaining <= 0:
                return False  # 쿨다운 없음
            
            db = next(get_db())
            
            # 해당 다운로드가 1fichier 로컬 다운로드인지 확인
            download_req = db.query(DownloadRequest).filter(
                DownloadRequest.id == download_id,
                DownloadRequest.use_proxy == False,
                DownloadRequest.url.contains('1fichier.com')
            ).first()
            
            if download_req and download_req.status == StatusEnum.pending:
                # 즉시 쿨다운 상태로 변경
                download_req.status = StatusEnum.cooldown
                db.commit()
                
                import json
                cooldown_message = f"1fichier 쿨다운 대기 중: {int(cooldown_remaining)}초 남음"
                cooldown_data = {
                    "type": "status_update",
                    "data": {
                        "id": download_id,
                        "status": "cooldown",
                        "message": cooldown_message,
                        "cooldown_remaining": int(cooldown_remaining)
                    }
                }
                print(f"[LOG] 🕐 즉시 쿨다운 메시지 생성: ID={download_id}, 남은시간={int(cooldown_remaining)}초")
                safe_status_queue_put(json.dumps(cooldown_data))
                
                print(f"[LOG] 즉시 쿨다운 설정: ID {download_id}, {int(cooldown_remaining)}초 남음")
                
                # 쿨다운 타이머가 실행 중이 아니면 시작
                if not hasattr(self, '_cooldown_timer_running') or not self._cooldown_timer_running:
                    self._start_cooldown_timer()
                
                return True
            
            db.close()
            return False
            
        except Exception as e:
            print(f"[LOG] 즉시 쿨다운 확인 실패: {e}")
            return False
    
    def _start_cooldown_timer(self):
        """1fichier 쿨다운 타이머 시작 - 주기적으로 대기중인 다운로드들에 상태 업데이트"""
        # 이미 실행 중인 타이머가 있으면 중복 생성 방지
        with self._lock:
            if self._cooldown_timer_running:
                print("[LOG] 쿨다운 타이머 이미 실행 중 - 중복 생성 방지")
                return
            self._cooldown_timer_running = True
        
        def cooldown_timer():
            try:
                cooldown_duration = self.FICHIER_COOLDOWN_SECONDS
                update_interval = 2  # 2초마다 업데이트 (실시간성 향상)
                
                for elapsed in range(0, cooldown_duration, update_interval):
                    remaining = cooldown_duration - elapsed
                    
                    # 대기 중인 1fichier 다운로드들에 쿨다운 상태 전송 (매번 업데이트)
                    db = None
                    try:
                        db = next(get_db())
                        self._send_cooldown_updates(db)
                    except Exception as e:
                        print(f"[LOG] 쿨다운 타이머 업데이트 실패: {e}")
                    finally:
                        if db:
                            try:
                                db.close()
                            except:
                                pass
                    
                    # 쿨다운이 끝나기 전까지 대기
                    time.sleep(min(update_interval, remaining))
                    
                    # 쿨다운이 끝났으면 종료
                    if remaining <= update_interval:
                        break
                
                print(f"[LOG] 1fichier 쿨다운 타이머 완료")
                
                # 쿨다운 완료 후 대기 중인 다운로드 체크
                self.check_and_start_waiting_downloads()
                
            except Exception as e:
                print(f"[LOG] 쿨다운 타이머 중 오류: {e}")
            finally:
                # 타이머 종료 시 플래그 초기화 (메모리 누수 방지)
                with self._lock:
                    self._cooldown_timer_running = False
                print("[LOG] 쿨다운 타이머 종료 - 플래그 초기화")
        
        # 백그라운드에서 쿨다운 타이머 실행
        threading.Thread(target=cooldown_timer, daemon=True).start()
    
    def can_start_local_download(self, url=None):
        """로컬 다운로드를 시작할 수 있는지 확인 (1fichier만 제한) - 하위 호환성"""
        return self.can_start_download(url)
    
    def start_download(self, download_id, func, *args, **kwargs):
        self.cancel_download(download_id)
        with self._lock:
            t = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
            t.start()
            self.active_downloads[download_id] = t
    
    def register_download(self, download_id, url=None, use_proxy=False):
        """다운로드 등록 (전체 + 1fichier 개별) - 중복 등록 방지"""
        with self._lock:
            # 이미 등록된 경우 건너뛰기
            if download_id in self.all_downloads:
                print(f"[LOG] ⚠️ 다운로드 {download_id} 이미 등록됨 - 중복 등록 방지")
                return
            
            # 모든 다운로드 등록
            self.all_downloads.add(download_id)
            
            # 정지 플래그 초기화 (없는 경우만)
            if download_id not in self.stop_events:
                self.stop_events[download_id] = threading.Event()
            
            # 1fichier이고 로컬 다운로드인 경우만 별도 등록
            if url and '1fichier.com' in url and not use_proxy:
                self.local_downloads.add(download_id)
                print(f"[LOG] 1fichier 로컬 다운로드 등록: {download_id} (1fichier: {len(self.local_downloads)}/{self.MAX_LOCAL_DOWNLOADS}, 전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS})")
            else:
                proxy_type = "프록시" if use_proxy else "일반"
                print(f"[LOG] {proxy_type} 다운로드 등록: {download_id} (전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS})")
    
    def register_local_download(self, download_id, url=None):
        """로컬 다운로드 등록 - 하위 호환성"""
        self.register_download(download_id, url)
    
    def unregister_download(self, download_id, is_completed=False, auto_start_next=True):
        """다운로드 해제 (전체 + 1fichier 개별)"""
        was_fichier = False
        with self._lock:
            # 전체 다운로드에서 해제
            self.all_downloads.discard(download_id)
            
            # 정지 플래그 정리
            if download_id in self.stop_events:
                del self.stop_events[download_id]
            
            # 1fichier 다운로드에서 해제
            was_fichier = download_id in self.local_downloads
            if was_fichier:
                self.local_downloads.discard(download_id)
                print(f"[LOG] 1fichier 다운로드 해제: {download_id} (1fichier: {len(self.local_downloads)}/{self.MAX_LOCAL_DOWNLOADS}, 전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS})")
                
                # 1fichier 다운로드가 성공적으로 완료된 경우 쿨다운 시작
                if is_completed:
                    self.last_1fichier_completion_time = time.time()
                    print(f"[LOG] 1fichier 다운로드 완료. 쿨다운 {self.FICHIER_COOLDOWN_SECONDS}초 시작")
                    # 쿨다운 타이머 시작
                    self._start_cooldown_timer()
            else:
                print(f"[LOG] 다운로드 해제: {download_id} (전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS})")
        
        # 락 외부에서 대기 중인 다운로드 체크 (데드락 방지)
        # 다운로드 해제 시 즉시 다음 다운로드 시작 (반응성 향상)
        if auto_start_next:
            print(f"[LOG] 다운로드 해제 후 즉시 자동 시작 체크")
            # 백그라운드에서 즉시 체크 (블로킹 방지)
            threading.Thread(target=lambda: self.check_and_start_waiting_downloads(force_check=True), daemon=True).start()
        else:
            print(f"[LOG] auto_start_next=False이므로 자동 시작 건너뜀")
    
    def unregister_local_download(self, download_id):
        """로컬 다운로드 해제 - 하위 호환성"""
        self.unregister_download(download_id)
    
    def stop_download_immediately(self, download_id):
        """특정 다운로드를 즉시 정지 (안전한 방법)"""
        with self._lock:
            if download_id in self.stop_events:
                self.stop_events[download_id].set()
                print(f"[LOG] ★★★ 다운로드 {download_id} 즉시 정지 플래그 설정 완료 ★★★")
                return True
            else:
                print(f"[LOG] ⚠️ 다운로드 {download_id} 정지 플래그를 찾을 수 없음 - 등록되지 않은 다운로드")
                return False
    
    def is_download_stopped(self, download_id):
        """특정 다운로드가 정지되었는지 확인"""
        with self._lock:
            if download_id in self.stop_events:
                is_stopped = self.stop_events[download_id].is_set()
                if is_stopped:
                    print(f"[LOG] ★★★ 다운로드 {download_id} 정지 플래그 감지됨 ★★★")
                return is_stopped
            return False
    
    def check_and_start_waiting_downloads(self, force_check=False):
        """대기 중인 다운로드를 확인하고 시작 (전체 제한 + 1fichier 개별 제한 고려)"""
        # 부하 감소를 위한 중복 호출 방지 (force_check가 True면 무시)
        current_time = time.time()
        if not force_check and current_time - self._last_check_time < self._check_interval:
            print(f"[LOG] 대기 중인 다운로드 체크 스킵 (최근 체크: {current_time - self._last_check_time:.1f}초 전)")
            return
        
        self._last_check_time = current_time
        
        db = None
        try:
            db = next(get_db())
            
            # DB에서 실제 활성 상태인 다운로드 수 확인 (downloading/proxying/parsing)
            active_downloads_count = db.query(DownloadRequest).filter(
                DownloadRequest.status.in_([StatusEnum.downloading, StatusEnum.proxying, StatusEnum.parsing])
            ).count()
            
            active_1fichier_count = db.query(DownloadRequest).filter(
                DownloadRequest.status.in_([StatusEnum.downloading, StatusEnum.proxying, StatusEnum.parsing]),
                DownloadRequest.use_proxy == False,
                DownloadRequest.url.contains('1fichier.com')
            ).count()
            
            print(f"[LOG] 대기 중인 다운로드 체크 시작 (실제 활성: {active_downloads_count}/{self.MAX_TOTAL_DOWNLOADS}, 1fichier: {active_1fichier_count}/{self.MAX_LOCAL_DOWNLOADS})")
            
            # 쿨다운이 끝났으면 cooldown 상태인 다운로드를 pending으로 되돌리기
            if self.get_1fichier_cooldown_remaining() <= 0:
                cooldown_downloads = db.query(DownloadRequest).filter(
                    DownloadRequest.status == StatusEnum.cooldown,
                    DownloadRequest.use_proxy == False,
                    DownloadRequest.url.contains('1fichier.com')
                ).all()
                
                for cooldown_download in cooldown_downloads:
                    cooldown_download.status = StatusEnum.pending
                    print(f"[LOG] 쿨다운 완료 - ID {cooldown_download.id}를 pending으로 복원")
                
                if cooldown_downloads:
                    db.commit()
            else:
                # 1fichier 쿨다운 상태인 대기중인 다운로드들에 쿨다운 메시지 전송
                self._send_cooldown_updates(db)
            
            # 전체 다운로드 수가 5개 이상이면 시작하지 않음
            if active_downloads_count >= self.MAX_TOTAL_DOWNLOADS:
                print(f"[LOG] 전체 다운로드 제한 도달 ({self.MAX_TOTAL_DOWNLOADS}개). 대기 중...")
                return
            
            # 현재 실행 중인 다운로드 ID 목록 가져오기 (중복 시작 방지)
            with self._lock:
                active_ids = list(self.active_downloads.keys())
            
            # DB에서도 실제 활성 다운로드 ID 목록 가져오기 (정확성 향상)
            db_active_ids = [r.id for r in db.query(DownloadRequest).filter(
                DownloadRequest.status.in_([StatusEnum.downloading, StatusEnum.proxying, StatusEnum.parsing])
            ).all()]
            
            # 두 목록을 합쳐서 중복 시작 완전 방지
            all_active_ids = list(set(active_ids + db_active_ids))
            print(f"[LOG] 활성 다운로드 ID: 메모리={active_ids}, DB={db_active_ids}, 전체={all_active_ids}")
            
            started_count = 0
            
            # 1. 프록시 다운로드 우선 처리 (제한 없음) - return 제거하여 계속 처리
            while active_downloads_count + started_count < self.MAX_TOTAL_DOWNLOADS:
                proxy_request = db.query(DownloadRequest).filter(
                    DownloadRequest.status == StatusEnum.pending,
                    DownloadRequest.use_proxy == True,
                    # 이미 실행 중인 다운로드는 제외
                    ~DownloadRequest.id.in_(all_active_ids) if all_active_ids else True
                ).order_by(DownloadRequest.requested_at.asc()).first()  # 먼저 요청된 순서대로 (FIFO)
                
                if proxy_request:
                    print(f"[LOG] 대기 중인 프록시 다운로드 발견: {proxy_request.id} (실행중 제외: {all_active_ids})")
                    self._start_waiting_download(proxy_request)
                    all_active_ids.append(proxy_request.id)  # 시작한 다운로드를 목록에 추가
                    started_count += 1
                else:
                    break  # 더 이상 프록시 다운로드 없음

            # 2. 1fichier가 아닌 로컬 다운로드 찾기 - return 제거하여 계속 처리
            while active_downloads_count + started_count < self.MAX_TOTAL_DOWNLOADS:
                non_fichier_request = db.query(DownloadRequest).filter(
                    DownloadRequest.status == StatusEnum.pending,
                    DownloadRequest.use_proxy == False,
                    ~DownloadRequest.url.contains('1fichier.com'),
                    # 이미 실행 중인 다운로드는 제외
                    ~DownloadRequest.id.in_(all_active_ids) if all_active_ids else True
                ).order_by(DownloadRequest.requested_at.asc()).first()  # 먼저 요청된 순서대로 (FIFO)
                
                if non_fichier_request:
                    print(f"[LOG] 대기 중인 비-1fichier 다운로드 발견: {non_fichier_request.id} (실행중 제외: {all_active_ids})")
                    self._start_waiting_download(non_fichier_request)
                    all_active_ids.append(non_fichier_request.id)  # 시작한 다운로드를 목록에 추가
                    started_count += 1
                else:
                    break  # 더 이상 비-1fichier 다운로드 없음
            
            # 3. 1fichier 로컬 다운로드 찾기 (1fichier 개별 제한 + 쿨다운 체크)
            if (active_downloads_count + started_count < self.MAX_TOTAL_DOWNLOADS and 
                active_1fichier_count < self.MAX_LOCAL_DOWNLOADS and
                self.get_1fichier_cooldown_remaining() <= 0):  # 쿨다운만 직접 체크
                
                fichier_request = db.query(DownloadRequest).filter(
                    DownloadRequest.status == StatusEnum.pending,
                    DownloadRequest.use_proxy == False,
                    DownloadRequest.url.contains('1fichier.com'),
                    # 이미 실행 중인 다운로드는 제외
                    ~DownloadRequest.id.in_(all_active_ids) if all_active_ids else True
                ).order_by(DownloadRequest.requested_at.asc()).first()  # 먼저 요청된 순서대로 (FIFO)
                
                if fichier_request:
                    print(f"[LOG] 대기 중인 1fichier 다운로드 발견: {fichier_request.id} (실행중 제외: {all_active_ids})")
                    self._start_waiting_download(fichier_request)
                    started_count += 1
            
            # 시작된 다운로드 수 로그 출력
            if started_count > 0:
                print(f"[LOG] 총 {started_count}개 다운로드 동시 시작 완료")
                    
        except Exception as e:
            print(f"[LOG] 대기 중인 다운로드 시작 실패: {e}")
        finally:
            if db:
                try:
                    db.close()
                except:
                    pass
    
    def _start_waiting_download(self, waiting_request):
        """대기 중인 다운로드 시작 - 1fichier와 일반 다운로드 분기"""
        import threading
        
        # 이미 실행 중인지 체크 (중복 시작 방지)
        with self._lock:
            if waiting_request.id in self.active_downloads:
                print(f"[LOG] 다운로드 {waiting_request.id}는 이미 실행 중 - 중복 시작 방지")
                return
        
        # DB에서 최신 프록시 설정 다시 조회 (실시간 업데이트 반영)
        try:
            db = next(get_db())
            fresh_request = db.query(DownloadRequest).filter(DownloadRequest.id == waiting_request.id).first()
            use_proxy = fresh_request.use_proxy if fresh_request else getattr(waiting_request, 'use_proxy', False)
            print(f"[LOG] 다운로드 {waiting_request.id} 최신 프록시 설정: {use_proxy}")
        except:
            use_proxy = getattr(waiting_request, 'use_proxy', False)
            print(f"[LOG] 다운로드 {waiting_request.id} 기본 프록시 설정 사용: {use_proxy}")
        
        # URL 타입에 따라 적절한 다운로드 함수 선택
        if "1fichier.com" in waiting_request.url.lower():
            # 1fichier 다운로드
            target_function = download_1fichier_file
            print(f"[LOG] 1fichier 다운로드 시작: {waiting_request.id}")
        else:
            # 일반 다운로드
            target_function = download_general_file
            print(f"[LOG] 일반 다운로드 시작: {waiting_request.id}")
        
        thread = threading.Thread(
            target=target_function,
            args=(waiting_request.id, "ko", use_proxy),
            daemon=True
        )
        thread.start()
        
        # active_downloads에 추가 (중복 시작 방지용)
        with self._lock:
            self.active_downloads[waiting_request.id] = thread
            
        print(f"[LOG] 대기 중인 다운로드 시작: {waiting_request.id} (프록시: {use_proxy})")

    def cancel_download(self, download_id):
        # 다운로드 상태를 stopped로 변경하여 자연스럽게 종료되도록 함
        print(f"[LOG] 다운로드 매니저: {download_id} 취소 요청")
        
        # DB 상태 변경
        db = None
        try:
            db = next(get_db())
            req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
            if req and req.status in [StatusEnum.downloading, StatusEnum.proxying]:
                req.status = StatusEnum.stopped
                db.commit()
                print(f"[LOG] 다운로드 {download_id} 상태를 stopped로 변경 (이어받기 지원)")
                
                # SSE 상태 업데이트 브로드캐스트
                import json
                # 현재 진행률 계산
                progress = 0.0
                if req.total_size and req.total_size > 0 and req.downloaded_size:
                    progress = min(100.0, (req.downloaded_size / req.total_size) * 100)
                
                safe_status_queue_put(json.dumps({
                    "type": "status_update",
                    "data": {
                        "id": download_id,
                        "status": "stopped",
                        "progress": progress,
                        "downloaded_size": req.downloaded_size or 0,
                        "total_size": req.total_size or 0
                    }
                }))
        except Exception as e:
            print(f"[LOG] 다운로드 상태 변경 실패: {e}")
        finally:
            if db:
                try:
                    db.close()
                except:
                    pass
        
        # 관리 목록에서 제거
        with self._lock:
            self.active_downloads.pop(download_id, None)
        # 다운로드에서 해제
        self.unregister_download(download_id)

    def is_download_active(self, download_id):
        with self._lock:
            t = self.active_downloads.get(download_id)
            return t and t.is_alive()

    def terminate_all_downloads(self):
        print("[LOG] 모든 다운로드 스레드 관리 목록에서 제거 (스레드는 강제 종료 불가)")
        # 진행 중인 다운로드 ID들을 수집
        with self._lock:
            download_ids = list(self.active_downloads.keys())
            self.active_downloads.clear()
        
        # 각 다운로드의 상태를 stopped로 변경하여 자연스럽게 종료되도록 함
        if download_ids:
            db = None
            try:
                db = next(get_db())
                import json
                for download_id in download_ids:
                    req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
                    if req and req.status in [StatusEnum.downloading, StatusEnum.proxying]:
                        req.status = StatusEnum.stopped
                        print(f"[LOG] 다운로드 {download_id} 상태를 stopped로 변경 (이어받기 지원)")
                        
                        # SSE 상태 업데이트 브로드캐스트
                        # 현재 진행률 계산
                        progress = 0.0
                        if req.total_size and req.total_size > 0 and req.downloaded_size:
                            progress = min(100.0, (req.downloaded_size / req.total_size) * 100)
                        
                        safe_status_queue_put(json.dumps({
                            "type": "status_update",
                            "data": {
                                "id": download_id,
                                "status": "stopped",
                                "progress": progress,
                                "downloaded_size": req.downloaded_size or 0,
                                "total_size": req.total_size or 0
                            }
                        }))
                db.commit()
            except Exception as e:
                print(f"[LOG] 다운로드 상태 변경 실패: {e}")
            finally:
                if db:
                    try:
                        db.close()
                    except:
                        pass

# 전역 다운로드 매니저 인스턴스
download_manager = DownloadManager()
