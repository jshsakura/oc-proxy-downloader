# -*- coding: utf-8 -*-
"""Link audit API.

Lightly GETs a 1fichier page without attempting a download to decide whether
it is alive / dead / temporarily blocked. The probe itself is handled by the
services.link_probe module; this router is responsible for single/batch calls
and emitting SSE progress.

Endpoints:
- POST /api/downloads/{id}/probe — immediate single-item audit.
- POST /api/downloads/audit — background batch audit. Emits SSE 'audit_progress'.
"""

import asyncio
import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.db import get_db, SessionLocal
from core import db_async
from core.models import DownloadRequest, StatusEnum
from services.link_probe import (
    probe_url,
    apply_probe_to_request,
    is_probe_supported,
    KIND_ALIVE,
    KIND_UNREACHABLE,
)
from services.sse_manager import sse_manager


router = APIRouter(prefix="/api", tags=["audit"])


class AuditRequest(BaseModel):
    """Batch audit request body.

    Optional filters (combined with AND, not OR — they only narrow):

    - ``ids``: explicit id list. When given, other filters are ignored (items
      hand-picked by an admin are always audit targets).
    - ``status_filter``: status whitelist. Defaults to ``[failed, stopped]`` if empty.
    - ``failure_kinds``: classification whitelist. An empty list means "all".
    - ``since`` / ``until``: period filter on ``requested_at`` (ISO strings).
    - ``limit``: cap on the number of result rows.
    - ``only_with_failure_kind``: if True, exclude rows where ``failure_kind`` is NULL.
    """
    ids: Optional[List[int]] = None
    status_filter: Optional[List[str]] = None
    failure_kinds: Optional[List[str]] = None
    since: Optional[datetime.datetime] = None
    until: Optional[datetime.datetime] = None
    limit: Optional[int] = None
    only_with_failure_kind: bool = False


# Only one audit runs at a time — the probe itself is throttled, but this is
# intentional serial processing.
_audit_lock = asyncio.Lock()


def _select_targets(req: "AuditRequest", db: Session) -> List[int]:
    """List of audit-target ids reflecting all ``AuditRequest`` filters.

    Rules:
    - When ``ids`` is given, ignore all other filters (only existing ids pass).
    - Otherwise combine with AND. If ``failure_kinds`` is empty, classification
      is ignored; if filled, only those kinds. If ``status_filter`` is empty,
      defaults to ``[failed, stopped]``.
    """
    if req.ids:
        rows = db.query(DownloadRequest.id, DownloadRequest.url, DownloadRequest.original_url).filter(
            DownloadRequest.id.in_(req.ids)
        ).all()
        return _probeable_ids(rows)

    statuses = req.status_filter or [
        StatusEnum.failed.value, StatusEnum.stopped.value
    ]
    query = db.query(DownloadRequest.id, DownloadRequest.url, DownloadRequest.original_url).filter(
        DownloadRequest.status.in_(statuses)
    )
    if req.failure_kinds:
        query = query.filter(DownloadRequest.failure_kind.in_(req.failure_kinds))
    elif req.only_with_failure_kind:
        query = query.filter(DownloadRequest.failure_kind.isnot(None))
    if req.since:
        query = query.filter(DownloadRequest.requested_at >= req.since)
    if req.until:
        query = query.filter(DownloadRequest.requested_at <= req.until)
    query = query.order_by(DownloadRequest.last_probed_at.asc().nullsfirst())
    if req.limit:
        query = query.limit(req.limit)
    return _probeable_ids(query.all())


def _probeable_ids(rows) -> List[int]:
    """Ids the prober can actually judge.

    The prober reads 1fichier's body markers and nothing else. Feeding it a
    DataNodes link produced a "result" that was really a statement about the
    prober, and applying it overwrote the row's real failure reason — 248 rows
    ended up pinned dead with "1fichier URL 이 아님" as their only explanation.
    Filtering here means such a row is never touched.
    """
    return [row[0] for row in rows if is_probe_supported(row[1] or row[2] or "")]


