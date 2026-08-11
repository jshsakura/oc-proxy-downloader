# -*- coding: utf-8 -*-
"""
Download history API router
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import case, desc, func
from typing import List, Optional

from core.db import get_db
from core.models import DownloadRequest, StatusEnum
from core.error_messages import classify_failure_text
from core.hoster_labels import hoster_label, hoster_slug
from core import live_progress
from core.simple_parser import derive_display_name


def _failure_kind_of(download: DownloadRequest) -> str:
    """The stored classification, falling back to the error text.

    ``failure_kind`` exists so a verdict survives changes to the matching rules —
    a link pinned ``dead`` by a probe must not turn ``transient`` because a regex
    was reworded. Re-deriving it from the text on every row of every list
    response threw that away, and cost a classification pass per row per poll.
    """
    stored = getattr(download, "failure_kind", None)
    if stored:
        return stored
    return classify_failure_text(download.error)


def _display_filename(download: DownloadRequest) -> str:
    """Never expose "Unknown" — if the DB's file_name is empty, derive it from the URL."""
    name = (download.file_name or "").strip()
    if name:
        return name
    return derive_display_name(download.url or "")

router = APIRouter(prefix="/api", tags=["history"])


# These read endpoints are what the UI polls to stay alive, and none of them await
# anything — as `async def` they ran their SQLite queries straight on the event
# loop, so any lock contention (progress writes during an active download) froze
# every request in the app, not just theirs. Declared sync, FastAPI runs them on
# anyio's own threadpool and the loop stays free no matter how busy parsing is.
@router.get("/history/")
def get_download_history(
    db: Session = Depends(get_db),
    limit: Optional[int] = None,
    offset: int = 0
):
    """Get download history.

    ``limit=None`` (default) and ``limit<=0`` return all rows — the UI's "전체"
    view should actually mean everything, not a silent 200-item cap. Pass an
    explicit positive ``limit`` to cap the response.
    """
    try:
        # Fetch recent downloads (descending by ID)
        base_query = db.query(DownloadRequest).order_by(desc(DownloadRequest.id))

        # Total count (before applying offset/limit)
        total_count = base_query.count()

        # Apply offset and optional limit
        query = base_query
        if offset > 0:
            query = query.offset(offset)
        if limit is not None and limit > 0:
            query = query.limit(limit)

        downloads = query.all()

        history = []
        for download in downloads:
            history.append({
                "id": download.id,
                "url": download.url,
                "filename": _display_filename(download),
                "status": download.status.value if download.status else "unknown",
                "progress": round((download.downloaded_size / download.total_size * 100), 1) if download.total_size and download.total_size > 0 else 0,
                "use_proxy": download.use_proxy or False,
                "created_at": download.requested_at.isoformat() if download.requested_at else None,
                "finished_at": download.finished_at.isoformat() if download.finished_at else None,
                "error_message": download.error,
                "failure_kind": _failure_kind_of(download),
                # The URL actually being fetched — after an ouo unwrap the
                # original is a shortlink, which says nothing about where
                # the bytes come from.
                "hoster": hoster_label(download.url or download.original_url),
                "hoster_key": hoster_slug(download.url or download.original_url),
                "total_size": download.total_size,
                "downloaded_size": download.downloaded_size
            })

        return {"history": history, "total": total_count}

    except Exception as e:
        print(f"[ERROR] Get download history failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/downloads/working")
