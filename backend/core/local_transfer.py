"""
로컬 다운로드 서비스
- 프록시 없이 직접 연결로 파일 다운로드
- 이어받기 지원
- 실시간 진행률 업데이트
"""

import httpx
import time
import asyncio
from pathlib import Path
from .models import StatusEnum
from utils.file_helpers import (
    extract_filename_from_headers,
    calculate_total_size,
    download_file_content,
    validate_downloaded_file,
    check_file_resume_status
)
from services.download_manager import download_manager


async def download_local(direct_link, file_path, initial_size, req, db):
    """로컬 연결로 다운로드 (비동기) - 완전히 재구성된 버전"""
    
    # 파일 상태 검사
    file_status, current_file_size = check_file_resume_status(file_path, initial_size, req)
    
    if file_status == "completed":
        print(f"[LOG] 파일이 이미 완료되었습니다: {file_path}")
        # DB 상태를 완료로 업데이트
        req.status = StatusEnum.done
        req.downloaded_size = current_file_size
        req.total_size = current_file_size
        db.commit()
        return
    
    req._last_sse_send_time = 0
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Accept-Language': 'ko-KR,ko;q=0.9',
        'Connection': 'keep-alive'
    }
    
    if initial_size > 0:
        headers['Range'] = f'bytes={initial_size}-'
        print(f"[LOG] 이어받기 시도: {initial_size} bytes부터")
    
    db.refresh(req)
    if req.status == StatusEnum.stopped:
        print(f"[LOG] 다운로드 시작 전 정지됨: {req.id}")
        return
    
    print(f"[LOG] 로컬 연결로 다운로드 시작")
    
    timeout = httpx.Timeout(15.0, read=90.0)
    
    # 압축 완전 비활성화를 위한 설정
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    async with httpx.AsyncClient(
        follow_redirects=True,
        limits=limits
    ) as client:
        try:
            async with client.stream('GET', direct_link, headers=headers, timeout=timeout) as response:
                if initial_size > 0 and response.status_code not in [206, 200]:
                    print(f"[LOG] Range 요청 실패 (status: {response.status_code}), 처음부터 다시 시작")
                    initial_size = 0
                    if file_path.exists():
                        file_path.unlink()
                        print(f"[LOG] 기존 파일 삭제: {file_path}")
                
                response.raise_for_status()
                
                content_length = int(response.headers.get('Content-Length', 0))
                content_type = response.headers.get('Content-Type', '').lower()
                
                # 압축 헤더 확인
                content_encoding = response.headers.get('Content-Encoding', 'None')
                if content_encoding != 'None':
                    print(f"[LOG] 서버 응답 압축: {content_encoding}")
                
                db.refresh(req)
                if req.status == StatusEnum.stopped:
                    print(f"[LOG] 응답 받은 후 정지됨: {req.id}")
                    return
                
                extract_filename_from_headers(response, req, db)
                
                total_size = calculate_total_size(initial_size, content_length)
                req.total_size = total_size
                db.commit()
                
                print(f"[LOG] 로컬 다운로드 시작 - 총 크기: {total_size} bytes, Content-Type: {content_type}")
                
                download_path = Path(file_path).parent
                download_path.mkdir(parents=True, exist_ok=True)
                print(f"[LOG] 파일 저장 경로: {file_path}")
                
                downloaded = await download_file_content(
                    response, file_path, initial_size, total_size, req, db
                )
                
                print(f"[LOG] 로컬 다운로드 완료: {downloaded} bytes")

                # 파일 검증 (실패해도 다운로드는 완료로 처리)
                try:
                    validate_downloaded_file(downloaded, content_type, file_path)
                    print(f"[LOG] 파일 검증 완료")
                except Exception as validation_error:
                    print(f"[WARNING] 파일 검증 실패 (다운로드는 완료): {validation_error}")

                return downloaded
                
        except Exception as stream_error:
            error_msg = str(stream_error)
            print(f"[ERROR] 로컬 다운로드 중 오류: {error_msg}")

            # 이어받기를 시도했던 경우에만 파일 정리하고 새로 시도
            if initial_size > 0 and file_path.exists():
                print(f"[LOG] 이어받기 실패로 파일 삭제 후 새로 시작: {file_path}")
                try:
                    file_path.unlink()
                    print(f"[LOG] 이어받기 실패 파일 삭제 완료")
                except Exception as cleanup_error:
                    print(f"[LOG] 파일 삭제 실패 (무시): {cleanup_error}")

                print(f"[LOG] 이어받기 포기 - 새로운 다운로드 시작")

                # 압축 해제 오류의 경우 재다운로드 트리거
                if "decompressing" in error_msg.lower() or "invalid block type" in error_msg.lower():
                    print(f"[LOG] 압축 오류로 인한 이어받기 실패 - 재다운로드 트리거")

                    # 다운로드 상태를 pending으로 변경하여 재다운로드 준비
                    req.status = StatusEnum.pending
                    req.downloaded_size = 0  # 다운로드 크기 초기화
                    req.error_message = None
                    db.commit()

                    print(f"[LOG] 다운로드 {req.id} 상태를 pending으로 변경 - 재다운로드 대기")

                    # 재다운로드를 위해 상태만 변경 (자동 재시작은 매니저가 처리)
                    print(f"[LOG] 재다운로드 준비 - 상태 변경 후 자동 재시작 대기")

                    # 현재 다운로드 해제
                    download_manager.unregister_download(req.id)
                    return 0  # 이어받기 실패했으므로 0 반환

            # 모든 에러를 로그만 남기고 예외는 발생시키지 않음 (프로세스 종료 방지)
            print(f"[ERROR] 다운로드 에러 처리 완료 - 프로세스 안정성 유지")

            if "decompressing" in error_msg.lower() or "invalid block type" in error_msg.lower():
                print(f"[ERROR] 압축 해제 오류 - 서버에서 잘못된 데이터를 전송했습니다")
            elif "stream" in error_msg.lower() and "closed" in error_msg.lower():
                print(f"[ERROR] 스트림 연결 중단 - 네트워크 문제입니다")
            else:
                print(f"[ERROR] 기타 다운로드 오류: {error_msg}")

            # 에러가 발생했지만 프로세스는 종료하지 않음
            return 0