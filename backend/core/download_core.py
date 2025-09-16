# -*- coding: utf-8 -*-
"""
비동기 다운로드 코어 모듈
- SSE 통합 메시징
- 비동기 다운로드 로직
- 상태 실시간 업데이트
"""

import asyncio
import aiofiles
import aiohttp
import os
import time
import datetime
import json
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator
from sqlalchemy.orm import Session

from .models import DownloadRequest, StatusEnum
from .config import get_download_path
from .db import SessionLocal
from services.sse_manager import sse_manager


class DownloadCore:
    """비동기 다운로드 코어"""

    def __init__(self):
        self.download_tasks: Dict[int, asyncio.Task] = {}

    async def send_download_update(self, req_id: int, update_data: Dict[str, Any]):
        """통합 다운로드 상태 업데이트 SSE 전송"""
        try:
            await sse_manager.broadcast_message("status_update", {
                "id": req_id,
                **update_data
            })
        except Exception as e:
            print(f"[ERROR] SSE 업데이트 전송 실패: {e}")

    async def send_download_log(self, req_id: int, message: str, level: str = "info"):
        """다운로드 로그 SSE 전송"""
        try:
            await sse_manager.broadcast_message("download_log", {
                "id": req_id,
                "message": message,
                "level": level,
                "timestamp": datetime.datetime.now().isoformat()
            })
        except Exception as e:
            print(f"[ERROR] SSE 로그 전송 실패: {e}")

    async def start_download_async(self, req: DownloadRequest, db: Session) -> bool:
        """비동기 다운로드 시작"""
        try:
            # 상태를 parsing으로 변경
            req.status = StatusEnum.parsing
            req.progress = 0
            req.download_started_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "parsing",
                "progress": 0,
                "message": "파싱 시작 중..."
            })

            # 비동기 다운로드 태스크 생성
            task = asyncio.create_task(self._download_task(req.id))
            self.download_tasks[req.id] = task

            # 태스크 완료 콜백 등록
            task.add_done_callback(lambda t: self._task_cleanup(req.id))

            return True

        except Exception as e:
            print(f"[ERROR] 다운로드 시작 실패: {e}")
            await self.send_download_update(req.id, {
                "status": "failed",
                "message": f"다운로드 시작 실패: {str(e)}"
            })
            return False

    async def _download_task(self, req_id: int):
        """실제 다운로드 수행 태스크"""
        db = SessionLocal()
        try:
            req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
            if not req:
                await self.send_download_log(req_id, "다운로드 요청을 찾을 수 없음", "error")
                return

            # 다운로드 진행
            if req.use_proxy:
                await self._download_with_proxy_async(req, db)
            else:
                await self._download_local_async(req, db)

        except asyncio.CancelledError:
            # 다운로드 취소됨
            req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
            if req:
                req.status = StatusEnum.stopped
                db.commit()
                await self.send_download_update(req_id, {
                    "status": "stopped",
                    "message": "다운로드가 중지되었습니다."
                })
        except Exception as e:
            print(f"[ERROR] 다운로드 태스크 오류: {e}")
            req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
            if req:
                req.status = StatusEnum.failed
                req.error_message = str(e)
                db.commit()
                await self.send_download_update(req_id, {
                    "status": "failed",
                    "message": f"다운로드 실패: {str(e)}"
                })
        finally:
            db.close()

    async def _download_with_proxy_async(self, req: DownloadRequest, db: Session):
        """프록시를 사용한 비동기 다운로드"""
        await self.send_download_log(req.id, "프록시 다운로드 시작")

        # 파싱 단계
        await self.send_download_update(req.id, {
            "status": "parsing",
            "progress": 5,
            "message": "링크 파싱 중..."
        })

        # 여기서 실제 파싱 로직 구현 (기존 동기 코드를 비동기로 변환)
        # parse_url_async(req.url) 등

        # 다운로드 단계
        req.status = StatusEnum.downloading
        db.commit()

        await self.send_download_update(req.id, {
            "status": "downloading",
            "progress": 10,
            "message": "다운로드 시작..."
        })

        # 실제 파일 다운로드 구현
        await self._perform_file_download_async(req, db)

    async def _download_local_async(self, req: DownloadRequest, db: Session):
        """로컬 다운로드 비동기 구현"""
        await self.send_download_log(req.id, "로컬 다운로드 시작")

        # 로컬 다운로드 로직 구현
        req.status = StatusEnum.downloading
        db.commit()

        await self.send_download_update(req.id, {
            "status": "downloading",
            "progress": 0,
            "message": "로컬 다운로드 중..."
        })

        # 실제 로컬 다운로드 구현
        await self._perform_local_download_async(req, db)

    async def _perform_file_download_async(self, req: DownloadRequest, db: Session):
        """실제 파일 다운로드 수행"""
        try:
            # 프로그레스 업데이트 시뮬레이션 (실제로는 다운로드 진행률)
            for progress in range(10, 101, 10):
                # 취소 확인
                if req_id := req.id in self.download_tasks and self.download_tasks[req.id].cancelled():
                    return

                await asyncio.sleep(1)  # 실제로는 다운로드 진행

                await self.send_download_update(req.id, {
                    "status": "downloading",
                    "progress": progress,
                    "message": f"다운로드 중... {progress}%"
                })

            # 완료
            req.status = StatusEnum.done
            req.progress = 100
            req.download_completed_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "done",
                "progress": 100,
                "message": "다운로드 완료!"
            })

        except Exception as e:
            raise Exception(f"파일 다운로드 실패: {e}")

    async def _perform_local_download_async(self, req: DownloadRequest, db: Session):
        """로컬 다운로드 수행"""
        try:
            # 로컬 다운로드 로직 (실제 구현 필요)
            for progress in range(0, 101, 20):
                await asyncio.sleep(0.5)

                await self.send_download_update(req.id, {
                    "status": "downloading",
                    "progress": progress,
                    "message": f"로컬 다운로드 중... {progress}%"
                })

            # 완료
            req.status = StatusEnum.done
            req.progress = 100
            db.commit()

            await self.send_download_update(req.id, {
                "status": "done",
                "progress": 100,
                "message": "로컬 다운로드 완료!"
            })

        except Exception as e:
            raise Exception(f"로컬 다운로드 실패: {e}")

    async def stop_download_async(self, req_id: int, db: Session) -> bool:
        """비동기 다운로드 중지"""
        try:
            # 실행 중인 태스크 취소
            if req_id in self.download_tasks:
                task = self.download_tasks[req_id]
                task.cancel()

                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

            # DB 상태 업데이트
            req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
            if req:
                req.status = StatusEnum.stopped
                db.commit()

                await self.send_download_update(req_id, {
                    "status": "stopped",
                    "message": "다운로드가 중지되었습니다."
                })

            return True

        except Exception as e:
            print(f"[ERROR] 다운로드 중지 실패: {e}")
            return False

    def _task_cleanup(self, req_id: int):
        """태스크 정리"""
        if req_id in self.download_tasks:
            del self.download_tasks[req_id]
            print(f"[LOG] 다운로드 태스크 정리: {req_id}")

    async def get_download_status(self, req_id: int) -> Dict[str, Any]:
        """다운로드 상태 조회"""
        try:
            db = SessionLocal()
            req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()

            if not req:
                return {"error": "다운로드 요청을 찾을 수 없음"}

            return {
                "id": req.id,
                "status": req.status.value if req.status else "unknown",
                "progress": req.progress or 0,
                "url": req.url,
                "filename": req.filename,
                "error_message": req.error_message
            }
        except Exception as e:
            return {"error": f"상태 조회 실패: {e}"}
        finally:
            db.close()

    async def cleanup_all_tasks(self):
        """모든 다운로드 태스크 정리"""
        for req_id, task in list(self.download_tasks.items()):
            try:
                task.cancel()
                await asyncio.wait_for(task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            finally:
                if req_id in self.download_tasks:
                    del self.download_tasks[req_id]

        print(f"[LOG] 모든 다운로드 태스크 정리 완료")


# 전역 인스턴스
download_core = DownloadCore()