def get_working_downloads(
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """Get in-progress downloads (all statuses except done)"""
    try:
        # Base query (excludes done)
        query = db.query(DownloadRequest).filter(
            DownloadRequest.status != StatusEnum.done
        )

        # Apply optional period filter (mirrors /history/period parsing)
        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD")
            query = query.filter(DownloadRequest.requested_at >= start_dt)

        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD")
            query = query.filter(DownloadRequest.requested_at < end_dt)

        # Add search condition
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            query = query.filter(
                (DownloadRequest.file_name.ilike(search_term)) |
                (DownloadRequest.url.ilike(search_term))
            )

        # Get total count
        total_count = query.count()

        # Apply paging and query
        offset = (page - 1) * page_size
        downloads = query.order_by(desc(DownloadRequest.id)).offset(offset).limit(page_size).all()

        live_speeds = live_progress.snapshot()
        download_list = []
        for download in downloads:
            download_list.append({
                "id": download.id,
                "url": download.url,
                "filename": _display_filename(download),
                "status": download.status.value if download.status else "unknown",
                "progress": round((download.downloaded_size / download.total_size * 100), 1) if download.total_size and download.total_size > 0 else 0,
                "use_proxy": download.use_proxy or False,
                "error_message": download.error,
                "failure_kind": _failure_kind_of(download),
                # The URL actually being fetched — after an ouo unwrap the
                # original is a shortlink, which says nothing about where
                # the bytes come from.
                "hoster": hoster_label(download.url or download.original_url),
                "hoster_key": hoster_slug(download.url or download.original_url),
                "total_size": download.total_size,
                "downloaded_size": download.downloaded_size,
                "file_size": download.file_size,
                "requested_at": download.requested_at.isoformat() if download.requested_at else None,
                # Alias for the frontend grid — kept alongside requested_at for legacy callers
                "created_at": download.requested_at.isoformat() if download.requested_at else None,
                # Retry state so the grid can show "재시도 대기 (N회, 다음 HH:MM)" on load,
                # not only when an SSE event happens to arrive.
                "next_retry_at": download.next_retry_at.isoformat() if getattr(download, "next_retry_at", None) else None,
                "attempt_count": getattr(download, "attempt_count", 0) or 0,
                # Live reading, so a refetch does not blank the column mid-transfer.
                "download_speed": live_speeds.get(download.id, 0),
            })

        total_pages = (total_count + page_size - 1) // page_size

        return {
            "downloads": download_list,
            "total_count": total_count,
            "current_page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Get working downloads failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/downloads/completed")
def get_completed_downloads(
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """Get completed downloads (done status only)"""
    try:
        # Base query (done only)
        query = db.query(DownloadRequest).filter(
            DownloadRequest.status == StatusEnum.done
        )

        # Apply optional period filter (mirrors /history/period parsing)
        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD")
            query = query.filter(DownloadRequest.requested_at >= start_dt)

        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD")
            query = query.filter(DownloadRequest.requested_at < end_dt)

        # Add search condition
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            query = query.filter(
                (DownloadRequest.file_name.ilike(search_term)) |
                (DownloadRequest.url.ilike(search_term))
            )

        # Get total count
        total_count = query.count()

        # Apply paging and query
        offset = (page - 1) * page_size
        downloads = query.order_by(desc(DownloadRequest.id)).offset(offset).limit(page_size).all()

        live_speeds = live_progress.snapshot()
        download_list = []
        for download in downloads:
            download_list.append({
                "id": download.id,
                "url": download.url,
                "filename": _display_filename(download),
                "status": download.status.value if download.status else "unknown",
                "progress": 100,  # completed items are always 100%
                "use_proxy": download.use_proxy or False,
                "error_message": download.error,
                "failure_kind": _failure_kind_of(download),
                # The URL actually being fetched — after an ouo unwrap the
                # original is a shortlink, which says nothing about where
                # the bytes come from.
                "hoster": hoster_label(download.url or download.original_url),
                "hoster_key": hoster_slug(download.url or download.original_url),
                "total_size": download.total_size,
                "downloaded_size": download.downloaded_size,
                "file_size": download.file_size,
                "requested_at": download.requested_at.isoformat() if download.requested_at else None,
                # Alias for the frontend grid — kept alongside requested_at for legacy callers
                "created_at": download.requested_at.isoformat() if download.requested_at else None,
                "next_retry_at": download.next_retry_at.isoformat() if getattr(download, "next_retry_at", None) else None,
                "attempt_count": getattr(download, "attempt_count", 0) or 0,
                # Live reading, so a refetch does not blank the column mid-transfer.
                "download_speed": live_speeds.get(download.id, 0),
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

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Get completed downloads failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/downloads/active")
def get_active_downloads(db: Session = Depends(get_db)):
    """Get active downloads (legacy compatibility)"""
    try:
        # In-progress downloads (failed ones are included in the display too)
        active_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([
                StatusEnum.parsing,
                StatusEnum.downloading,
                StatusEnum.waiting,
                StatusEnum.failed,
                StatusEnum.pending
            ])
        ).all()

        downloads = []
        for download in active_downloads:
            downloads.append({
                "id": download.id,
                "url": download.url,
                "filename": _display_filename(download),
                "status": download.status.value if download.status else "unknown",
                "progress": round((download.downloaded_size / download.total_size * 100), 1) if download.total_size and download.total_size > 0 else 0,
                "use_proxy": download.use_proxy or False,
                "error_message": download.error,
                "failure_kind": _failure_kind_of(download),
                # The URL actually being fetched — after an ouo unwrap the
                # original is a shortlink, which says nothing about where
                # the bytes come from.
                "hoster": hoster_label(download.url or download.original_url),
                "hoster_key": hoster_slug(download.url or download.original_url),
                "total_size": download.total_size,
                "downloaded_size": download.downloaded_size,
                "file_size": download.file_size  # file size info obtained from preparse
            })

        return {"downloads": downloads, "count": len(downloads)}

    except Exception as e:
        print(f"[ERROR] Get active downloads failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/period")
def get_history_period(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        query = db.query(DownloadRequest).order_by(desc(DownloadRequest.requested_at))

        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD")
            query = query.filter(DownloadRequest.requested_at >= start_dt)

        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD")
            query = query.filter(DownloadRequest.requested_at < end_dt)

        if status:
            try:
                status_enum = StatusEnum(status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status. Valid: {[s.value for s in StatusEnum]}")
            query = query.filter(DownloadRequest.status == status_enum)

        total = query.count()

        page_size = max(1, min(200, page_size))
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        offset = (page - 1) * page_size
        downloads = query.offset(offset).limit(page_size).all()

        history = [d.as_dict() for d in downloads]

        return {
            "history": history,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Get history period failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/stats")
def get_history_stats(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db)
):
    try:
        query = db.query(DownloadRequest)
        start_dt = None
        end_dt = None

        if start_date:
            try:
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format. Use YYYY-MM-DD")
            query = query.filter(DownloadRequest.requested_at >= start_dt)

        if end_date:
            try:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format. Use YYYY-MM-DD")
            query = query.filter(DownloadRequest.requested_at < end_dt)

        # One grouped pass instead of a COUNT per status plus two more for the
        # proxy split. The tab badges refresh off every SSE status update, so
        # this endpoint runs while downloads are writing — each extra full scan
        # here is time the writer spends waiting.
        status_rows = query.with_entities(
            DownloadRequest.status,
            func.count(DownloadRequest.id),
            func.coalesce(func.sum(DownloadRequest.total_size), 0),
            func.sum(case((DownloadRequest.use_proxy == True, 1), else_=0)),
        ).group_by(DownloadRequest.status).all()

        status_counts = {status_enum.value: 0 for status_enum in StatusEnum}
        total = 0
        total_bytes = 0
        proxy_count = 0
        for status, count, size_sum, proxy_sum in status_rows:
            # A pre-migration row can carry a NULL status. It belongs in the
            # totals but must not invent a status key the UI would then render
            # as a badge.
            if status is not None:
                status_counts[status.value if hasattr(status, "value") else str(status)] = count
            total += count
            total_bytes += int(size_sum or 0)
            proxy_count += int(proxy_sum or 0)
        local_count = total - proxy_count

        done_count = status_counts.get("done", 0)
        success_rate = round(done_count / total * 100, 1) if total > 0 else 0.0

        trend_query = db.query(
            func.date(DownloadRequest.requested_at).label("date"),
            func.count(DownloadRequest.id).label("count"),
            func.coalesce(func.sum(DownloadRequest.total_size), 0).label("bytes")
        )

        if start_date:
            trend_query = trend_query.filter(DownloadRequest.requested_at >= start_dt)
        if end_date:
            trend_query = trend_query.filter(DownloadRequest.requested_at < end_dt)

        trend_query = trend_query.group_by(func.date(DownloadRequest.requested_at)).order_by(func.date(DownloadRequest.requested_at))

        daily_trend_raw = trend_query.all()

        daily_trend = []
        if len(daily_trend_raw) <= 365:
            for row in daily_trend_raw:
                daily_trend.append({"date": str(row.date), "count": row.count, "bytes": int(row.bytes)})
        else:
            step = len(daily_trend_raw) / 365
            for i in range(365):
                idx = int(i * step)
                row = daily_trend_raw[idx]
                daily_trend.append({"date": str(row.date), "count": row.count, "bytes": int(row.bytes)})

        return {
            "total": total,
            "by_status": status_counts,
            "total_bytes": total_bytes,
            "proxy_count": proxy_count,
            "local_count": local_count,
            "success_rate": success_rate,
            "daily_trend": daily_trend
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Get history stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))