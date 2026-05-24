"""
Common download utility functions
- Functions shared by local/proxy downloads to remove duplication
"""

import asyncio
import time
import re
import os
from pathlib import Path
from urllib.parse import unquote
from sqlalchemy import and_
from core.models import StatusEnum, DownloadRequest
from core.config import get_download_path
from utils.sse import send_sse_message
from services.sse_manager import sse_manager
# The legacy synchronous download manager has been removed


def generate_file_path(filename, is_temporary=True):
    """Generate a file save path"""
    download_dir = get_download_path()

    # Convert to a safe file name
    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    file_path = download_dir / safe_filename

    # Handle duplicate file names
    counter = 1
    original_path = file_path
    while file_path.exists() or (file_path.with_suffix(file_path.suffix + '.part').exists() if not is_temporary else False):
        stem = original_path.stem
        suffix = original_path.suffix
        file_path = original_path.parent / f"{stem}({counter}){suffix}"
        counter += 1

    # Add the .part extension while downloading
    if is_temporary:
        file_path = file_path.with_suffix(file_path.suffix + '.part')

    return str(file_path)


def get_final_file_path(temp_file_path):
    """Generate the final file path from the temporary file (.part)"""
    if temp_file_path.endswith('.part'):
        return temp_file_path[:-5]  # remove .part
    return temp_file_path


def extract_filename_from_headers(response, req, db):
    """Extract the file name from the Content-Disposition header"""
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
    """Calculate the total file size"""
    if initial_size > 0:
        total_size = initial_size + content_length
        print(f"[LOG] 이어받기 - 기존: {initial_size}, 남은 크기: {content_length}")
    else:
        total_size = content_length

    if total_size == 0:
        raise Exception("파일 크기가 0입니다. 다운로드 링크가 올바르지 않습니다.")

    return total_size


async def download_file_content(response, file_path, initial_size, total_size, req, db):
    """Perform the actual file download"""
    downloaded = initial_size
    last_update_size = downloaded
    chunk_count = 0

    try:
        with open(file_path, 'ab' if initial_size > 0 else 'wb') as f:
            async for chunk in response.content.iter_chunked(8192):
                if chunk:
                    try:
                        f.write(chunk)
                        downloaded += len(chunk)
                        chunk_count += 1
                    except OSError as write_error:
                        # Detect file-write errors such as disk space exhaustion
                        error_msg = str(write_error).lower()
                        if any(keyword in error_msg for keyword in ['disk full', 'no space', 'not enough space', 'insufficient disk space', 'space remaining', '28']):
                            print(f"[ERROR] 디스크 용량 부족: {write_error}")

                            # Stop all pending downloads
                            try:

                                # Change all pending and downloading requests to stopped
                                pending_downloads = db.query(DownloadRequest).filter(
                                    and_(
                                        DownloadRequest.id != req.id,  # exclude the currently failed download
                                        DownloadRequest.status.in_([StatusEnum.pending, StatusEnum.downloading, StatusEnum.parsing])
                                    )
                                ).all()

                                stopped_count = 0
                                for download in pending_downloads:
                                    download.status = StatusEnum.stopped
                                    download.error = "디스크 용량 부족으로 인한 자동 정지"
                                    stopped_count += 1

                                if stopped_count > 0:
                                    db.commit()
                                    print(f"[LOG] 디스크 용량 부족으로 {stopped_count}개 다운로드 자동 정지")

                                    # Send updates over SSE for the stopped downloads
                                    from services.sse_manager import sse_manager
                                    import asyncio
                                    loop = asyncio.get_event_loop()
                                    if loop.is_running():
                                        for download in pending_downloads:
                                            loop.create_task(sse_manager.broadcast_message("status_update", {
                                                "id": download.id,
                                                "status": "stopped",
                                                "message": "디스크 용량 부족으로 인한 자동 정지"
                                            }))

                            except Exception as stop_error:
                                print(f"[WARNING] 대기중 다운로드 정지 실패: {stop_error}")

                            # Get the error message in the user's language
                            try:
                                from core.config import get_config
                                from core.i18n import get_translations
                                config = get_config()
                                user_language = config.get("language", "ko")
                                translations = get_translations(user_language)
                                disk_full_msg = translations.get("disk_full_error", "디스크 용량이 부족합니다. 저장 공간을 확보한 후 다시 시도해주세요.")
                                raise Exception(disk_full_msg)
                            except Exception:
                                # Default message if translation loading fails
                                raise Exception("디스크 용량이 부족합니다. 저장 공간을 확보한 후 다시 시도해주세요.")
                        else:
                            print(f"[ERROR] 파일 쓰기 오류: {write_error}")
                            raise Exception(f"파일 쓰기 실패: {str(write_error)}")
                    except Exception as write_error:
                        print(f"[ERROR] 파일 쓰기 중 알 수 없는 오류: {write_error}")
                        raise

                # Performance improvement: widen the check interval (every 128 chunks = every 1MB)
                if chunk_count % 128 == 0:
                    # Check for a download stop
                    db.refresh(req)
                    if req.status == StatusEnum.stopped:
                        print(f"[LOG] 다운로드 중 정지됨: {req.id}")

                        # Send a stopped-status SSE
                        try:

                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                loop.create_task(sse_manager.broadcast_message("status_update", {
                                    "id": req.id,
                                    "status": "stopped",
                                    "progress": round((downloaded / total_size * 100), 1) if total_size > 0 else 0,
                                    "download_speed": 0,  # explicitly set speed to 0 when stopped
                                    "message": "다운로드가 중지되었습니다."
                                }))
                        except Exception as sse_error:
                            print(f"[WARNING] 정지 상태 SSE 전송 실패: {sse_error}")

                        return downloaded

                    # Check whether a progress update is needed
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
    """Check whether a progress update is needed - optimized interval"""
    current_time = time.time()
    last_update_time = getattr(req, '_last_sse_send_time', 0)
    time_since_last_update = current_time - last_update_time

    # On the first update, or immediately on completion, otherwise every 3 seconds (a reasonable interval)
    should_update = (
        (last_update_time == 0) or  # first update
        (downloaded >= total_size) or  # immediately on completion
        (time_since_last_update >= 3.0)  # update every 3 seconds (so it doesn't change too often)
    )

    # Progress-update logging removed (too noisy)

    return should_update


