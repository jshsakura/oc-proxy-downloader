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
    limit: Optional[int] = None,
    offset: int = 0
):
    """다운로드 히스토리 조회 (제한 없이 전체 데이터)"""
    try:
        # 최근 다운로드들을 가져오기 (ID 역순)
        query = db.query(DownloadRequest).order_by(desc(DownloadRequest.id))

        # offset이 있으면 적용
        if offset > 0:
            query = query.offset(offset)

        # limit이 지정되면 적용, 아니면 전체 조회
        if limit is not None:
            query = query.limit(limit)

        downloads = query.all()

        # 디버깅: 조회된 데이터 상태 확인
        total_count = len(downloads)
        status_counts = {}
        for download in downloads:
            status = download.status.value if download.status else "unknown"
            status_counts[status] = status_counts.get(status, 0) + 1

        print(f"[DEBUG] History API - Total downloads: {total_count}")
        print(f"[DEBUG] History API - Status counts: {status_counts}")

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


@router.get("/downloads/working")
async def get_working_downloads(
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None
):
    """진행 중인 다운로드 조회 (done을 제외한 모든 상태)"""
    try:
        # 기본 쿼리 (done 제외)
        query = db.query(DownloadRequest).filter(
            DownloadRequest.status != StatusEnum.done
        )

        # 검색 조건 추가
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            query = query.filter(
                (DownloadRequest.file_name.ilike(search_term)) |
                (DownloadRequest.url.ilike(search_term))
            )

        # 전체 개수 조회
        total_count = query.count()

        # 페이징 적용하여 조회
        offset = (page - 1) * page_size
        downloads = query.order_by(desc(DownloadRequest.id)).offset(offset).limit(page_size).all()

        download_list = []
        for download in downloads:
            download_list.append({
                "id": download.id,
                "url": download.url,
                "filename": download.file_name or "Unknown",
                "status": download.status.value if download.status else "unknown",
                "progress": round((download.downloaded_size / download.total_size * 100), 1) if download.total_size and download.total_size > 0 else 0,
                "use_proxy": download.use_proxy or False,
                "error_message": download.error,
                "total_size": download.total_size,
                "downloaded_size": download.downloaded_size,
                "file_size": download.file_size,
                "requested_at": download.requested_at.isoformat() if download.requested_at else None
            })

        total_pages = (total_count + page_size - 1) // page_size

        return {
            "downloads": download_list,
            "total_count": total_count,
            "current_page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }

    except Exception as e:
        print(f"[ERROR] Get working downloads failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/downloads/completed")
async def get_completed_downloads(
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None
):
    """완료된 다운로드 조회 (done 상태만)"""
    try:
        # 기본 쿼리 (done만)
        query = db.query(DownloadRequest).filter(
            DownloadRequest.status == StatusEnum.done
        )

        # 검색 조건 추가
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            query = query.filter(
                (DownloadRequest.file_name.ilike(search_term)) |
                (DownloadRequest.url.ilike(search_term))
            )

        # 전체 개수 조회
        total_count = query.count()

        # 페이징 적용하여 조회
        offset = (page - 1) * page_size
        downloads = query.order_by(desc(DownloadRequest.id)).offset(offset).limit(page_size).all()

        download_list = []
        for download in downloads:
            download_list.append({
                "id": download.id,
                "url": download.url,
                "filename": download.file_name or "Unknown",
                "status": download.status.value if download.status else "unknown",
                "progress": 100,  # 완료된 건은 항상 100%
                "use_proxy": download.use_proxy or False,
                "error_message": download.error,
                "total_size": download.total_size,
                "downloaded_size": download.downloaded_size,
                "file_size": download.file_size,
                "requested_at": download.requested_at.isoformat() if download.requested_at else None,
                "finished_at": download.finished_at.isoformat() if download.finished_at else None
            })

        total_pages = (total_count + page_size - 1) // page_size

        return {
            "downloads": download_list,
            "total_count": total_count,
            "current_page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }

    except Exception as e:
        print(f"[ERROR] Get completed downloads failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/downloads/active")
async def get_active_downloads(db: Session = Depends(get_db)):
    """활성 다운로드 조회 (기존 호환성)"""
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
            print(f"[DEBUG] Active download DB values: id={download.id}, file_name='{download.file_name}', file_size='{download.file_size}', total_size={download.total_size}, downloaded_size={download.downloaded_size}")
            downloads.append({
                "id": download.id,
                "url": download.url,
                "filename": download.file_name or "Unknown",
                "status": download.status.value if download.status else "unknown",
                "progress": round((download.downloaded_size / download.total_size * 100), 1) if download.total_size and download.total_size > 0 else 0,
                "use_proxy": download.use_proxy or False,
                "error_message": download.error,
                "total_size": download.total_size,
                "downloaded_size": download.downloaded_size,
                "file_size": download.file_size  # 사전파싱에서 얻은 파일 크기 정보
            })

        return {"downloads": downloads, "count": len(downloads)}

    except Exception as e:
        print(f"[ERROR] Get active downloads failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))