"""
다운로드 공통 유틸리티 함수들
- 중복 제거를 위해 로컬/프록시 다운로드에서 공통으로 사용하는 함수들
"""

import time
import re
from pathlib import Path
from urllib.parse import unquote
from core.models import StatusEnum
from utils.sse import send_sse_message
from services.download_manager import download_manager


def extract_filename_from_headers(response, req, db):
    """Content-Disposition 헤더에서 파일명 추출"""
    content_disposition = response.headers.get('Content-Disposition', '')
    if content_disposition and 'filename' in content_disposition:
        filename_match = re.search(r'filename[*]?=(?:UTF-8\'\')?["\']?([^"\';\\r\\n]*)["\']?', content_disposition)
        if filename_match:
            extracted_filename = filename_match.group(1).strip()
            extracted_filename = unquote(extracted_filename)
            
            if (req.file_name.endswith('.tmp') or 
                req.file_name == '1fichier.com: Cloud Storage' or 
                req.file_name.startswith('1fichier_')):
                print(f"[LOG] Content-Disposition에서 파일명 추출: '{extracted_filename}'")
                req.file_name = extracted_filename
                db.commit()


def calculate_total_size(initial_size, content_length):
    """총 파일 크기 계산"""
    if initial_size > 0:
        total_size = initial_size + content_length
        print(f"[LOG] 이어받기 - 기존: {initial_size}, 남은 크기: {content_length}")
    else:
        total_size = content_length
    
    if total_size == 0:
        raise Exception("파일 크기가 0입니다. 다운로드 링크가 올바르지 않습니다.")
    
    return total_size


async def download_file_content(response, file_path, initial_size, total_size, req, db):
    """실제 파일 다운로드 수행"""
    downloaded = initial_size
    last_update_size = downloaded
    chunk_count = 0

    try:
        with open(file_path, 'ab' if initial_size > 0 else 'wb') as f:
            async for chunk in response.aiter_bytes(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    chunk_count += 1
                
                if chunk_count % 16 == 0:
                    if download_manager.is_download_stopped(req.id):
                        print(f"[LOG] 다운로드 중 정지 플래그 감지: {req.id}")
                        return downloaded
                    
                    db.refresh(req)
                    if req.status == StatusEnum.stopped:
                        print(f"[LOG] 다운로드 중 정지됨: {req.id}")
                        return downloaded
                
                if should_update_progress(downloaded, last_update_size, total_size, req):
                    try:
                        last_update_size = send_progress_update(
                            downloaded, total_size, last_update_size, req, db
                        )
                    except Exception as sse_error:
                        print(f"[WARNING] SSE 업데이트 실패: {sse_error}")
                        last_update_size = downloaded

            print(f"[LOG] 파일 다운로드 완료: {downloaded} bytes")

    except Exception as e:
        print(f"[ERROR] 다운로드 중 오류: {e}")
        print(f"[ERROR] 오류 타입: {type(e).__name__}")
        raise

    req.downloaded_size = downloaded
    db.commit()
    return downloaded


def should_update_progress(downloaded, last_update_size, total_size, req):
    """진행률 업데이트가 필요한지 확인 - 순수 시간 기반"""
    current_time = time.time()
    last_update_time = getattr(req, '_last_sse_send_time', 0)
    time_since_last_update = current_time - last_update_time

    # 시간 기반으로만 업데이트 (크기 기반 제거)
    return (
        (downloaded >= total_size) or  # 완료 시 즉시
        (time_since_last_update >= 2.5)  # 2.5초마다 업데이트
    )


def send_progress_update(downloaded, total_size, last_update_size, req, db):
    """진행률 업데이트 전송"""
    progress = (downloaded / total_size * 100) if total_size > 0 else 0.0
    current_time = time.time()
    last_update_time = getattr(req, '_last_sse_send_time', current_time)
    time_diff = current_time - last_update_time

    # 속도 계산 개선
    if time_diff > 0 and downloaded > last_update_size:
        size_diff = downloaded - last_update_size
        download_speed = (size_diff / 1024) / time_diff  # KB/s

        # 속도 변수 업데이트
        if hasattr(req, '_last_proxy_download_speed'):
            req._last_proxy_download_speed = download_speed
        else:
            req._last_local_download_speed = download_speed

        req._last_sse_send_time = current_time
    else:
        # 이전 속도 사용
        speed_attr = '_last_proxy_download_speed' if hasattr(req, '_last_proxy_download_speed') else '_last_local_download_speed'
        download_speed = getattr(req, speed_attr, 0)

    # 속도가 너무 작으면 0으로 표시
    if download_speed < 0.1:
        download_speed = 0
    
    send_sse_message("status_update", {
        "id": req.id,
        "downloaded_size": downloaded,
        "total_size": total_size,
        "progress": round(min(100.0, progress), 1),  # 100% 초과 방지
        "speed": f"{round(download_speed, 0)} KB/s" if download_speed > 0 else "0 KB/s",
        "status": "downloading"
    })
    
    if downloaded - getattr(req, '_last_db_update_size', 0) >= 1024 * 1024:
        req.downloaded_size = downloaded
        db.commit()
        req._last_db_update_size = downloaded
    
    return downloaded


def validate_downloaded_file(downloaded, content_type, file_path):
    """다운로드된 파일 검증"""
    if downloaded == 0:
        raise Exception("다운로드 실패 - 받은 데이터가 없습니다")
    
    if any(wrong_type in content_type for wrong_type in ['text/html', 'text/css', 'text/javascript', 'application/json']):
        raise Exception(f"잘못된 파일 타입 다운로드: {content_type} ({downloaded} bytes)")
    
    if downloaded < 1024:
        print(f"[LOG] 경고: 다운로드된 파일이 매우 작음 ({downloaded} bytes)")
        try:
            with open(file_path, 'rb') as check_file:
                check_content = check_file.read(512)
                check_text = check_content.decode('utf-8', errors='ignore').lower()
                error_patterns = ['<html', '<body', 'error', '404', '403', 'not found', 'access denied']
                if any(pattern in check_text for pattern in error_patterns):
                    raise Exception(f"다운로드된 파일이 에러 페이지입니다 ({downloaded} bytes)")
        except UnicodeDecodeError:
            pass
        except Exception as check_error:
            print(f"[LOG] 파일 내용 확인 중 오류: {check_error}")


def check_file_resume_status(file_path, initial_size, req):
    """파일 이어받기 상태 검사"""
    if not file_path.exists():
        return "new_download", 0
    
    current_size = file_path.stat().st_size
    
    # 100% 다운로드된 경우
    if req.total_size and current_size >= req.total_size:
        print(f"[LOG] 파일이 이미 100% 다운로드 완료: {current_size}/{req.total_size}")
        return "completed", current_size
    
    # 이어받기 가능성 검사
    if current_size > 0 and initial_size > 0:
        # 이어받기를 시도할 수 있는 상황
        print(f"[LOG] 이어받기 가능 - 현재 크기: {current_size}, 초기 크기: {initial_size}")
        return "resume_attempt", current_size
    elif current_size > 0:
        # 파일이 있지만 이어받기 설정이 없는 경우
        print(f"[LOG] 기존 파일 발견 - 크기: {current_size}")
        return "existing_file", current_size
    
    return "new_download", 0