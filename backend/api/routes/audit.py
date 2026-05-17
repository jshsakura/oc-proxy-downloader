# -*- coding: utf-8 -*-
"""링크 검수(audit) API.

다운로드 시도 없이 1fichier 페이지를 가볍게 GET 해서 살아있는지/죽었는지/
일시 차단인지 판정한다. probe 자체는 services.link_probe 모듈이 담당하고,
이 라우터는 단건/배치 호출 및 SSE 진행률 송신을 책임진다.

엔드포인트:
- POST /api/downloads/{id}/probe — 단건 즉시 검수.
- POST /api/downloads/audit — 백그라운드 배치 검수. SSE 'audit_progress' 송신.
"""

import asyncio
import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.db import get_db, SessionLocal
from core.models import DownloadRequest, StatusEnum
from services.link_probe import (
    probe_1fichier_url,
    apply_probe_to_request,
    KIND_ALIVE,
    KIND_UNREACHABLE,
)
from services.sse_manager import sse_manager


router = APIRouter(prefix="/api", tags=["audit"])


class AuditRequest(BaseModel):
    """배치 검수 요청 본문.

    선택 옵션 (전부 OR 결합이 아니라 AND — 좁히는 방향으로만 동작):

    - ``ids``: 명시적 id 리스트. 지정 시 다른 필터 무시 (관리자가 직접 고른
      항목은 항상 검수 대상).
    - ``status_filter``: 상태 화이트리스트. 비어있으면 ``[failed, stopped]``.
    - ``failure_kinds``: 분류 화이트리스트. 빈 리스트는 "전체" 의미.
    - ``since`` / ``until``: ``requested_at`` 기준 기간 필터 (ISO 문자열).
    - ``limit``: 결과 row 수 상한.
    - ``only_with_failure_kind``: True 면 ``failure_kind`` NULL row 제외.
    """
    ids: Optional[List[int]] = None
    status_filter: Optional[List[str]] = None
    failure_kinds: Optional[List[str]] = None
    since: Optional[datetime.datetime] = None
    until: Optional[datetime.datetime] = None
    limit: Optional[int] = None
    only_with_failure_kind: bool = False


# 동시에 audit 가 1개만 돌도록 — probe 자체가 throttle 되긴 하지만 의도된 직렬 처리.
_audit_lock = asyncio.Lock()


def _select_targets(req: "AuditRequest", db: Session) -> List[int]:
    """``AuditRequest`` 필터를 모두 반영한 검수 대상 id 리스트.

    동작 규칙:
    - ``ids`` 지정 시 다른 필터 전부 무시 (단, 존재하는 id 만 통과).
    - 그 외엔 AND 결합. ``failure_kinds`` 가 비어있으면 분류 무관, 채워지면 해당
      kind 만. ``status_filter`` 가 비어있으면 ``[failed, stopped]`` 기본값.
    """
    if req.ids:
        rows = db.query(DownloadRequest.id).filter(
            DownloadRequest.id.in_(req.ids)
        ).all()
        return [r[0] for r in rows]

    statuses = req.status_filter or [
        StatusEnum.failed.value, StatusEnum.stopped.value
    ]
    query = db.query(DownloadRequest.id).filter(
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
    return [r[0] for r in query.all()]


@router.post("/downloads/{download_id}/probe")
async def probe_single(download_id: int, db: Session = Depends(get_db)):
    """단건 즉시 검수."""
    req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Download request not found")

    probe_url = req.original_url or req.url
    if not probe_url:
        raise HTTPException(status_code=400, detail="No URL to probe")

    probe = await probe_1fichier_url(probe_url)
    apply_probe_to_request(req, probe)
    db.commit()

    # SSE 단건 알림 — 프런트가 즉시 행 갱신할 수 있게.
    await sse_manager.broadcast_message("probe_result", {
        "id": download_id,
        "kind": probe.kind,
        "summary": probe.summary,
        "body_marker": probe.body_marker,
        "raw_status": probe.raw_status,
        "definitive": probe.definitive,
        "failure_kind": req.failure_kind,
        "next_retry_at": req.next_retry_at.isoformat() if req.next_retry_at else None,
    })

    return {
        "id": download_id,
        "kind": probe.kind,
        "summary": probe.summary,
        "alive": probe.kind == KIND_ALIVE,
        "definitive": probe.definitive,
        "failure_kind": req.failure_kind,
        "next_retry_at": req.next_retry_at.isoformat() if req.next_retry_at else None,
    }


@router.post("/downloads/audit")
async def start_audit(request: AuditRequest, db: Session = Depends(get_db)):
    """배치 검수 시작. 백그라운드에서 돌고 SSE 'audit_progress' 로 진행률 송신.

    동일 시점에 한 번에 하나의 audit 만 돈다. 락을 먼저 잡고 — 두 요청이 동시에
    도착해도 한 쪽만 통과 — 잡힌 락은 백그라운드 태스크가 finally 에서 해제.
    """
    if not await _try_acquire():
        raise HTTPException(status_code=409, detail="audit_already_running")

    # 락 잡은 뒤 어떤 분기든 실패하면 반드시 해제. (대상 0건이거나 예외 발생 시
    # 백그라운드 태스크가 도는 일 자체가 없으므로 여기서 풀어야 함.)
    try:
        target_ids = _select_targets(request, db)
        total = len(target_ids)

        if total == 0:
            _audit_lock.release()
            return {"started": False, "total": 0, "message": "검수 대상 없음"}

        # 백그라운드 태스크로 처리 — 락은 _run_audit 의 finally 에서 풀린다.
        asyncio.create_task(_run_audit(target_ids))
        return {"started": True, "total": total}
    except Exception:
        if _audit_lock.locked():
            _audit_lock.release()
        raise


async def _run_audit(target_ids: List[int]) -> None:
    """배치 검수 본체. probe_1fichier_url 의 글로벌 throttle 때문에 자연스럽게
    1 req / 3s 페이스로 진행된다.

    호출자가 이미 ``_audit_lock`` 을 획득한 상태여야 한다 — 함수는 finally 에서
    무조건 release.
    """
    try:
        total = len(target_ids)
        await _broadcast_progress(0, total, status="start")

        # 결과 카운터 — UI 토스트에 요약 노출용.
        counts = {
            "alive": 0, "dead": 0, "auth_required": 0,
            "rate_limited": 0, "cloudflare": 0, "proxy_blocked": 0,
            "blocked": 0, "transient": 0, "unreachable": 0,
        }

        for idx, req_id in enumerate(target_ids, start=1):
            db = SessionLocal()
            try:
                req = db.query(DownloadRequest).filter(
                    DownloadRequest.id == req_id
                ).first()
                if not req:
                    continue
                probe_url = req.original_url or req.url
                if not probe_url:
                    continue
                probe = await probe_1fichier_url(probe_url)
                apply_probe_to_request(req, probe)
                db.commit()
                counts[probe.kind] = counts.get(probe.kind, 0) + 1
                await _broadcast_progress(
                    idx, total, status="step",
                    item={
                        "id": req_id,
                        "kind": probe.kind,
                        "summary": probe.summary,
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
    """``_audit_lock`` 을 non-blocking 으로 획득. 이미 잠겨있으면 False."""
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