@router.post("/downloads/{download_id}/probe")
async def probe_single(download_id: int, db: Session = Depends(get_db)):
    """Immediate single-item audit."""
    req = await db_async.first(db.query(DownloadRequest).filter(DownloadRequest.id == download_id))
    if not req:
        raise HTTPException(status_code=404, detail="Download request not found")

    probe_url = req.original_url or req.url
    if not probe_url:
        raise HTTPException(status_code=400, detail="No URL to probe")

    # Say so instead of recording a verdict the prober cannot back up. The old
    # behaviour wrote "1fichier URL 이 아님" over the row's real failure reason.
    if not is_probe_supported(probe_url):
        raise HTTPException(
            status_code=400,
            detail="이 호스트는 링크 검수를 지원하지 않습니다 (1fichier 전용)",
        )

    probe = await probe_url(probe_url)
    apply_probe_to_request(req, probe)

    # Read the verdict out before committing — the commit expires the instance,
    # so each field below would otherwise re-SELECT the row on the event loop.
    failure_kind = req.failure_kind
    next_retry_at = req.next_retry_at.isoformat() if req.next_retry_at else None
    await db_async.commit(db)

    # Single-item SSE notification — so the frontend can refresh the row immediately.
    await sse_manager.broadcast_message("probe_result", {
        "id": download_id,
        "kind": probe.kind,
        "summary": probe.summary,
        "body_marker": probe.body_marker,
        "raw_status": probe.raw_status,
        "definitive": probe.definitive,
        "failure_kind": failure_kind,
        "next_retry_at": next_retry_at,
    })

    return {
        "id": download_id,
        "kind": probe.kind,
        "summary": probe.summary,
        "alive": probe.kind == KIND_ALIVE,
        "definitive": probe.definitive,
        "failure_kind": failure_kind,
        "next_retry_at": next_retry_at,
    }


@router.post("/downloads/audit")
async def start_audit(request: AuditRequest, db: Session = Depends(get_db)):
    """Start a batch audit. Runs in the background and emits progress via SSE 'audit_progress'.

    Only one audit runs at any given time. Acquire the lock first — even if two
    requests arrive at once, only one passes — and the held lock is released by
    the background task in its finally block.
    """
    if not await _try_acquire():
        raise HTTPException(status_code=409, detail="audit_already_running")

    # Once the lock is held, release it if any branch fails. (When there are 0
    # targets or an exception occurs, no background task runs, so it must be
    # released here.)
    try:
        # _select_targets runs its query synchronously; called straight from
        # here it would execute on the event loop.
        target_ids = await asyncio.to_thread(_select_targets, request, db)
        total = len(target_ids)

        if total == 0:
            _audit_lock.release()
            return {"started": False, "total": 0, "message": "검수 대상 없음"}

        # Handle via a background task — the lock is released in _run_audit's finally.
        asyncio.create_task(_run_audit(target_ids))
        return {"started": True, "total": total}
    except Exception:
        if _audit_lock.locked():
            _audit_lock.release()
        raise


async def _run_audit(target_ids: List[int]) -> None:
    """Body of the batch audit. Because of probe_1fichier_url's global throttle,
    it naturally proceeds at a 1 req / 3s pace.

    The caller must already hold ``_audit_lock`` — this function always releases
    it in its finally block.
    """
    try:
        total = len(target_ids)
        await _broadcast_progress(0, total, status="start")

        # Result counters — for showing a summary in the UI toast.
        counts = {
            "alive": 0, "dead": 0, "auth_required": 0,
            "rate_limited": 0, "cloudflare": 0, "proxy_blocked": 0,
            "blocked": 0, "transient": 0, "unreachable": 0,
        }

        for idx, req_id in enumerate(target_ids, start=1):
            db = SessionLocal()
            try:
                req = await db_async.first(db.query(DownloadRequest).filter(
                    DownloadRequest.id == req_id
                ))
                if not req:
                    continue
                probe_url = req.original_url or req.url
                if not probe_url:
                    continue
                probe = await probe_url(probe_url)
                apply_probe_to_request(req, probe)
                await db_async.commit(db)
                counts[probe.kind] = counts.get(probe.kind, 0) + 1
                await _broadcast_progress(
                    idx, total, status="step",
                    item={
                        "id": req_id,
                        "kind": probe.kind,
                        "summary": probe.summary,
                        # Include the post-probe fields so the frontend can update
                        # the row in place (no full list reload needed at the end).
                        "failure_kind": req.failure_kind,
                        "next_retry_at": req.next_retry_at.isoformat() if req.next_retry_at else None,
                    },
                )
            except Exception as e:
                print(f"[ERROR] audit 단건 실패 (id={req_id}): {e}")
            finally:
                db.close()

        await _broadcast_progress(total, total, status="done", counts=counts)
    finally:
        _audit_lock.release()


async def _try_acquire() -> bool:
    """Acquire ``_audit_lock`` non-blockingly. Returns False if already locked."""
    try:
        await asyncio.wait_for(_audit_lock.acquire(), timeout=0.01)
        return True
    except asyncio.TimeoutError:
        return False


async def _broadcast_progress(done: int, total: int, *, status: str,
                              item: Optional[dict] = None,
                              counts: Optional[dict] = None) -> None:
    payload = {
        "done": done,
        "total": total,
        "status": status,
        "ts": datetime.datetime.now().isoformat(),
    }
    if item:
        payload["item"] = item
    if counts:
        payload["counts"] = counts
    await sse_manager.broadcast_message("audit_progress", payload)
