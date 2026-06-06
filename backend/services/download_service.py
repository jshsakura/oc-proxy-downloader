# -*- coding: utf-8 -*-
"""
New async download service
- Fully asyncio-based
- Integrated SSE messaging
- Legacy synchronous code completely removed
"""

import asyncio
import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from core.models import DownloadRequest, StatusEnum
from core.db import SessionLocal
from core.config import get_config
from core.download_core import download_core
from core.error_messages import is_retry_blocked_now
from core.proxy_manager import proxy_manager
from services.sse_manager import sse_manager

# How often the background sweeper scans for failed downloads whose retry
# cooldown (next_retry_at) has arrived.
RETRY_SWEEP_INTERVAL_SEC = 20

# Max downloads the sweeper re-runs PER cycle. Re-running a special-hoster/1fichier
# item triggers a heavy parse (cloudscraper + possibly FlareSolverr, multi-second,
# holds a thread-pool slot). Firing every due item at once exhausted the pool and
# made ALL API responses queue for 10-30s. One at a time spreads that load — the
# next due item is just picked up on the following cycle.
MAX_RETRIES_PER_SWEEP = 1


def _has_fichier_credentials() -> bool:
    """True if a 1fichier account is configured — the criterion for whether an
    auth_required failure is worth auto-retrying."""
    cfg = get_config()
    email = (cfg.get("fichier_email") or "").strip()
    password = cfg.get("fichier_password") or ""
    return bool(email and password)


