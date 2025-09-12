# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel, HttpUrl
from typing import Optional
import requests
import re
from urllib.parse import urlparse

from core.models import DownloadRequest, StatusEnum
from core.db import get_db
from services.download_service import download_service
from services.sse_manager import sse_manager
from services.preparse_service import preparse_service
from core.i18n import get_message
from utils.wait_store import wait_store

router = APIRouter(prefix="/api", tags=["downloads"])


class DownloadRequestCreate(BaseModel):
    url: HttpUrl
    password: Optional[str] = None
    use_proxy: bool = False


@router.post("/download/")
async def create_download_task(
    download_req: DownloadRequestCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    """다운로드 작업 생성 (비동기)"""
    try:
        url_str = str(download_req.url)
        
        # 1fichier URL인 경우 사전 파싱 수행
        file_name = None
        file_size = None
        
        if preparse_service.is_1fichier_url(url_str):
            print(f"[LOG] 1fichier URL 감지 - 사전 파싱 시작: {url_str}")
            try:
                preparse_result = await preparse_service.preparse_1fichier(url_str)
                if preparse_result['success']:
                    file_name = preparse_result.get('name')
                    file_size = preparse_result.get('size')
                    print(f"[LOG] 사전 파싱 성공 - 파일명: {file_name}, 크기: {file_size}")
                else:
                    print(f"[LOG] 사전 파싱 실패: {preparse_result.get('error', '알 수 없는 오류')}")
            except Exception as e:
                print(f"[ERROR] 사전 파싱 중 오류: {e}")
        
        # DB에 다운로드 요청 저장
        req = DownloadRequest(
            url=url_str,
            file_name=file_name,
            file_size=file_size,
            password=download_req.password,
            use_proxy=download_req.use_proxy,
            status=StatusEnum.pending
        )
        db.add(req)
        db.commit()
        db.refresh(req)

        # 비동기 다운로드 시작
        success = await download_service.start_download(
            req.id,
            lang="ko",  # TODO: 요청에서 언어 가져오기
            use_proxy=download_req.use_proxy
        )

        if not success:
            raise HTTPException(
                status_code=500, detail="Failed to start download")

        return {
            "id": req.id,
            "status": req.status.value,
            "message": "다운로드가 시작되었습니다."
        }

    except Exception as e:
        print(f"[ERROR] Create download failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pause/{download_id}")
async def pause_download(download_id: int, request: Request, db: Session = Depends(get_db)):
    """다운로드 일시정지"""
    try:
        # 즉시 정지 플래그 설정 (가장 중요)
        from core.shared import download_manager
        from services.download_manager import download_manager as simple_manager
        download_manager.stop_download_immediately(download_id)
        simple_manager.cleanup(download_id)  # active_downloads에서 정리
        print(f"[LOG] 다운로드 {download_id} 즉시 정지 플래그 설정 완료")
        
        # 다운로드 취소
        success = await download_service.cancel_download(download_id)

        if not success:
            # DB에서 직접 상태 변경
            req = db.query(DownloadRequest).filter(
                DownloadRequest.id == download_id).first()
            if not req:
                raise HTTPException(
                    status_code=404, detail="Download not found")

            req.status = StatusEnum.stopped
            db.commit()

            # 현재 진행률 계산
            progress = 0.0
            if req.total_size and req.total_size > 0 and req.downloaded_size:
                progress = min(100.0, (req.downloaded_size / req.total_size) * 100)

            # SSE 알림 (완전한 정보 포함)
            await sse_manager.broadcast_message("status_update", {
                "id": download_id,
                "url": req.url,
                "file_name": req.file_name,
                "status": StatusEnum.stopped.value,
                "progress": progress,
                "downloaded_size": req.downloaded_size or 0,
                "total_size": req.total_size or 0,
                "save_path": req.save_path,
                "use_proxy": req.use_proxy,
                "error": req.error
            })

        return {"success": True, "status": "stopped"}

    except Exception as e:
        print(f"[ERROR] Pause download failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resume/{download_id}")
async def resume_download(download_id: int, request: Request, db: Session = Depends(get_db)):
    """다운로드 재개"""
    try:
        req = db.query(DownloadRequest).filter(
            DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Download not found")

        # 이미 실행 중이면 에러
        if req.status in [StatusEnum.downloading, StatusEnum.proxying, StatusEnum.parsing]:
            return {"message": "이미 다운로드가 진행 중입니다."}

        # 정지 플래그 초기화 (중요)
        from core.shared import download_manager
        if download_id in download_manager.stop_events:
            download_manager.stop_events[download_id].clear()
            print(f"[LOG] 다운로드 {download_id} 정지 플래그 초기화 완료")
        
        # 즉시 상태를 parsing으로 변경 (사용자 피드백)
        req.status = StatusEnum.parsing
        db.commit()
        
        # SSE로 즉시 상태 업데이트 전송
        from services.sse_manager import sse_manager
        await sse_manager.broadcast_message("status_update", {
            "id": download_id,
            "status": "parsing",
            "message": "이어받기 시작 중..."
        })
        print(f"[LOG] 이어받기 즉시 상태 업데이트 전송: ID {download_id}")

        # 비동기 다운로드 재시작
        use_proxy = request.query_params.get(
            "use_proxy", "false").lower() == "true"
        print(f"[LOG] Resume download starting for ID {download_id}, use_proxy={use_proxy}")
        success = await download_service.start_download(
            download_id,
            lang="ko",
            use_proxy=use_proxy
        )
        print(f"[LOG] Resume download start result: {success}")

        if not success:
            print(f"[ERROR] Failed to start resume download for ID {download_id}")
            # 실패 시 상태를 다시 되돌림
            req.status = StatusEnum.stopped
            db.commit()
            await sse_manager.broadcast_message("status_update", {
                "id": download_id,
                "status": "stopped",
                "message": "이어받기 시작 실패"
            })
            raise HTTPException(
                status_code=500, detail="Failed to resume download")

        return {"success": True, "message": "다운로드가 재개되었습니다."}

    except Exception as e:
        print(f"[ERROR] Resume download failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retry/{download_id}")
async def retry_download(download_id: int, request: Request, db: Session = Depends(get_db)):
    """다운로드 재시도"""
    try:
        req = db.query(DownloadRequest).filter(
            DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Download not found")

        # 상태 초기화
        req.status = StatusEnum.pending
        req.error = None
        req.downloaded_size = 0
        db.commit()

        # 비동기 다운로드 시작
        print(f"[LOG] Retry download starting for ID {download_id}, use_proxy={req.use_proxy}")
        success = await download_service.start_download(
            download_id,
            lang="ko",
            use_proxy=req.use_proxy
        )
        print(f"[LOG] Retry download start result: {success}")

        if not success:
            print(f"[ERROR] Failed to start retry download for ID {download_id}")
            raise HTTPException(
                status_code=500, detail="Failed to retry download")

        return {"success": True, "message": "다운로드 재시도가 시작되었습니다."}

    except Exception as e:
        print(f"[ERROR] Retry download failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/delete/{download_id}")
async def delete_download(download_id: int, request: Request, db: Session = Depends(get_db)):
    """다운로드 삭제"""
    try:
        req = db.query(DownloadRequest).filter(
            DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Download not found")

        # 진행 중이면 먼저 취소
        if req.status in [StatusEnum.downloading, StatusEnum.proxying, StatusEnum.parsing]:
            await download_service.cancel_download(download_id)

        # DB에서 삭제
        db.delete(req)
        db.commit()

        return {"success": True, "message": "다운로드가 삭제되었습니다."}

    except Exception as e:
        print(f"[ERROR] Delete download failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/downloads/active")
async def get_active_downloads(request: Request):
    """활성 다운로드 목록"""
    # download_service에서 활성 태스크 개수 반환
    active_count = len(download_service.download_tasks)

    return {
        "active_downloads": list(download_service.download_tasks.keys()),
        "count": active_count
    }


@router.get("/downloads/wait-status")
async def get_wait_status(request: Request):
    """진행 중인 대기시간 상태 확인 (새로고침용)"""
    try:
        active_waits = wait_store.get_all_active_waits()
        
        # 진행 중인 대기 작업이 있으면 SSE로 즉시 전송
        for download_id, wait_info in active_waits.items():
            wait_minutes = wait_info["remaining_time"] // 60
            wait_message = f"대기 중 ({wait_minutes}분 {wait_info['remaining_time'] % 60}초)" if wait_minutes > 0 else f"대기 중 ({wait_info['remaining_time']}초)"
            
            await sse_manager.broadcast_message("wait_countdown", {
                "download_id": download_id,
                "remaining_time": wait_info["remaining_time"],
                "wait_message": wait_message,
                "total_wait_time": wait_info["total_wait_time"],
                "url": wait_info["url"]
            })
            print(f"[LOG] 새로고침 시 대기시간 복원: ID {download_id}, 남은시간 {wait_info['remaining_time']}초")
        
        return {
            "active_waits": len(active_waits),
            "wait_info": active_waits
        }
        
    except Exception as e:
        print(f"[ERROR] Wait status check failed: {e}")
        return {"active_waits": 0, "wait_info": {}}


@router.get("/history/")
async def get_download_history(request: Request, db: Session = Depends(get_db)):
    """다운로드 히스토리"""
    try:
        # 최신 순으로 정렬
        downloads = db.query(DownloadRequest).order_by(
            DownloadRequest.requested_at.desc()
        ).all()

        # 결과 포맷팅
        result = []
        for download in downloads:
            # 진행률 계산 (total_size가 0이면 0으로 처리)
            progress = 0
            if getattr(download, 'total_size', 0) and getattr(download, 'downloaded_size', 0):
                try:
                    progress = int((download.downloaded_size /
                                   max(1, download.total_size)) * 100)
                except Exception:
                    progress = 0

            result.append({
                "id": download.id,
                "url": download.url,
                "file_name": download.file_name,
                "file_size": download.file_size,
                "status": download.status.value,
                "progress": progress,
                "downloaded_size": download.downloaded_size,
                "total_size": download.total_size,
                "use_proxy": download.use_proxy,
                "error": download.error,
                "requested_at": download.requested_at.isoformat() if download.requested_at else None,
                "finished_at": download.finished_at.isoformat() if getattr(download, 'finished_at', None) else None
            })

        return result

    except Exception as e:
        print(f"[ERROR] Get history failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/downloads/{download_id}/proxy-toggle")
async def toggle_proxy_mode(download_id: int, request: Request, db: Session = Depends(get_db)):
    """프록시 모드 토글 (stopped 상태에서만 가능)"""
    try:
        req = db.query(DownloadRequest).filter(
            DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Download not found")

        if req.status not in [StatusEnum.stopped, StatusEnum.failed]:
            raise HTTPException(
                status_code=400, detail="Can only toggle proxy mode when download is stopped or failed")

        # 프록시 모드 토글
        req.use_proxy = not req.use_proxy
        db.commit()

        return {"success": True, "use_proxy": req.use_proxy}

    except Exception as e:
        print(f"[ERROR] Toggle proxy mode failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class URLValidationRequest(BaseModel):
    url: str


@router.post("/validate-url/")
async def validate_download_url(
    validation_req: URLValidationRequest,
    request: Request
):
    """URL이 다운로드 가능한 링크인지 검증"""
    
    try:
        url = validation_req.url.strip()
        
        # 기본 URL 형식 검증
        try:
            parsed = urlparse(url)
            if not all([parsed.scheme, parsed.netloc]):
                return {
                    "valid": False,
                    "reason": "invalid_url_format",
                    "message": "유효하지 않은 URL 형식입니다."
                }
        except Exception:
            return {
                "valid": False,
                "reason": "invalid_url_format", 
                "message": "유효하지 않은 URL 형식입니다."
            }
        
        # 1fichier URL은 항상 허용
        if re.match(r'https?://(?:[^\.]+\.)?1fichier\.com/', url.lower()):
            return {
                "valid": True,
                "reason": "1fichier_url",
                "message": "1fichier URL입니다."
            }
        
        # 일반 URL의 경우 HEAD 요청으로 다운로드 링크인지 확인
        try:
            print(f"[LOG] URL validation HEAD request: {url}")
            response = requests.head(url, timeout=10, allow_redirects=True)
            
            # Content-Type 확인
            content_type = response.headers.get('Content-Type', '').lower()
            content_disposition = response.headers.get('Content-Disposition', '')
            
            print(f"[LOG] Content-Type: {content_type}")
            print(f"[LOG] Content-Disposition: {content_disposition}")
            
            # HTML 페이지인지 확인
            html_types = ['text/html', 'text/plain', 'application/json']
            is_html_page = any(html_type in content_type for html_type in html_types)
            
            # Content-Disposition이 있으면 다운로드 링크로 간주
            has_download_header = 'attachment' in content_disposition.lower()
            
            # 파일 확장자 확인 (원본 URL과 최종 URL 둘 다 확인)
            original_parsed = urlparse(url)
            final_parsed = urlparse(response.url)  # 리다이렉트된 최종 URL
            
            original_extension = original_parsed.path.lower().split('.')[-1] if '.' in original_parsed.path else ''
            final_extension = final_parsed.path.lower().split('.')[-1] if '.' in final_parsed.path else ''
            file_extension = original_extension or final_extension
            
            downloadable_extensions = [
                'zip', 'rar', '7z', 'tar', 'gz', 'exe', 'msi', 'dmg', 'pkg',
                'mp4', 'avi', 'mkv', 'mp3', 'wav', 'flac', 'pdf', 'doc', 'docx',
                'xls', 'xlsx', 'ppt', 'pptx', 'jpg', 'png', 'gif', 'bmp', 'svg',
                'apk', 'ipa', 'deb', 'rpm', 'iso', 'img', 'bin', 'rom', 'nds',
                'gba', 'smc', 'sfc', 'n64', 'z64', 'v64', 'gcm', 'iso'
            ]
            
            has_download_extension = file_extension in downloadable_extensions
            
            print(f"[LOG] Validation results: html_page={is_html_page}, download_header={has_download_header}, file_ext={file_extension}, downloadable_ext={has_download_extension}")
            
            # 다운로드 가능한 파일인지 판단
            if has_download_header or has_download_extension:
                return {
                    "valid": True,
                    "reason": "downloadable_file",
                    "message": "다운로드 가능한 파일입니다.",
                    "content_type": content_type,
                    "file_extension": file_extension
                }
            elif is_html_page and not has_download_header:
                return {
                    "valid": False,
                    "reason": "html_page",
                    "message": "HTML 페이지입니다. 실제 파일 다운로드 링크를 입력해주세요.",
                    "content_type": content_type
                }
            else:
                # 애매한 경우는 허용 (Content-Type을 알 수 없는 경우 등)
                return {
                    "valid": True,
                    "reason": "unknown_but_allowed",
                    "message": "파일 유형을 확인할 수 없지만 시도해볼 수 있습니다.",
                    "content_type": content_type
                }
                
        except requests.exceptions.Timeout:
            return {
                "valid": False,
                "reason": "timeout",
                "message": "URL 응답 시간이 초과되었습니다."
            }
        except requests.exceptions.ConnectionError:
            return {
                "valid": False,
                "reason": "connection_error",
                "message": "URL에 연결할 수 없습니다."
            }
        except requests.exceptions.RequestException as e:
            return {
                "valid": False,
                "reason": "request_error",
                "message": f"URL 검증 중 오류가 발생했습니다: {str(e)}"
            }
            
    except Exception as e:
        print(f"[ERROR] URL validation failed: {e}")
        return {
            "valid": False,
            "reason": "validation_error",
            "message": f"URL 검증 중 예기치 못한 오류가 발생했습니다: {str(e)}"
        }
