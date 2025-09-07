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
import requests
import json
from pathlib import Path
from sqlalchemy.orm import Session

from .db import get_db
from .models import DownloadRequest, StatusEnum
from .config import get_download_path, get_config
from .proxy_manager import get_unused_proxies, mark_proxy_used
from .parser_service import get_or_parse_direct_link


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


def send_websocket_message(message_type: str, data: dict):
    """WebSocket 메시지를 전송하는 함수"""
    try:
        # main.py의 status_queue에 메시지 전송
        from core.shared import status_queue
        message = json.dumps({
            "type": message_type,
            "data": data
        }, ensure_ascii=False)
        status_queue.put(message)
        # print(f"[LOG] WebSocket 메시지 전송: {message_type}")
    except Exception as e:
        print(f"[LOG] WebSocket 메시지 전송 실패: {e}")

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


def send_telegram_wait_notification(file_name: str, wait_minutes: int, lang: str = "ko"):
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
        import datetime
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
        
        message = f"""🔔 <b>OC-Proxy: {wait_text}</b> ⏳

📁 <b>{filename_text}</b>
<code>{file_name}</code>

📊 <b>{filesize_text}</b>
<code>{filesize_text or '알 수 없음'}</code>

⏰ <b>{wait_time_text}</b>
<code>{wait_minutes}분</code>"""
        
        # 텔레그램 API 호출 (비동기)
        import requests
        import threading
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        def send_async():
            try:
                response = requests.post(url, json=payload, timeout=10)
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
        import datetime
        # ISO 형식의 UTC 시간을 파싱
        if utc_time_str.endswith('Z'):
            utc_time_str = utc_time_str[:-1]
        
        utc_dt = datetime.datetime.fromisoformat(utc_time_str)
        # UTC+9 (한국 시간) 적용
        kst_dt = utc_dt + datetime.timedelta(hours=9)
        return kst_dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return utc_time_str or "알 수 없음"

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
        import datetime
        if lang == "ko":
            # 한국어일 때만 KST로 표시
            current_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            # 영어 등 다른 언어는 UTC로 표시
            current_time = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        if status == "done":
            success_text = translations.get("telegram_download_success", "Download Complete")
            filename_text = translations.get("telegram_filename", "Filename")
            filesize_text = translations.get("telegram_filesize", "파일크기")
            requested_time_text = translations.get("telegram_requested_time", "요청시간")
            completed_time_text = translations.get("telegram_completed_time", "완료시간")
            save_path_text = translations.get("telegram_save_path", "저장경로")

            message = f"""🔔 <b>OC-Proxy: {success_text}</b> 🎉

📁 <b>{filename_text}</b>
<code>{file_name}</code>

📊 <b>{filesize_text}</b>
<code>{file_size or '알 수 없음'}</code>

📥 <b>{requested_time_text}</b>
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
        import requests
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        # 백그라운드에서 전송 (블로킹 방지)
        def send_async():
            try:
                response = requests.post(url, json=payload, timeout=10)
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


def download_1fichier_file_new(request_id: int, lang: str = "ko", use_proxy: bool = True, retry_count: int = 0, fichier_retry_count: int = 0):
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
    
    # 로컬 다운로드 등록 (1fichier만)
    from .shared import download_manager
    
    # 새로운 DB 세션 생성
    from .db import SessionLocal
    db = SessionLocal()
    req = None
    
    try:
        # 요청 정보 조회
        req = db.query(DownloadRequest).filter(DownloadRequest.id == request_id).first()
        if req is None:
            print(f"[LOG] 다운로드 요청을 찾을 수 없음: ID {request_id}")
            return
            
        # 지연 시간 체크 (5번 이후 재시도에서 3분 지연)
        if req.error and "delay_until:" in req.error:
            try:
                import datetime
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
                else:
                    print(f"[LOG] 다운로드가 정지 상태이므로 제한 확인 생략: ID {request_id}")
                    return
                
                    # WebSocket으로 대기 상태 알림
                    send_websocket_message("status_update", {
                        "id": req.id,
                        "url": req.url,
                        "file_name": req.file_name,
                        "status": "pending", 
                        "message": "다운로드 대기 중",
                        "requested_at": req.requested_at.isoformat() if req.requested_at else None
                    })
                
                # 매니저가 자동으로 시작해주므로 여기서는 그냥 종료
                print(f"[LOG] 매니저의 자동 시작 기능에 의해 대기: ID {request_id}")
                return
        
        # 다운로드 등록 (제한에 걸리지 않은 경우만)
        download_manager.register_download(request_id, req.url)
        
        
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
        
        # 기존 파일 확인
        initial_downloaded_size = 0
        if part_file_path.exists():
            file_path = part_file_path
            initial_downloaded_size = part_file_path.stat().st_size
            print(f"[LOG] 이어받기: {initial_downloaded_size} bytes")
        elif file_path.exists():
            initial_downloaded_size = file_path.stat().st_size
            print(f"[LOG] 기존 파일 발견: {initial_downloaded_size} bytes")
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
            req.status = StatusEnum.proxying
            db.commit()
            
            # WebSocket으로 상태 업데이트 알림
            send_websocket_message("status_update", {
                "id": req.id,
                "url": req.url,
                "file_name": req.file_name,
                "status": "proxying",
                "error": None
            })
            force_reparse = initial_downloaded_size > 0 or req.direct_link is None
            print(f"[LOG] 강제 재파싱 모드: {force_reparse} (이어받기: {initial_downloaded_size > 0}, 링크없음: {req.direct_link is None})")
            direct_link, used_proxy_addr = parse_with_proxy_cycling(req, db, force_reparse=force_reparse)
        else:
            print(f"[LOG] 로컬 모드로 Direct Link 파싱")
            req.status = StatusEnum.downloading
            db.commit()
            
            # WebSocket으로 상태 업데이트 알림 
            send_websocket_message("status_update", {
                "id": req.id,
                "url": req.url,
                "file_name": req.file_name,
                "status": "downloading",
                "error": None
            })
            
            # 재시도이거나 이어받기인 경우 항상 강제 재파싱 (원본 URL로 새로 파싱)
            force_reparse = initial_downloaded_size > 0 or req.direct_link is None
            print(f"[LOG] 강제 재파싱 모드: {force_reparse} (이어받기: {initial_downloaded_size > 0}, 링크없음: {req.direct_link is None})")
            
            # 로컬 모드에서는 파일 정보와 함께 파싱
            from .parser_service import parse_direct_link_with_file_info
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
                print(f"[LOG] Direct Link 실패. 기존 파싱 로직으로 재시도 (파일명 보존)")
                direct_link = get_or_parse_direct_link(req, use_proxy=False, force_reparse=force_reparse)
                
                # WebSocket으로 파일명 업데이트 전송
                send_websocket_message("filename_update", {
                    "id": req.id,
                    "file_name": req.file_name,
                    "url": req.url,
                    "status": req.status.value if hasattr(req.status, 'value') else str(req.status)
                })
            
        
        # 파싱 완료 후 파일명 확인 (프록시/로컬 공통)
        print(f"[LOG] 파싱 완료 후 파일명 체크: req.file_name='{req.file_name}', type={type(req.file_name)}, len={len(req.file_name) if req.file_name else 'None'}")
        print(f"[LOG] 파일명 조건 체크: not req.file_name={not req.file_name}, strip()==''{req.file_name.strip() == '' if req.file_name else 'N/A'}, equals_cloud_storage={req.file_name == '1fichier.com: Cloud Storage' if req.file_name else 'N/A'}")
        
        # 파일명이 없거나 기본값인 경우 fallback 로직 시도 (fallback은 최소화)
        if not req.file_name or req.file_name.strip() == '' or req.file_name == '1fichier.com: Cloud Storage':
            print(f"[WARNING] 파싱된 파일명이 없습니다. fallback 로직 시작")
            
            # URL에서 파일명 추출 시도
            from urllib.parse import urlparse, unquote
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

        # 정지 상태 체크 (파싱 후)
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 정지됨 (파싱 후): ID {request_id}")
            return
        
        # direct_link 유효성 체크 (DNS 오류 등으로 인한 만료된 링크 감지)
        if direct_link:
            print(f"[LOG] Direct Link 유효성 체크: {direct_link}")
            from .parser_service import is_direct_link_expired
            if is_direct_link_expired(direct_link, use_proxy=use_proxy):
                print(f"[LOG] Direct Link 만료 감지 - 강제 재파싱 시도: {direct_link}")
                req.direct_link = None
                db.commit()
                
                # 강제 재파싱
                if use_proxy:
                    direct_link, used_proxy_addr = parse_with_proxy_cycling(req, db, force_reparse=True)
                else:
                    direct_link = get_or_parse_direct_link(req, use_proxy=False, force_reparse=True)
                
                print(f"[LOG] 재파싱 결과: {direct_link}")
        
        if not direct_link:
            # URL 유효성 체크를 통한 더 자세한 에러 메시지
            try:
                import requests
                test_response = requests.head(req.url, timeout=5)
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
            
            # WebSocket으로 실패 상태 전송
            send_websocket_message("status_update", {
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
                "direct_link": req.direct_link,
                "use_proxy": req.use_proxy
            })
            
            raise Exception(error_msg)
        
        # 특별한 다운로드 모드 처리
        if direct_link in ["DIRECT_DOWNLOAD_STREAM", "DIRECT_FILE_RESPONSE"]:
            print(f"[LOG] 직접 다운로드 모드: {direct_link}")
            req.direct_link = direct_link
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
            req.direct_link = direct_link
            req.status = StatusEnum.downloading
            db.commit()
            
            # 다운로드 시작 시 즉시 WebSocket 상태 업데이트 (프로그레스바 즉시 시작)
            send_websocket_message("status_update", {
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
                "direct_link": req.direct_link,
                "use_proxy": req.use_proxy
            })
            
            # 정지 상태 체크 (다운로드 시작 전)
            db.refresh(req)
            if req.status == StatusEnum.stopped:
                print(f"[LOG] 다운로드 정지됨 (다운로드 시작 전): ID {request_id}")
                return
            
            # 2단계: 프록시 순환으로 실제 다운로드
            if use_proxy:
                print(f"[LOG] 프록시 순환 다운로드 시작 (시작 프록시: {used_proxy_addr})")
                download_with_proxy_cycling(direct_link, file_path, used_proxy_addr, initial_downloaded_size, req, db)
            else:
                print(f"[LOG] 로컬 연결로 다운로드 시작")
                download_local(direct_link, file_path, initial_downloaded_size, req, db)
        
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
                from pathlib import Path
                
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
        import datetime
        req.finished_at = datetime.datetime.utcnow()
        if final_file_path:
            req.save_path = str(final_file_path)
        db.commit()
        
        # 텔레그램 알림 전송 (완료)
        unknown_file = get_translations(lang).get("telegram_unknown_file", "알 수 없는 파일")
        
        # 파일 크기 포맷팅
        file_size_str = "알 수 없음"
        if req.total_size:
            file_size_str = format_file_size(req.total_size)

        # 시간 포맷팅
        import datetime
        requested_time_str = None
        if req.requested_at:
            if lang == "ko":
                # 한국어일 때만 KST로 변환
                kst_requested = req.requested_at + datetime.timedelta(hours=9)
                requested_time_str = kst_requested.strftime("%Y-%m-%d %H:%M:%S")
            else:
                # 영어 등 다른 언어는 UTC 그대로 표시
                requested_time_str = req.requested_at.strftime("%Y-%m-%d %H:%M:%S UTC")

        download_time_str = None
        if req.finished_at:
            if lang == "ko":
                # 한국어일 때만 KST로 변환
                kst_finished = req.finished_at + datetime.timedelta(hours=9)
                download_time_str = kst_finished.strftime("%Y-%m-%d %H:%M:%S")
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
        
        # WebSocket으로 완료 상태 전송
        send_websocket_message("status_update", {
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
            "direct_link": req.direct_link,
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
                    
                    # WebSocket으로 재시도 상태 전송
                    send_websocket_message("status_update", {
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
                        "direct_link": req.direct_link,
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
                        
                        # WebSocket으로 재시도 대기 상태 전송
                        send_websocket_message("status_update", {
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
                            "direct_link": req.direct_link,
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
                        
                        # WebSocket으로 실패 상태 전송
                        send_websocket_message("status_update", {
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
                            "direct_link": req.direct_link,
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
    from .proxy_manager import get_working_proxy_batch, get_unused_proxies
    from .parser_service import parse_filename_only_with_proxy
    from .i18n import get_message
    
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
                    print(f"[LOG] ✅ 파일명 파싱 성공: {result['filename']} (프록시: {proxy_addr})")
                    return result
                    
            except Exception as e:
                print(f"[LOG] ❌ 파일명 파싱 실패 (프록시: {proxy_addr}): {e}")
                continue
                
        proxy_index = batch_end
        
    print(f"[LOG] ❌ 모든 프록시로 파일명 파싱 실패")
    return None

def parse_with_proxy_cycling(req, db: Session, force_reparse=False):
    """프록시 배치를 병렬 테스트해서 성공한 프록시들로 파싱"""
    from .proxy_manager import get_working_proxy_batch, get_unused_proxies
    from .i18n import get_message
    from .shared import download_manager
    
    # 활성 다운로드 간섭 방지 - 이미 다운로드가 진행 중인 경우 상태 변경하지 않음
    is_actively_downloading = download_manager.is_download_active(req.id)
    if is_actively_downloading:
        print(f"[LOG] ID {req.id}는 이미 활성 다운로드 중이므로 파싱 상태 변경 생략")
    else:
        # 프록시 파싱 시작 상태 알림  
        req.status = StatusEnum.parsing
        db.commit()
        
        send_websocket_message("status_update", {
            "id": req.id,
            "status": "parsing",
            "message": get_message("proxy_parsing_started"),
            "progress": 0,
            "url": req.url
        })
    
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
            send_websocket_message("status_update", {
                "id": req.id,
                "status": "parsing",
                "message": get_message("proxy_batch_testing").format(batch=batch_num),
                "progress": 5,
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
        from .proxy_manager import test_proxy_batch, mark_proxy_used
        working_proxies, failed_proxies = test_proxy_batch(db, batch_proxies, req=req)
        
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
            import time
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
            # WebSocket으로 프록시 시도 중 알림 (상세)
            send_websocket_message("proxy_trying", {
                "proxy": working_proxy,
                "step": "파싱 중 (검증됨)",
                "current": i + 1,
                "total": len(working_proxies),
                "url": req.url
            })
            
            # 상태 업데이트도 함께 (활성 다운로드 중이 아닐 때만)
            if not download_manager.is_download_active(req.id):
                send_websocket_message("status_update", {
                    "id": req.id,
                    "status": "parsing",
                    "message": get_message("proxy_verified_parsing").format(current=i + 1, total=len(working_proxies)),
                    "progress": 10 + int((i / len(working_proxies)) * 30),  # 10-40% 진행률
                    "url": req.url
                })
            
            # 프록시로 파싱 시도 (재시도 없이 1회만) - 파일 정보도 함께 추출
            try:
                from .parser_service import parse_direct_link_with_file_info
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
                    
                    # WebSocket으로 파일명 업데이트 전송
                    send_websocket_message("filename_update", {
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
                
                # 파싱 완료, 프록시 연결 상태로 전환
                req.status = StatusEnum.proxying
                db.commit()
                
                send_websocket_message("status_update", {
                    "id": req.id,
                    "status": "proxying",
                    "message": get_message("download_proxying") + f" ({working_proxy})",
                    "progress": 50,
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
        # 매 프록시 시도마다 정지 상태 체크
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 프록시 파싱 중 정지됨: {req.id}")
            return None, None
        
        try:
            # print(f"[LOG] 파싱 시도 {i+1}/{len(unused_proxies)}: {proxy_addr}")
            
            # WebSocket으로 프록시 시도 중 알림
            send_websocket_message("proxy_trying", {
                "proxy": proxy_addr,
                "step": "파싱 중",
                "current": i + 1,
                "total": len(unused_proxies),
                "url": req.url
            })
            
            # 프록시로 파싱 시도 (카운트다운 감지) - 파일 정보도 함께 추출
            try:
                from .parser_service import parse_direct_link_with_file_info
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
                    
                    # WebSocket으로 파일명 업데이트 전송
                    send_websocket_message("filename_update", {
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
                
                # WebSocket으로 프록시 성공 알림
                send_websocket_message("proxy_success", {
                    "proxy": proxy_addr,
                    "step": "파싱 완료",
                    "url": req.url
                })
                
                return direct_link, proxy_addr
                
        except (requests.exceptions.ConnectTimeout, 
                requests.exceptions.ReadTimeout, 
                requests.exceptions.Timeout, 
                requests.exceptions.ProxyError) as e:
            
            print(f"[LOG] 파싱 실패 - 프록시 {proxy_addr}: {e}")
            mark_proxy_used(db, proxy_addr, success=False)
            
            # WebSocket으로 프록시 실패 알림
            send_websocket_message("proxy_failed", {
                "proxy": proxy_addr,
                "step": "파싱 실패",
                "error": str(e),
                "url": req.url
            })
            
            continue
            
        except Exception as e:
            print(f"[LOG] 파싱 오류 - 프록시 {proxy_addr}: {e}")
            mark_proxy_used(db, proxy_addr, success=False)
            
            # WebSocket으로 프록시 실패 알림
            send_websocket_message("proxy_failed", {
                "proxy": proxy_addr,
                "step": "파싱 오류",
                "error": str(e),
                "url": req.url
            })
            
            continue
    
    print(f"[LOG] 모든 프록시에서 파싱 실패")
    return None, None


def download_with_proxy_cycling(direct_link, file_path, preferred_proxy, initial_size, req, db):
    """프록시를 순환하면서 다운로드 - 실패시 자동으로 다음 프록시로 이동"""
    from .proxy_manager import get_unused_proxies, mark_proxy_used
    
    # 선호 프록시부터 시작하여 모든 프록시 시도
    unused_proxies = get_unused_proxies(db)
    
    # 선호 프록시가 있으면 맨 앞에 배치
    if preferred_proxy and preferred_proxy not in unused_proxies:
        unused_proxies.insert(0, preferred_proxy)
    elif preferred_proxy and preferred_proxy in unused_proxies:
        # 선호 프록시를 맨 앞으로 이동
        unused_proxies.remove(preferred_proxy)
        unused_proxies.insert(0, preferred_proxy)
    
    if not unused_proxies:
        print("[LOG] 사용 가능한 프록시가 없음")
        req.status = StatusEnum.failed
        req.error = "사용 가능한 프록시가 없음"
        db.commit()
        return
    
    print(f"[LOG] {len(unused_proxies)}개 프록시로 다운로드 순환 시도")
    
    last_error = None
    for i, proxy_addr in enumerate(unused_proxies):
        # 매 프록시 시도마다 정지 상태 체크
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 프록시 다운로드 중 정지됨: {req.id}")
            return
        
        try:
            print(f"[LOG] 다운로드 시도 {i+1}/{len(unused_proxies)}: {proxy_addr}")
            
            # WebSocket으로 프록시 시도 중 알림
            send_websocket_message("proxy_trying", {
                "proxy": proxy_addr,
                "step": "다운로드 중",
                "current": i + 1,
                "total": len(unused_proxies),
                "url": req.url
            })
            
            # 프록시로 다운로드 시도
            download_with_proxy(direct_link, file_path, proxy_addr, initial_size, req, db)
            
            # 성공하면 프록시 성공 마킹하고 종료
            mark_proxy_used(db, proxy_addr, success=True)
            print(f"[LOG] 프록시 다운로드 성공: {proxy_addr}")
            return
            
        except Exception as e:
            last_error = e
            error_str = str(e)
            print(f"[LOG] 프록시 {proxy_addr} 다운로드 실패: {error_str}")
            
            # 프록시 실패 마킹
            mark_proxy_used(db, proxy_addr, success=False)
            
            # WebSocket으로 프록시 실패 알림
            send_websocket_message("proxy_failed", {
                "proxy": proxy_addr,
                "error": error_str,
                "current": i + 1,
                "total": len(unused_proxies),
                "url": req.url
            })
            
            # 마지막 프록시가 아니면 계속 시도
            if i < len(unused_proxies) - 1:
                print(f"[LOG] 다음 프록시로 이동: {i+2}/{len(unused_proxies)}")
                continue
    
    # 모든 프록시에서 실패
    print(f"[LOG] 모든 프록시에서 다운로드 실패")
    if last_error:
        raise last_error  # 마지막 에러를 상위로 전파


def download_with_proxy(direct_link, file_path, proxy_addr, initial_size, req, db):
    """지정된 프록시로 다운로드"""
    proxies = {
        'http': f'http://{proxy_addr}',
        'https': f'http://{proxy_addr}'
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Accept-Language': 'ko-KR,ko;q=0.9',
        'Connection': 'keep-alive'
    }
    
    if initial_size > 0:
        headers['Range'] = f'bytes={initial_size}-'
        print(f"[LOG] 이어받기 헤더: Range={headers['Range']}")
    
    try:
        # 다운로드 시작 전 정지 상태 체크
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 시작 전 정지됨: {req.id}")
            return
        
        # WebSocket으로 다운로드 시작 알림
        send_websocket_message("proxy_trying", {
            "proxy": proxy_addr,
            "step": "다운로드 중",
            "current": 1,
            "total": 1,
            "url": req.url
        })
        
        with requests.get(direct_link, stream=True, headers=headers, proxies=proxies, timeout=(3, 10)) as response:
            response.raise_for_status()
            
            # 응답 받은 후 정지 상태 체크
            db.refresh(req)
            if req.status == StatusEnum.stopped:
                print(f"[LOG] 응답 받은 후 정지됨: {req.id}")
                return
            
            content_length = int(response.headers.get('Content-Length', 0))
            content_type = response.headers.get('Content-Type', '').lower()
            
            # Content-Disposition에서 실제 파일명 추출 시도
            content_disposition = response.headers.get('Content-Disposition', '')
            if content_disposition and 'filename' in content_disposition:
                import re
                # filename="..." 또는 filename*=UTF-8''... 형태 처리
                filename_match = re.search(r'filename[*]?=(?:UTF-8\'\')?["\']?([^"\';\r\n]*)["\']?', content_disposition)
                if filename_match:
                    extracted_filename = filename_match.group(1).strip()
                    # URL 디코딩
                    from urllib.parse import unquote
                    extracted_filename = unquote(extracted_filename)
                    
                    # 임시 파일명이거나 파일명이 확정되지 않은 경우에만 업데이트
                    if (req.file_name.endswith('.tmp') or req.file_name == '1fichier.com: Cloud Storage' or 
                        req.file_name.startswith('1fichier_')):
                        print(f"[LOG] Content-Disposition에서 실제 파일명 추출: '{extracted_filename}'")
                        req.file_name = extracted_filename
                        db.commit()
                        
                        # WebSocket으로 파일명 업데이트 전송
                        send_websocket_message("filename_update", {
                            "id": req.id,
                            "file_name": req.file_name,
                            "url": req.url,
                            "status": req.status.value if hasattr(req.status, 'value') else str(req.status)
                        })
            
            # 응답 검증: HTML이나 빈 파일인지 확인
            print(f"[LOG] 프록시 응답 분석 - Content-Length: {content_length}, Content-Type: {content_type}")
            
            # Content-Type이 HTML인 경우 - 내용을 확인해서 실제 HTML인지 판단
            if 'text/html' in content_type:
                print(f"[LOG] HTML Content-Type 감지 - 내용 검사 중...")
                # 처음 1024바이트를 확인해서 실제 HTML인지 판단
                peek_content = response.content[:1024] if hasattr(response, 'content') else b''
                try:
                    peek_text = peek_content.decode('utf-8', errors='ignore').lower()
                    # 실제 HTML 태그와 에러 메시지가 있는지 확인
                    html_indicators = ['<html', '<body', '<head', '<!doctype']
                    error_indicators = ['error', '404', '403', 'not found', 'access denied', 'forbidden']
                    
                    has_html_tags = any(indicator in peek_text for indicator in html_indicators)
                    has_error_msg = any(indicator in peek_text for indicator in error_indicators)
                    
                    # HTML 태그가 있고 에러 메시지도 있으면 실제 에러 페이지
                    if has_html_tags and has_error_msg:
                        print(f"[LOG] 실제 HTML 에러 페이지 감지: {peek_text[:100]}...")
                        raise Exception("다운로드 링크가 에러 페이지로 리다이렉트됨 (HTML 응답)")
                    elif has_html_tags:
                        print(f"[LOG] HTML 페이지지만 에러가 아닐 수 있음 - 계속 진행")
                    else:
                        print(f"[LOG] HTML Content-Type이지만 실제 파일 데이터로 보임 - 계속 진행")
                except:
                    print(f"[LOG] HTML 내용 검사 실패 - 계속 진행")
                    pass
            
            # Content-Length가 너무 작은 경우 (1KB 미만)
            if content_length < 1024 and initial_size == 0:
                print(f"[LOG] 파일 크기가 너무 작음: {content_length} bytes - 에러 응답일 가능성")
                # 작은 응답의 내용을 확인해봄
                peek_content = response.content[:500]  # 처음 500바이트만 확인
                try:
                    peek_text = peek_content.decode('utf-8', errors='ignore').lower()
                    # HTML 태그나 에러 메시지가 포함되어 있는지 확인
                    error_indicators = ['<html', '<body', 'error', '404', '403', 'not found', 'access denied']
                    if any(indicator in peek_text for indicator in error_indicators):
                        print(f"[LOG] 응답에 에러 내용 감지: {peek_text[:100]}...")
                        raise Exception(f"다운로드 실패 - 에러 응답 감지 (크기: {content_length} bytes)")
                except:
                    pass  # 디코딩 실패해도 계속 진행
            
            if initial_size > 0:
                # 이어받기: 전체 크기 = 기존 크기 + 남은 크기
                total_size = initial_size + content_length
                print(f"[LOG] 이어받기 - 기존: {initial_size}, 남은 크기: {content_length}")
            else:
                # 새 다운로드: 전체 크기 = Content-Length
                total_size = content_length
            
            # 파일 크기가 0인 경우 다운로드 중단
            if total_size == 0:
                print(f"[LOG] 파일 크기가 0 - 다운로드 중단")
                raise Exception("파일 크기가 0입니다. 다운로드 링크가 올바르지 않습니다.")
            
            req.total_size = total_size
            db.commit()
            
            print(f"[LOG] 프록시 다운로드 시작 - 총 크기: {total_size} bytes, Content-Type: {content_type}")
            
            # 파일 경로 검증 및 디렉토리 생성
            try:
                download_path = Path(file_path).parent
                download_path.mkdir(parents=True, exist_ok=True)
                print(f"[LOG] 파일 저장 경로: {file_path}")
            except Exception as e:
                raise Exception(f"다운로드 디렉토리 생성 실패: {e}")
            
            try:
                with open(file_path, 'ab' if initial_size > 0 else 'wb') as f:
                    downloaded = initial_size
                    last_update_size = downloaded
                    
                    chunk_count = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            chunk_count += 1
                            
                            # 매 64KB마다(8개 청크) 정지 상태 체크
                            if chunk_count % 8 == 0:
                                db.refresh(req)
                                if req.status == StatusEnum.stopped:
                                    print(f"[LOG] 다운로드 중 정지됨: {req.id} (진행률: {downloaded}/{total_size})")
                                    return
                            
                            # 진행률 업데이트 - 적절한 빈도 (매 512KB마다) + WebSocket 실시간 전송  
                            # 진행률 및 속도 계산
                            # 안전한 진행률 계산 (NaN 방지)
                            try:
                                if total_size > 0 and downloaded >= 0:
                                    progress = (downloaded / total_size * 100)
                                    # NaN 체크
                                    if not (0 <= progress <= 100):
                                        progress = 0.0
                                else:
                                    progress = 0.0
                            except (ZeroDivisionError, TypeError, ValueError):
                                progress = 0.0
                            current_percent_for_log = int(progress // 5) * 5  # 5% 단위 (로그용)
                            current_percent_for_ui = int(progress * 2) / 2  # 0.5% 단위 (UI 업데이트용)
                            
                            # 속도 계산을 위한 시간 추적
                            current_time = time.time()
                            if not hasattr(req, '_speed_start_time'):
                                req._speed_start_time = current_time
                                req._speed_start_bytes = downloaded
                            
                            if downloaded - last_update_size >= 10485760 or current_percent_for_ui != getattr(req, '_last_ui_percent', 0):  # 10MB마다 또는 0.5% 단위로 업데이트
                                req.downloaded_size = downloaded
                                db.commit()
                                last_update_size = downloaded
                                
                                # 5% 단위로만 로그 출력 (속도 포함)
                                if current_percent_for_log != getattr(req, '_last_logged_percent', 0) and current_percent_for_log % 5 == 0 and current_percent_for_log > 0:
                                    req._last_logged_percent = current_percent_for_log
                                    # 속도 계산 (로그용)
                                    time_elapsed = current_time - req._speed_start_time
                                    if time_elapsed > 0:
                                        bytes_diff = downloaded - req._speed_start_bytes
                                        download_speed = bytes_diff / time_elapsed
                                        speed_mb = download_speed / (1024 * 1024)
                                        print(f"[LOG] 프록시 진행률: {current_percent_for_log}% ({downloaded}/{total_size}) - 속도: {speed_mb:.2f}MB/s")
                                        req._speed_start_time = current_time
                                        req._speed_start_bytes = downloaded
                                
                                # 0.5% 단위로 WebSocket 업데이트 (화면 업데이트)
                                if current_percent_for_ui != getattr(req, '_last_ui_percent', 0):
                                    req._last_ui_percent = current_percent_for_ui
                                    
                                    # 속도는 2% 단위로만 업데이트 (더 안정적)
                                    current_percent_for_speed = int(progress // 2) * 2
                                    download_speed = getattr(req, '_last_download_speed', 0)
                                    
                                    if current_percent_for_speed != getattr(req, '_last_speed_percent', 0):
                                        req._last_speed_percent = current_percent_for_speed
                                        # 속도 계산 (첫 1분은 2초, 이후 4초 간격)
                                        speed_time_elapsed = current_time - getattr(req, '_ui_speed_time', current_time - 4)
                                        download_start_time = getattr(req, '_download_start_time', current_time)
                                        is_initial_phase = (current_time - download_start_time) < 60  # 첫 1분
                                        
                                        min_interval = 2.0 if is_initial_phase else 4.0
                                        if speed_time_elapsed >= min_interval or not hasattr(req, '_ui_speed_time'):
                                            speed_bytes_diff = downloaded - getattr(req, '_ui_speed_bytes', downloaded)
                                            if speed_time_elapsed > 0 and speed_bytes_diff > 0:
                                                download_speed = speed_bytes_diff / speed_time_elapsed
                                            elif not hasattr(req, '_ui_speed_time'):
                                                # 첫 측정시에는 기본값
                                                download_speed = 0
                                            req._ui_speed_time = current_time
                                            req._ui_speed_bytes = downloaded
                                            req._last_download_speed = download_speed
                                            if not hasattr(req, '_download_start_time'):
                                                req._download_start_time = current_time
                                    
                                    send_websocket_message("progress_update", {
                                        "id": req.id,
                                        "downloaded_size": downloaded,
                                        "total_size": total_size,
                                        "progress": round(max(0.0, min(100.0, progress or 0.0)), 1),
                                        "download_speed": round(download_speed, 0),
                                        "status": "downloading"
                                    })
                    
                    req.downloaded_size = downloaded
                    db.commit()
                
            except Exception as file_error:
                raise Exception(f"파일 쓰기 실패: {file_error}")
                
        print(f"[LOG] 프록시 다운로드 완료: {downloaded} bytes")
        
        # 다운로드 완료 후 파일 검증
        if downloaded == 0:
            print(f"[LOG] 경고: 다운로드된 데이터가 0 bytes")
            raise Exception("다운로드 실패 - 받은 데이터가 없습니다")
        elif downloaded < 1024:
            print(f"[LOG] 경고: 다운로드된 파일이 매우 작음 ({downloaded} bytes)")
            # 작은 파일의 내용을 확인해봄
            try:
                with open(file_path, 'rb') as check_file:
                    content = check_file.read(500)
                    try:
                        text_content = content.decode('utf-8', errors='ignore').lower()
                        if any(indicator in text_content for indicator in ['<html', 'error', '404', '403']):
                            print(f"[LOG] 다운로드된 파일이 에러 페이지임: {text_content[:100]}...")
                            raise Exception(f"다운로드 실패 - 에러 페이지 받음 ({downloaded} bytes)")
                    except:
                        pass
            except:
                pass
        
        mark_proxy_used(db, proxy_addr, success=True)
        
        # WebSocket으로 다운로드 성공 알림
        send_websocket_message("proxy_success", {
            "proxy": proxy_addr,
            "step": "다운로드 완료",
            "url": req.url
        })
        
    except Exception as e:
        error_str = str(e)
        print(f"[LOG] 프록시 다운로드 실패: {e}")
        mark_proxy_used(db, proxy_addr, success=False)
        
        # DNS 오류 감지 시 재파싱 시도 (프록시에서도)
        if any(dns_error in error_str for dns_error in [
            "NameResolutionError", "Failed to resolve", "Name or service not known", 
            "No address associated with hostname", "nodename nor servname provided"
        ]):
            print(f"[LOG] 프록시에서 DNS 해상도 오류 감지 - 다운로드 링크 재파싱 시도")
            print(f"[LOG] 만료된 링크: {direct_link}")
            
            try:
                # 기존 direct_link 완전 초기화
                req.direct_link = None
                db.commit()
                
                # 강제 재파싱 시도 (여러 프록시로 시도)
                print(f"[LOG] 원본 URL로 강제 재파싱 시도: {req.url}")
                new_direct_link, used_proxy = parse_with_proxy_cycling(req, db, force_reparse=True)
                
                if new_direct_link and new_direct_link != direct_link:
                    print(f"[LOG] 프록시에서 DNS 오류 후 재파싱 성공: {new_direct_link}")
                    req.direct_link = new_direct_link
                    db.commit()
                    
                    # 재파싱된 링크로 다시 다운로드 시도
                    if used_proxy:
                        return download_with_proxy(new_direct_link, file_path, used_proxy, initial_size, req, db)
                    else:
                        return download_local(new_direct_link, file_path, initial_size, req, db)
                else:
                    print(f"[LOG] 프록시에서 DNS 오류 후 재파싱 실패 - 프록시 순환으로도 새 링크 획득 불가")
                    
            except Exception as reparse_error:
                print(f"[LOG] 프록시에서 DNS 오류 후 재파싱 중 예외: {reparse_error}")
                
                # 마지막 시도: 로컬 연결로 재파싱
                try:
                    print(f"[LOG] 마지막 시도: 로컬 연결로 재파싱")
                    from .parser_service import parse_direct_link_simple
                    local_direct_link = parse_direct_link_simple(req.url, req.password, use_proxy=False)
                    if local_direct_link and local_direct_link != direct_link:
                        print(f"[LOG] 로컬 연결로 재파싱 성공: {local_direct_link}")
                        req.direct_link = local_direct_link
                        db.commit()
                        return download_local(local_direct_link, file_path, initial_size, req, db)
                except Exception as local_error:
                    print(f"[LOG] 로컬 연결 재파싱도 실패: {local_error}")
        
        # WebSocket으로 다운로드 실패 알림
        send_websocket_message("proxy_failed", {
            "proxy": proxy_addr,
            "step": "다운로드 실패",
            "error": str(e),
            "url": req.url
        })
        
        raise e


def download_local(direct_link, file_path, initial_size, req, db):
    """로컬 연결로 다운로드"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Accept-Language': 'ko-KR,ko;q=0.9',
        'Connection': 'keep-alive'
    }
    
    if initial_size > 0:
        headers['Range'] = f'bytes={initial_size}-'
        print(f"[LOG] 이어받기 헤더: Range={headers['Range']}")
    
    try:
        # 다운로드 시작 전 정지 상태 체크
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 시작 전 정지됨: {req.id}")
            return
        
        print(f"[LOG] 로컬 연결로 다운로드 시작")
        
        with requests.get(direct_link, stream=True, headers=headers, timeout=(10, 30)) as response:
            response.raise_for_status()
            
            # 응답 받은 후 정지 상태 체크
            db.refresh(req)
            if req.status == StatusEnum.stopped:
                print(f"[LOG] 응답 받은 후 정지됨: {req.id}")
                return
            
            content_length = int(response.headers.get('Content-Length', 0))
            content_type = response.headers.get('Content-Type', '').lower()
            
            # Content-Disposition에서 실제 파일명 추출 시도 (로컬)
            content_disposition = response.headers.get('Content-Disposition', '')
            if content_disposition and 'filename' in content_disposition:
                import re
                # filename="..." 또는 filename*=UTF-8''... 형태 처리
                filename_match = re.search(r'filename[*]?=(?:UTF-8\'\')?["\']?([^"\';\r\n]*)["\']?', content_disposition)
                if filename_match:
                    extracted_filename = filename_match.group(1).strip()
                    # URL 디코딩
                    from urllib.parse import unquote
                    extracted_filename = unquote(extracted_filename)
                    
                    # 임시 파일명이거나 파일명이 확정되지 않은 경우에만 업데이트
                    if (req.file_name.endswith('.tmp') or req.file_name == '1fichier.com: Cloud Storage' or 
                        req.file_name.startswith('1fichier_')):
                        print(f"[LOG] 로컬 Content-Disposition에서 실제 파일명 추출: '{extracted_filename}'")
                        req.file_name = extracted_filename
                        db.commit()
                        
                        # WebSocket으로 파일명 업데이트 전송
                        send_websocket_message("filename_update", {
                            "id": req.id,
                            "file_name": req.file_name,
                            "url": req.url,
                            "status": req.status.value if hasattr(req.status, 'value') else str(req.status)
                        })
            
            # 응답 검증: HTML이나 빈 파일인지 확인
            print(f"[LOG] 로컬 응답 분석 - Content-Length: {content_length}, Content-Type: {content_type}")
            
            # Content-Type이 HTML인 경우 - 내용을 확인해서 실제 HTML인지 판단
            if 'text/html' in content_type:
                print(f"[LOG] HTML Content-Type 감지 - 내용 검사 중...")
                # 처음 1024바이트를 확인해서 실제 HTML인지 판단
                peek_content = response.content[:1024] if hasattr(response, 'content') else b''
                try:
                    peek_text = peek_content.decode('utf-8', errors='ignore').lower()
                    # 실제 HTML 태그와 에러 메시지가 있는지 확인
                    html_indicators = ['<html', '<body', '<head', '<!doctype']
                    error_indicators = ['error', '404', '403', 'not found', 'access denied', 'forbidden']
                    
                    has_html_tags = any(indicator in peek_text for indicator in html_indicators)
                    has_error_msg = any(indicator in peek_text for indicator in error_indicators)
                    
                    # HTML 태그가 있고 에러 메시지도 있으면 실제 에러 페이지
                    if has_html_tags and has_error_msg:
                        print(f"[LOG] 실제 HTML 에러 페이지 감지: {peek_text[:100]}...")
                        raise Exception("다운로드 링크가 에러 페이지로 리다이렉트됨 (HTML 응답)")
                    elif has_html_tags:
                        print(f"[LOG] HTML 페이지지만 에러가 아닐 수 있음 - 계속 진행")
                    else:
                        print(f"[LOG] HTML Content-Type이지만 실제 파일 데이터로 보임 - 계속 진행")
                except:
                    print(f"[LOG] HTML 내용 검사 실패 - 계속 진행")
                    pass
            
            # Content-Length가 너무 작은 경우 (1KB 미만)
            if content_length < 1024 and initial_size == 0:
                print(f"[LOG] 파일 크기가 너무 작음: {content_length} bytes - 에러 응답일 가능성")
                # 작은 응답의 내용을 확인해봄
                peek_content = response.content[:500]  # 처음 500바이트만 확인
                try:
                    peek_text = peek_content.decode('utf-8', errors='ignore').lower()
                    # HTML 태그나 에러 메시지가 포함되어 있는지 확인
                    error_indicators = ['<html', '<body', 'error', '404', '403', 'not found', 'access denied']
                    if any(indicator in peek_text for indicator in error_indicators):
                        print(f"[LOG] 응답에 에러 내용 감지: {peek_text[:100]}...")
                        raise Exception(f"다운로드 실패 - 에러 응답 감지 (크기: {content_length} bytes)")
                except:
                    pass  # 디코딩 실패해도 계속 진행
            
            if initial_size > 0:
                # 이어받기: 전체 크기 = 기존 크기 + 남은 크기
                total_size = initial_size + content_length
                print(f"[LOG] 이어받기 - 기존: {initial_size}, 남은 크기: {content_length}")
            else:
                # 새 다운로드: 전체 크기 = Content-Length
                total_size = content_length
            
            # 파일 크기가 0인 경우 다운로드 중단
            if total_size == 0:
                print(f"[LOG] 파일 크기가 0 - 다운로드 중단")
                raise Exception("파일 크기가 0입니다. 다운로드 링크가 올바르지 않습니다.")
            
            req.total_size = total_size
            db.commit()
            
            print(f"[LOG] 로컬 다운로드 시작 - 총 크기: {total_size} bytes, Content-Type: {content_type}")
            
            # 파일 경로 검증 및 디렉토리 생성
            try:
                download_path = Path(file_path).parent
                download_path.mkdir(parents=True, exist_ok=True)
                print(f"[LOG] 파일 저장 경로: {file_path}")
            except Exception as e:
                raise Exception(f"다운로드 디렉토리 생성 실패: {e}")
            
            try:
                with open(file_path, 'ab' if initial_size > 0 else 'wb') as f:
                    downloaded = initial_size
                    last_update_size = downloaded
                    
                    chunk_count = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            chunk_count += 1
                            
                            # 매 64KB마다(8개 청크) 정지 상태 체크
                            if chunk_count % 8 == 0:
                                db.refresh(req)
                                if req.status == StatusEnum.stopped:
                                    print(f"[LOG] 다운로드 중 정지됨: {req.id} (진행률: {downloaded}/{total_size})")
                                    return
                            
                            # 진행률 업데이트 - 적절한 빈도 (매 512KB마다) + WebSocket 실시간 전송  
                            # 진행률 및 속도 계산
                            # 안전한 진행률 계산 (NaN 방지)
                            try:
                                if total_size > 0 and downloaded >= 0:
                                    progress = (downloaded / total_size * 100)
                                    # NaN 체크
                                    if not (0 <= progress <= 100):
                                        progress = 0.0
                                else:
                                    progress = 0.0
                            except (ZeroDivisionError, TypeError, ValueError):
                                progress = 0.0
                            current_percent_for_log = int(progress // 5) * 5  # 5% 단위 (로그용)
                            current_percent_for_ui = int(progress * 2) / 2  # 0.5% 단위 (UI 업데이트용)
                            
                            # 속도 계산을 위한 시간 추적
                            current_time = time.time()
                            if not hasattr(req, '_local_speed_start_time'):
                                req._local_speed_start_time = current_time
                                req._local_speed_start_bytes = downloaded
                            
                            if downloaded - last_update_size >= 10485760 or current_percent_for_ui != getattr(req, '_last_ui_percent', 0):  # 10MB마다 또는 0.5% 단위로 업데이트
                                req.downloaded_size = downloaded
                                db.commit()
                                last_update_size = downloaded
                                
                                # 5% 단위로만 로그 출력 (속도 포함)
                                if current_percent_for_log != getattr(req, '_last_logged_percent', 0) and current_percent_for_log % 5 == 0 and current_percent_for_log > 0:
                                    req._last_logged_percent = current_percent_for_log
                                    # 속도 계산 (로그용)
                                    time_elapsed = current_time - req._local_speed_start_time
                                    if time_elapsed > 0:
                                        bytes_diff = downloaded - req._local_speed_start_bytes
                                        download_speed = bytes_diff / time_elapsed
                                        speed_mb = download_speed / (1024 * 1024)
                                        print(f"[LOG] 로컬 진행률: {current_percent_for_log}% ({downloaded}/{total_size}) - 속도: {speed_mb:.2f}MB/s")
                                        req._local_speed_start_time = current_time
                                        req._local_speed_start_bytes = downloaded
                                
                                # 0.5% 단위로 WebSocket 업데이트 (화면 업데이트)
                                if current_percent_for_ui != getattr(req, '_last_ui_percent', 0):
                                    req._last_ui_percent = current_percent_for_ui
                                    
                                    # 속도는 2% 단위로만 업데이트 (더 안정적)
                                    current_percent_for_speed = int(progress // 2) * 2
                                    download_speed = getattr(req, '_last_local_download_speed', 0)
                                    
                                    if current_percent_for_speed != getattr(req, '_last_local_speed_percent', 0):
                                        req._last_local_speed_percent = current_percent_for_speed
                                        # 속도 계산 (첫 1분은 2초, 이후 4초 간격)
                                        speed_time_elapsed = current_time - getattr(req, '_local_ui_speed_time', current_time - 4)
                                        download_start_time = getattr(req, '_local_download_start_time', current_time)
                                        is_initial_phase = (current_time - download_start_time) < 60  # 첫 1분
                                        
                                        min_interval = 2.0 if is_initial_phase else 4.0
                                        if speed_time_elapsed >= min_interval or not hasattr(req, '_local_ui_speed_time'):
                                            speed_bytes_diff = downloaded - getattr(req, '_local_ui_speed_bytes', downloaded)
                                            if speed_time_elapsed > 0 and speed_bytes_diff > 0:
                                                download_speed = speed_bytes_diff / speed_time_elapsed
                                            elif not hasattr(req, '_local_ui_speed_time'):
                                                # 첫 측정시에는 기본값
                                                download_speed = 0
                                            req._local_ui_speed_time = current_time
                                            req._local_ui_speed_bytes = downloaded
                                            req._last_local_download_speed = download_speed
                                            if not hasattr(req, '_local_download_start_time'):
                                                req._local_download_start_time = current_time
                                    
                                    send_websocket_message("progress_update", {
                                        "id": req.id,
                                        "downloaded_size": downloaded,
                                        "total_size": total_size,
                                        "progress": round(max(0.0, min(100.0, progress or 0.0)), 1),
                                        "download_speed": round(download_speed, 0),
                                        "status": "downloading"
                                    })
                    
                    req.downloaded_size = downloaded
                    db.commit()
                
            except Exception as file_error:
                raise Exception(f"파일 쓰기 실패: {file_error}")
                
        print(f"[LOG] 로컬 다운로드 완료: {downloaded} bytes")
        
        # 다운로드 완료 후 파일 검증
        if downloaded == 0:
            print(f"[LOG] 경고: 다운로드된 데이터가 0 bytes")
            raise Exception("다운로드 실패 - 받은 데이터가 없습니다")
        # Content-Type으로 잘못된 파일 감지 (용량은 체크하지 않음)
        content_type = response.headers.get('Content-Type', '').lower()
        if any(wrong_type in content_type for wrong_type in ['text/html', 'text/css', 'text/javascript', 'application/json']):
            raise Exception(f"잘못된 파일 타입 다운로드: {content_type} ({downloaded} bytes)")
        elif downloaded < 1024:  # 1KB 미만은 확실히 문제
            print(f"[LOG] 경고: 다운로드된 파일이 매우 작음 ({downloaded} bytes)")
            # 작은 파일의 내용을 확인해봄
            try:
                with open(file_path, 'rb') as check_file:
                    content = check_file.read(500)
                    try:
                        text_content = content.decode('utf-8', errors='ignore').lower()
                        if any(indicator in text_content for indicator in ['<html', 'error', '404', '403']):
                            print(f"[LOG] 다운로드된 파일이 에러 페이지임: {text_content[:100]}...")
                            raise Exception(f"다운로드 실패 - 에러 페이지 받음 ({downloaded} bytes)")
                    except:
                        pass
            except:
                pass
        
    except Exception as e:
        error_str = str(e)
        print(f"[LOG] 로컬 다운로드 실패: {e}")
        
        # DNS 오류 감지 시 재파싱 시도
        if any(dns_error in error_str for dns_error in [
            "NameResolutionError", "Failed to resolve", "Name or service not known", 
            "No address associated with hostname", "nodename nor servname provided"
        ]):
            print(f"[LOG] DNS 해상도 오류 감지 - 다운로드 링크 재파싱 시도")
            print(f"[LOG] 만료된 링크: {direct_link}")
            
            try:
                # 기존 direct_link 완전 초기화
                req.direct_link = None
                db.commit()
                
                # 우선 로컬 연결로 재파싱 시도
                print(f"[LOG] 로컬 연결으로 강제 재파싱 시도: {req.url}")
                from .parser_service import parse_direct_link_simple
                new_direct_link = parse_direct_link_simple(req.url, req.password, use_proxy=False)
                
                if new_direct_link and new_direct_link != direct_link:
                    print(f"[LOG] 로컬 연결 DNS 오류 후 재파싱 성공: {new_direct_link}")
                    req.direct_link = new_direct_link
                    db.commit()
                    return download_local(new_direct_link, file_path, initial_size, req, db)
                else:
                    print(f"[LOG] 로컬 재파싱 실패 - 프록시 순환 시도")
                    
                    # 로컬 재파싱 실패 시 프록시로 시도
                    try:
                        new_direct_link, used_proxy = parse_with_proxy_cycling(req, db, force_reparse=True)
                        if new_direct_link and new_direct_link != direct_link:
                            print(f"[LOG] 프록시 순환으로 재파싱 성공: {new_direct_link}")
                            req.direct_link = new_direct_link
                            db.commit()
                            
                            if used_proxy:
                                return download_with_proxy(new_direct_link, file_path, used_proxy, initial_size, req, db)
                            else:
                                return download_local(new_direct_link, file_path, initial_size, req, db)
                        else:
                            print(f"[LOG] 프록시 순환 재파싱도 실패")
                    except Exception as proxy_error:
                        print(f"[LOG] 프록시 순환 재파싱 중 예외: {proxy_error}")
                        
            except Exception as reparse_error:
                print(f"[LOG] DNS 오류 후 재파싱 중 예외: {reparse_error}")
        
        # WebSocket으로 로컬 다운로드 실패 상태 전송
        send_websocket_message("status_update", {
            "id": req.id,
            "url": req.url,
            "file_name": req.file_name,
            "status": "failed",
            "error": str(e),
            "downloaded_size": req.downloaded_size or 0,
            "total_size": req.total_size or 0,
            "save_path": req.save_path,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "finished_at": None,
            "password": req.password,
            "direct_link": req.direct_link,
            "use_proxy": req.use_proxy
        })
        
        raise e


def download_from_stream(proxy_addr, file_path, initial_size, req, db, use_proxy):
    """직접 다운로드 스트림에서 파일 다운로드"""
    print(f"[LOG] 직접 스트림 다운로드 시작 (프록시: {proxy_addr})")
    
    # 스트림 다운로드는 parser_service에서 이미 시작되었으므로
    # 여기서는 재시도 메커니즘을 구현
    try:
        # 새로운 요청으로 다운로드 재시작
        from .parser_service import get_or_parse_direct_link
        
        if use_proxy and proxy_addr:
            # 프록시 사용하여 다운로드 재시작
            print(f"[LOG] 프록시 {proxy_addr}로 스트림 다운로드 재시작")
            download_with_proxy("STREAM_RETRY", file_path, proxy_addr, initial_size, req, db)
        else:
            # 로컬 연결로 다운로드 재시작
            print(f"[LOG] 로컬 연결로 스트림 다운로드 재시작")
            download_local("STREAM_RETRY", file_path, initial_size, req, db)
            
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


def download_general_file(request_id, language="ko", use_proxy=False):
    """일반 파일 다운로드 (non-1fichier) - URL에서 직접 다운로드"""
    from .db import SessionLocal
    from .models import DownloadRequest, StatusEnum
    from urllib.parse import urlparse, unquote
    import requests
    import re
    
    db = SessionLocal()
    req = None  # 변수 초기화
    
    try:
        # 다운로드 요청 조회
        req = db.query(DownloadRequest).filter(DownloadRequest.id == request_id).first()
        if not req:
            print(f"[LOG] 일반 다운로드 요청을 찾을 수 없음: {request_id}")
            return
        
        print(f"[LOG] 일반 다운로드 시작: {req.url}")
        
        # 먼저 HEAD 요청으로 파일 정보 확인 (파일명 생성 전)
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            head_response = requests.head(req.url, headers=headers, timeout=30, allow_redirects=True)
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
        
        # 파일명이 없으면 임시명 설정
        if not req.file_name or req.file_name.strip() == '':
            req.file_name = f"general_{request_id}.tmp"
            print(f"[LOG] 파일명을 추출할 수 없어 임시명 사용: {req.file_name}")
            
        # Content-Length에서 파일 크기 추출
        content_length = head_response.headers.get('Content-Length')
        if content_length:
            bytes_size = int(content_length)
            
            # 1fichier처럼 포맷팅된 크기를 문자열로 저장
            formatted_size = format_file_size(bytes_size)
            req.file_size = formatted_size
            print(f"[LOG] ★ 파일크기 최초 설정: '{formatted_size}' ({content_length} bytes)")
        
        # 상태를 다운로드 중으로 변경
        req.status = StatusEnum.downloading
        db.commit()
        
        # WebSocket으로 상태 업데이트 알림
        send_websocket_message("status_update", {
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
        
        # 기존 파일 확인
        initial_size = 0
        if part_file_path.exists():
            file_path = part_file_path
            initial_size = part_file_path.stat().st_size
            print(f"[LOG] 이어받기: {initial_size} bytes")
        elif file_path.exists():
            initial_size = file_path.stat().st_size
            print(f"[LOG] 기존 파일 발견: {initial_size} bytes")
        else:
            file_path = part_file_path
            print(f"[LOG] 새 다운로드 시작")
        
        # 실제 다운로드는 기존 다운로드 로직 재사용
        if use_proxy:
            print(f"[LOG] 프록시 모드로 일반 파일 다운로드")
            download_with_proxy_cycling(req.url, file_path, None, initial_size, req, db)
        else:
            print(f"[LOG] 로컬 모드로 일반 파일 다운로드")
            download_local(req.url, file_path, initial_size, req, db)
            
        # 3단계: 완료 처리
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 정지됨 (완료 처리 전): ID {request_id}")
            return

        final_file_path = cleanup_download_file(file_path)

        req.status = StatusEnum.done
        import datetime
        req.finished_at = datetime.datetime.utcnow()
        if final_file_path:
            req.save_path = str(final_file_path)
        db.commit()

        # 텔레그램 알림 전송 (완료)
        unknown_file = get_translations(language).get("telegram_unknown_file", "알 수 없는 파일")
        
        file_size_str = req.file_size or "알 수 없음"
        
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
        
        # WebSocket으로 완료 상태 전송
        send_websocket_message("status_update", {
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
            "direct_link": req.direct_link,
            "use_proxy": req.use_proxy
        })
        
        print(f"[LOG] 일반 다운로드 완료: {req.file_name}")
            
    except Exception as e:
        print(f"[LOG] 일반 다운로드 중 오류: {e}")
        if req:
            req.status = StatusEnum.failed
            req.error_message = str(e)
            db.commit()
        raise e
    finally:
        db.close()