class DownloadService:
    """A completely new async download service"""

    def __init__(self):
        self.download_tasks: Dict[int, asyncio.Task] = {}
        self.is_running = False
        self._retry_sweeper_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the service"""
        if self.is_running:
            return

        self.is_running = True
        print("[LOG] DownloadService started")

        # Reset all downloads to stopped status at startup
        await self._reset_all_downloads()

        # Start the background auto-retry sweeper
        self._retry_sweeper_task = asyncio.create_task(self._retry_sweeper_loop())

    async def stop(self):
        """Stop the service"""
        if not self.is_running:
            return

        print("[LOG] Stopping DownloadService...")
        self.is_running = False

        # Stop the auto-retry sweeper
        if self._retry_sweeper_task is not None:
            self._retry_sweeper_task.cancel()
            self._retry_sweeper_task = None

        # Clean up all download tasks
        await download_core.cleanup_all_tasks()

        print("[LOG] DownloadService stopped")

    async def _retry_sweeper_loop(self):
        """Re-run failed downloads whose retry cooldown has arrived.

        Transient failures (node outage, timeout, 5xx) are stamped with a
        ``next_retry_at`` backoff at failure time, but until now nothing acted on
        it — a download that died on a brief blip stayed failed forever. This loop
        is that missing piece: it periodically picks up due, non-terminal failures
        and restarts them, preserving ``attempt_count`` so the existing backoff
        keeps escalating (30s → 2m → 8m → 30m) on repeat failure.
        """
        while self.is_running:
            await asyncio.sleep(RETRY_SWEEP_INTERVAL_SEC)
            if not self.is_running:
                break
            # Resilience: one bad sweep must not kill the loop, or every later
            # auto-retry silently stops. Log and continue on the next tick.
            try:
                await self._sweep_due_retries()
            except Exception as e:
                print(f"[ERROR] 자동 재시도 스윕 실패: {e}")

    async def _sweep_due_retries(self):
        """Restart every failed download whose ``next_retry_at`` has passed."""
        with SessionLocal() as db:
            now = datetime.datetime.now()
            due = db.query(DownloadRequest).filter(
                DownloadRequest.status == StatusEnum.failed,
                DownloadRequest.next_retry_at.isnot(None),
                DownloadRequest.next_retry_at <= now,
            ).order_by(DownloadRequest.next_retry_at.asc()).all()

            if not due:
                return

            has_creds = _has_fichier_credentials()
            started = 0
            for req in due:
                # Skip permanent failures (dead / auth_required w/o account).
                if is_retry_blocked_now(req, has_creds) is not None:
                    continue

                # Auto-retry — unlike a manual forced retry, KEEP attempt_count /
                # attempts_json so the backoff keeps escalating; just clear the
                # cooldown + error and re-queue. downloaded_size is preserved so
                # the existing .part resumes instead of restarting from zero.
                print(f"[LOG] 자동 재시도: id={req.id} ({req.file_name})")
                req.status = StatusEnum.pending
                req.error = None
                req.failure_kind = None
                req.next_retry_at = None
                req.finished_at = None
                db.commit()

                await download_core.start_download_async(req, db)

                # One (heavy) re-parse per cycle — the rest wait for the next tick
                # so a batch of simultaneously-due failures can't stampede the
                # thread pool and stall every API request.
                started += 1
                if started >= MAX_RETRIES_PER_SWEEP:
                    break

    async def _reset_all_downloads(self):
        """Reset all download statuses at startup"""
        try:
            with SessionLocal() as db:
                # Change all running downloads to stopped
                active_downloads = db.query(DownloadRequest).filter(
                    DownloadRequest.status.in_([
                        StatusEnum.parsing,
                        StatusEnum.downloading,
                        StatusEnum.waiting,
                    ])
                ).all()

                reset_count = 0
                for req in active_downloads:
                    req.status = StatusEnum.stopped
                    # The column name is ``error`` — fixes a bug where it was
                    # mistakenly written as ``error_message`` and vanished as a
                    # transient attribute.
                    req.error = "서버 재시작으로 인한 초기화"
                    reset_count += 1

                db.commit()

                if reset_count > 0:
                    print(f"[LOG] {reset_count}개 다운로드 상태 초기화 완료")
                    await sse_manager.broadcast_message("download_reset", {
                        "message": f"서버 재시작으로 {reset_count}개 다운로드가 초기화되었습니다",
                        "count": reset_count,
                    })

                # Auto-start pending downloads after a server restart
                await self._start_pending_downloads_after_restart(db)

        except Exception as e:
            print(f"[ERROR] 다운로드 상태 초기화 실패: {e}")

    async def _start_pending_downloads_after_restart(self, db: Session):
        """Automatically start pending downloads after a server restart"""
        try:
            # Query all pending downloads (sorted ascending by request time)
            pending_downloads = db.query(DownloadRequest).filter(
                DownloadRequest.status == StatusEnum.pending
            ).order_by(DownloadRequest.requested_at.asc()).all()

            if not pending_downloads:
                print("[LOG] 서버 재시작 후 대기중인 다운로드 없음")
                return

            print(f"[LOG] 서버 재시작 후 {len(pending_downloads)}개 대기중인 다운로드 발견")

            # Auto-start via download_core. Each task parks on its own semaphore
            # (per-site or the shared general/1fichier one) and enforces the
            # concurrency limit itself, so we simply launch every pending and let
            # the semaphores throttle. Gating here on a single semaphore value
            # would use the wrong limit for per-site hosts and starve pendings.
            from core.download_core import download_core
            started_count = 0

            for req in pending_downloads:
                success = await download_core.start_download_async(req, db)
                if success:
                    started_count += 1
                    print(f"[LOG] 다운로드 자동 재시작: {req.id}")

            print(f"[LOG] 서버 재시작 후 총 {started_count}개 다운로드 자동 시작됨")

        except Exception as e:
            print(f"[ERROR] 서버 재시작 후 자동 시작 실패: {e}")

    async def get_download_statistics(self) -> Dict[str, Any]:
        """Get download statistics"""
        try:
            with SessionLocal() as db:
                # Aggregate download counts by status
                base = db.query(DownloadRequest)
                return {
                    "total": base.count(),
                    "parsing": base.filter(DownloadRequest.status == StatusEnum.parsing).count(),
                    "downloading": base.filter(DownloadRequest.status == StatusEnum.downloading).count(),
                    "waiting": base.filter(DownloadRequest.status == StatusEnum.waiting).count(),
                    "done": base.filter(DownloadRequest.status == StatusEnum.done).count(),
                    "failed": base.filter(DownloadRequest.status == StatusEnum.failed).count(),
                    "stopped": base.filter(DownloadRequest.status == StatusEnum.stopped).count(),
                    "active_tasks": len(download_core.download_tasks),
                    "sse_connections": len(sse_manager.connections),
                }
        except Exception as e:
            print(f"[ERROR] 통계 조회 실패: {e}")
            return {"error": str(e)}

    async def cleanup_completed_downloads(self, older_than_hours: int = 24):
        """DEPRECATED: Infinite retention policy — DO NOT CALL.
        User requires all download history preserved indefinitely.
        This method is intentionally a no-op to prevent accidental data loss.
        """
        return 0


# Global instance
download_service = DownloadService()