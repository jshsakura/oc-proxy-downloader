# -*- coding: utf-8 -*-
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel, HttpUrl
from typing import Optional

from core.models import DownloadRequest, StatusEnum
from core.db import get_db
from services.download_service import download_service
from services.sse_manager import sse_manager
from services.preparse_service import preparse_service
from core.i18n import get_message

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

            # SSE 알림
            await sse_manager.broadcast_message("status_update", {
                "id": download_id,
                "status": StatusEnum.stopped.value
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

        if req.status != StatusEnum.stopped:
            raise HTTPException(
                status_code=400, detail="Can only toggle proxy mode when download is stopped")

        # 프록시 모드 토글
        req.use_proxy = not req.use_proxy
        db.commit()

        return {"success": True, "use_proxy": req.use_proxy}

    except Exception as e:
        print(f"[ERROR] Toggle proxy mode failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