def send_progress_update(downloaded, total_size, last_update_size, req, db):
    """Send a progress update"""
    progress = (downloaded / total_size * 100) if total_size > 0 else 0.0
    current_time = time.time()
    last_update_time = getattr(req, '_last_sse_send_time', 0)
    time_diff = current_time - last_update_time

    # Check the speed-calculation conditions

    # Improved speed calculation (computed in bytes per second)
    if time_diff > 0 and downloaded > last_update_size:
        size_diff = downloaded - last_update_size
        new_speed = size_diff / time_diff  # B/s (matches the frontend formatSpeed)

        # Apply smoothing with the previous speed (avoid abrupt changes)
        speed_attr = '_last_proxy_download_speed' if hasattr(req, '_last_proxy_download_speed') else '_last_local_download_speed'
        prev_speed = getattr(req, speed_attr, new_speed)

        if prev_speed > 0:
            # Smooth with a weighted average (70% previous speed + 30% new speed)
            download_speed = prev_speed * 0.7 + new_speed * 0.3
        else:
            download_speed = new_speed

        # Update the speed variable
        if hasattr(req, '_last_proxy_download_speed'):
            req._last_proxy_download_speed = download_speed
        else:
            req._last_local_download_speed = download_speed

        req._last_sse_send_time = current_time
        # Speed calculation done
    else:
        # Skip the speed calculation
        # On the first update, or reuse the previous speed
        if last_update_time == 0:
            # First update: estimate and compute the speed
            if time_diff > 0.1 and downloaded > 0:  # if at least 0.1s has elapsed and there is data
                download_speed = downloaded / time_diff
                print(f"[DEBUG] 첫 번째 업데이트: 추정 속도 {download_speed:.0f} B/s")
            else:
                download_speed = 0
                # First update: speed cannot be computed
            req._last_sse_send_time = current_time
        else:
            # Keep the previous speed as-is (display stably until stop)
            speed_attr = '_last_proxy_download_speed' if hasattr(req, '_last_proxy_download_speed') else '_last_local_download_speed'
            download_speed = getattr(req, speed_attr, 0)
            # Keep the previous speed

    # If the speed is too small, show it as 0 (10 B/s or less)
    if download_speed < 10:
        download_speed = 0

    # Update the speed variable (store it even if 0)
    speed_attr = '_last_proxy_download_speed' if hasattr(req, '_last_proxy_download_speed') else '_last_local_download_speed'
    setattr(req, speed_attr, download_speed)

    # Use the sse_manager
    try:

        # Asynchronous SSE send
        sse_data = {
            "id": req.id,
            "downloaded_size": downloaded,
            "total_size": total_size,
            "progress": round(min(100.0, progress), 1),
            "download_speed": int(download_speed) if download_speed > 0 else 0,
            "status": "downloading"
        }

        # SSE send-data logging removed (too noisy)

        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(sse_manager.broadcast_message("status_update", sse_data))
    except Exception as sse_error:
        print(f"[WARNING] SSE 진행률 전송 실패: {sse_error}")
    
    # Optimize the database update too (every 5 seconds)
    last_db_update_time = getattr(req, '_last_db_update_time', 0)
    if current_time - last_db_update_time >= 5.0 or downloaded >= total_size:
        req.downloaded_size = downloaded
        db.commit()
        req._last_db_update_time = current_time
    
    return downloaded


def validate_downloaded_file(downloaded, content_type, file_path):
    """Validate the downloaded file"""
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
    """Check the file resume status"""
    if not file_path.exists():
        return "new_download", 0

    current_size = file_path.stat().st_size

    # When the file is already 100% downloaded
    if req.total_size and current_size >= req.total_size:
        print(f"[LOG] 파일이 이미 100% 다운로드 완료: {current_size}/{req.total_size}")
        return "completed", current_size

    # Check whether resuming is possible
    if current_size > 0 and initial_size > 0:
        # A situation where a resume can be attempted
        print(f"[LOG] 이어받기 가능 - 현재 크기: {current_size}, 초기 크기: {initial_size}")
        return "resume_attempt", current_size
    elif current_size > 0:
        # The file exists but there is no resume setting
        print(f"[LOG] 기존 파일 발견 - 크기: {current_size}")
        return "existing_file", current_size
    
    return "new_download", 0