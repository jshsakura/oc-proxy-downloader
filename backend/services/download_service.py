# -*- coding: utf-8 -*-
"""
새로운 비동기 다운로드 서비스
- 완전한 asyncio 기반
- SSE 통합 메시징
- 기존 동기 코드 완전 제거
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
    """완전히 새로운 비동기 다운로드 서비스"""

    def __init__(self):
        self.download_tasks: Dict[int, asyncio.Task] = {}
        self.is_running = False

    async def start(self):
        """서비스 시작"""
        if self.is_running:
            return

        self.is_running = True
        print("[LOG] DownloadService started")

        # 시작시 모든 다운로드를 stopped 상태로 초기화
        await self._reset_all_downloads()

        # 대기시간 모니터링 시작
        self.wait_monitor_task = asyncio.create_task(self._monitor_wait_timeouts())
        print("[LOG] Wait timeout monitor started")

    async def stop(self):
        """서비스 정지"""
        if not self.is_running:
            return

        print("[LOG] Stopping DownloadService...")
        self.is_running = False

        # 대기시간 모니터링 중지
        if hasattr(self, 'wait_monitor_task'):
            self.wait_monitor_task.cancel()
            try:
                await asyncio.wait_for(self.wait_monitor_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        # 모든 다운로드 태스크 정리
        await download_core.cleanup_all_tasks()

        print("[LOG] DownloadService stopped")

    async def _reset_all_downloads(self):
        """시작시 모든 다운로드 상태 초기화"""
        try:
            db = SessionLocal()

            # 실행 중인 다운로드들을 모두 stopped로 변경
            active_downloads = db.query(DownloadRequest).filter(
                DownloadRequest.status.in_([
                    StatusEnum.parsing,
                    StatusEnum.downloading,
                    StatusEnum.waiting
                ])
            ).all()

            reset_count = 0
            for req in active_downloads:
                req.status = StatusEnum.stopped
                req.error_message = "서버 재시작으로 인한 초기화"
                reset_count += 1

            db.commit()

            if reset_count > 0:
                print(f"[LOG] {reset_count}개 다운로드 상태 초기화 완료")

                # SSE로 상태 초기화 알림
                await sse_manager.broadcast_message("download_reset", {
                    "message": f"서버 재시작으로 {reset_count}개 다운로드가 초기화되었습니다",
                    "count": reset_count
                })

        except Exception as e:
            print(f"[ERROR] 다운로드 상태 초기화 실패: {e}")
        finally:
            db.close()

    async def _monitor_wait_timeouts(self):
        """대기시간 타임아웃 모니터링"""
        while self.is_running:
            try:
                await asyncio.sleep(60)  # 1분마다 체크

                db = SessionLocal()
                try:
                    # 대기 중인 다운로드들 체크
                    waiting_downloads = db.query(DownloadRequest).filter(
                        DownloadRequest.status == StatusEnum.waiting
                    ).all()

                    current_time = datetime.datetime.now()

                    for req in waiting_downloads:
                        if hasattr(req, 'wait_until') and req.wait_until and current_time >= req.wait_until:
                            # 대기시간 완료 - 다운로드 재시작
                            await self._restart_after_wait(req, db)

                except Exception as e:
                    print(f"[ERROR] 대기시간 모니터링 오류: {e}")
                finally:
                    db.close()

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ERROR] 대기시간 모니터 루프 오류: {e}")
                await asyncio.sleep(10)  # 오류 시 잠시 대기

    async def _restart_after_wait(self, req: DownloadRequest, db: Session):
        """대기시간 완료 후 다운로드 재시작"""
        try:
            print(f"[LOG] 대기시간 완료, 다운로드 재시작: {req.id}")

            # 상태를 parsing으로 변경
            req.status = StatusEnum.parsing
            if hasattr(req, 'wait_until'):
                req.wait_until = None
            if hasattr(req, 'progress'):
                req.progress = 0
            db.commit()

            # SSE 알림
            await sse_manager.broadcast_message("download_resumed", {
                "id": req.id,
                "message": "대기시간 완료, 다운로드 재시작",
                "status": "parsing"
            })

            # 비동기 다운로드 시작
            await download_core.start_download_async(req, db)

        except Exception as e:
            print(f"[ERROR] 대기 후 재시작 실패: {e}")
            req.status = StatusEnum.failed
            req.error_message = f"재시작 실패: {str(e)}"
            db.commit()

    async def get_download_statistics(self) -> Dict[str, Any]:
        """다운로드 통계 조회"""
        try:
            db = SessionLocal()

            # 상태별 다운로드 수 집계
            total = db.query(DownloadRequest).count()
            parsing = db.query(DownloadRequest).filter(DownloadRequest.status == StatusEnum.parsing).count()
            downloading = db.query(DownloadRequest).filter(DownloadRequest.status == StatusEnum.downloading).count()
            waiting = db.query(DownloadRequest).filter(DownloadRequest.status == StatusEnum.waiting).count()
            done = db.query(DownloadRequest).filter(DownloadRequest.status == StatusEnum.done).count()
            failed = db.query(DownloadRequest).filter(DownloadRequest.status == StatusEnum.failed).count()
            stopped = db.query(DownloadRequest).filter(DownloadRequest.status == StatusEnum.stopped).count()

            return {
                "total": total,
                "parsing": parsing,
                "downloading": downloading,
                "waiting": waiting,
                "done": done,
                "failed": failed,
                "stopped": stopped,
                "active_tasks": len(download_core.download_tasks),
                "sse_connections": len(sse_manager.connections)
            }

        except Exception as e:
            print(f"[ERROR] 통계 조회 실패: {e}")
            return {"error": str(e)}
        finally:
            db.close()

    async def cleanup_completed_downloads(self, older_than_hours: int = 24):
        """완료된 다운로드 정리 (선택적)"""
        try:
            db = SessionLocal()

            cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=older_than_hours)

            # 24시간 이전에 완료된 다운로드들 삭제
            completed_old = db.query(DownloadRequest).filter(
                DownloadRequest.status == StatusEnum.done,
                DownloadRequest.finished_at < cutoff_time
            )

            count = completed_old.count()
            completed_old.delete()
            db.commit()

            if count > 0:
                print(f"[LOG] {count}개 완료된 다운로드 정리")

                # SSE 알림
                await sse_manager.broadcast_message("downloads_cleaned", {
                    "message": f"{count}개 완료된 다운로드가 정리되었습니다",
                    "count": count
                })

            return count

        except Exception as e:
            print(f"[ERROR] 다운로드 정리 실패: {e}")
            return 0
        finally:
            db.close()


# 전역 인스턴스
download_service = DownloadService()