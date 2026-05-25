# -*- coding: utf-8 -*-
"""
New async download service
- Fully asyncio-based
- Integrated SSE messaging
- Legacy synchronous code completely removed
"""

import asyncio
import datetime
from typing import Dict, Any
from sqlalchemy.orm import Session

from core.models import DownloadRequest, StatusEnum
from core.db import SessionLocal
from core.download_core import download_core
from core.proxy_manager import proxy_manager
from services.sse_manager import sse_manager


class DownloadService:
    """A completely new async download service"""

    def __init__(self):
        self.download_tasks: Dict[int, asyncio.Task] = {}
        self.is_running = False

    async def start(self):
        """Start the service"""
        if self.is_running:
            return

        self.is_running = True
        print("[LOG] DownloadService started")

        # Reset all downloads to stopped status at startup
        await self._reset_all_downloads()

    async def stop(self):
        """Stop the service"""
        if not self.is_running:
            return

        print("[LOG] Stopping DownloadService...")
        self.is_running = False

        # Clean up all download tasks
        await download_core.cleanup_all_tasks()

        print("[LOG] DownloadService stopped")

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