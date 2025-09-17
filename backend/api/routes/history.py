# -*- coding: utf-8 -*-
"""
다운로드 히스토리 API 라우터
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional

from core.db import get_db
from core.models import DownloadRequest, StatusEnum

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history/")
async def get_download_history(
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0
):
    """다운로드 히스토리 조회"""
    try:
        # 최근 다운로드들을 가져오기 (ID 역순)
        downloads = db.query(DownloadRequest).order_by(
            desc(DownloadRequest.id)
        ).offset(offset).limit(limit).all()

        history = []
        for download in downloads:
            history.append({
                "id": download.id,
                "url": download.url,
                "filename": download.file_name or "Unknown",
                "status": download.status.value if download.status else "unknown",
                "progress": round((download.downloaded_size / download.total_size * 100), 1) if download.total_size and download.total_size > 0 else 0,
                "use_proxy": download.use_proxy or False,
                "created_at": download.requested_at.isoformat() if download.requested_at else None,
                "finished_at": download.finished_at.isoformat() if download.finished_at else None,
                "error_message": download.error,
                "total_size": download.total_size,
                "downloaded_size": download.downloaded_size
            })

        return {"history": history, "total": len(history)}

    except Exception as e:
        print(f"[ERROR] Get download history failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/downloads/active")
async def get_active_downloads(db: Session = Depends(get_db)):
    """활성 다운로드 조회"""
    try:
        # 진행 중인 다운로드들
        active_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([
                StatusEnum.parsing,
                StatusEnum.downloading,
                StatusEnum.waiting
            ])
        ).all()

        downloads = []
        for download in active_downloads:
            downloads.append({
                "id": download.id,
                "url": download.url,
                "filename": download.file_name or "Unknown",
                "status": download.status.value if download.status else "unknown",
                "progress": round((download.downloaded_size / download.total_size * 100), 1) if download.total_size and download.total_size > 0 else 0,
                "use_proxy": download.use_proxy or False,
                "error_message": download.error,
                "total_size": download.total_size,
                "downloaded_size": download.downloaded_size
            })

        return {"downloads": downloads, "count": len(downloads)}

    except Exception as e:
        print(f"[ERROR] Get active downloads failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))