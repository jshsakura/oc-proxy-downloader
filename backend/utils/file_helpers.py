"""
다운로드 공통 유틸리티 함수들
- 중복 제거를 위해 로컬/프록시 다운로드에서 공통으로 사용하는 함수들
"""

import time
import re
import os
from pathlib import Path
from urllib.parse import unquote
from core.models import StatusEnum
from core.config import get_download_path
from utils.sse import send_sse_message
# 기존 동기 다운로드 매니저 제거됨


def generate_file_path(filename, is_temporary=True):
    """파일 저장 경로 생성"""
    download_dir = get_download_path()

    # 안전한 파일명으로 변환
    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    file_path = download_dir / safe_filename

    # 중복 파일명 처리
    counter = 1
    original_path = file_path
    while file_path.exists() or (file_path.with_suffix(file_path.suffix + '.part').exists() if not is_temporary else False):
        stem = original_path.stem
        suffix = original_path.suffix
        file_path = original_path.parent / f"{stem}({counter}){suffix}"
        counter += 1

    # 다운로드 중에는 .part 확장자 추가
    if is_temporary:
        file_path = file_path.with_suffix(file_path.suffix + '.part')

    return str(file_path)


def get_final_file_path(temp_file_path):
    """임시 파일(.part)에서 최종 파일 경로 생성"""
    if temp_file_path.endswith('.part'):
        return temp_file_path[:-5]  # .part 제거
    return temp_file_path


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
            async for chunk in response.content.iter_chunked(8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    chunk_count += 1
                
                # 성능 개선: 체크 간격을 늘림 (128개 청크마다 = 1MB마다)
                if chunk_count % 128 == 0:
                    # 다운로드 중지 체크
                    db.refresh(req)
                    if req.status == StatusEnum.stopped:
                        print(f"[LOG] 다운로드 중 정지됨: {req.id}")

                        # 정지 상태 SSE 전송
                        try:
                            from services.sse_manager import sse_manager
                            import asyncio

                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                loop.create_task(sse_manager.broadcast_message("status_update", {
                                    "id": req.id,
                                    "status": "stopped",
                                    "progress": round((downloaded / total_size * 100), 1) if total_size > 0 else 0,
                                    "message": "다운로드가 중지되었습니다."
                                }))
                        except Exception as sse_error:
                            print(f"[WARNING] 정지 상태 SSE 전송 실패: {sse_error}")

                        return downloaded

                    # 진행률 업데이트 체크
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
    """진행률 업데이트가 필요한지 확인 - 최적화된 간격"""
    current_time = time.time()
    last_update_time = getattr(req, '_last_sse_send_time', 0)
    time_since_last_update = current_time - last_update_time

    # 첫 번째 업데이트이거나, 완료 시 즉시, 그외에는 2초마다
    should_update = (
        (last_update_time == 0) or  # 첫 번째 업데이트
        (downloaded >= total_size) or  # 완료 시 즉시
        (time_since_last_update >= 2.0)  # 2초마다 업데이트 (속도 표시 개선)
    )

    print(f"[DEBUG] should_update_progress: last_time={last_update_time}, time_diff={time_since_last_update:.2f}, should_update={should_update}")

    return should_update


def send_progress_update(downloaded, total_size, last_update_size, req, db):
    """진행률 업데이트 전송"""
    progress = (downloaded / total_size * 100) if total_size > 0 else 0.0
    current_time = time.time()
    last_update_time = getattr(req, '_last_sse_send_time', 0)
    time_diff = current_time - last_update_time

    # 속도 계산 디버깅
    print(f"[DEBUG] 속도 계산 조건: time_diff={time_diff:.2f}, downloaded={downloaded}, last_update_size={last_update_size}")

    # 속도 계산 개선 (bytes per second로 계산)
    if time_diff > 0 and downloaded > last_update_size:
        size_diff = downloaded - last_update_size
        download_speed = size_diff / time_diff  # B/s (프론트엔드 formatSpeed에 맞춤)

        # 속도 변수 업데이트
        if hasattr(req, '_last_proxy_download_speed'):
            req._last_proxy_download_speed = download_speed
        else:
            req._last_local_download_speed = download_speed

        req._last_sse_send_time = current_time
        print(f"[DEBUG] 속도 계산: {size_diff} bytes in {time_diff:.2f}s = {download_speed:.0f} B/s")
    else:
        print(f"[DEBUG] 속도 계산 건너뜀 - 조건 불만족")
        # 첫 번째 업데이트이거나 이전 속도 사용
        if last_update_time == 0:
            # 첫 번째 업데이트: 속도 0으로 시작
            download_speed = 0
            req._last_sse_send_time = current_time
            print(f"[DEBUG] 첫 번째 업데이트: 속도 0으로 설정")
        else:
            # 이전 속도 사용
            speed_attr = '_last_proxy_download_speed' if hasattr(req, '_last_proxy_download_speed') else '_last_local_download_speed'
            download_speed = getattr(req, speed_attr, 0)
            print(f"[DEBUG] 이전 속도 사용: {download_speed:.0f} B/s")

    # 속도가 너무 작으면 0으로 표시 (10 B/s 이하)
    if download_speed < 10:
        download_speed = 0
        print(f"[DEBUG] 속도가 너무 낮음: {download_speed} B/s -> 0으로 설정")
    else:
        print(f"[DEBUG] 최종 속도: {download_speed:.0f} B/s")
    
    # sse_manager를 import 해서 사용
    try:
        from services.sse_manager import sse_manager
        import asyncio

        # 비동기 SSE 전송
        sse_data = {
            "id": req.id,
            "downloaded_size": downloaded,
            "total_size": total_size,
            "progress": round(min(100.0, progress), 1),
            "download_speed": int(download_speed) if download_speed > 0 else 0,
            "status": "downloading"
        }

        print(f"[DEBUG] SSE 전송 데이터: {sse_data}")

        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(sse_manager.broadcast_message("status_update", sse_data))
    except Exception as sse_error:
        print(f"[WARNING] SSE 진행률 전송 실패: {sse_error}")
    
    # 데이터베이스 업데이트도 최적화 (5초마다)
    last_db_update_time = getattr(req, '_last_db_update_time', 0)
    if current_time - last_db_update_time >= 5.0 or downloaded >= total_size:
        req.downloaded_size = downloaded
        db.commit()
        req._last_db_update_time = current_time
    
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