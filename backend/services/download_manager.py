# -*- coding: utf-8 -*-
"""
제대로 된 다운로드 매니저
- 메모리 기반 상태 관리
- 스레드 안전한 큐 시스템
- DB와 메모리 동기화
- 시작/정지 요청 큐 처리
"""

import asyncio
import threading
import time
from typing import Dict, Set, Optional, Any
from enum import Enum
from dataclasses import dataclass
from queue import Queue, Empty
from collections import defaultdict

from core.models import DownloadRequest, StatusEnum
from core.db import get_db


class DownloadCommand(Enum):
    START = "start"
    STOP = "stop"
    PAUSE = "pause"
    RESUME = "resume"


@dataclass
class DownloadTask:
    """다운로드 작업 정보"""
    id: int
    url: str
    use_proxy: bool
    status: StatusEnum
    task: Optional[asyncio.Task] = None
    start_time: Optional[float] = None
    stop_requested: bool = False


@dataclass
class DownloadCommand:
    """다운로드 명령"""
    command: str  # start, stop, pause, resume
    download_id: int


class DownloadManager:
    """메모리 기반 다운로드 매니저"""

    def __init__(self):
        # 메모리 상태
        self.active_downloads: Dict[int, DownloadTask] = {}
        self.command_queue: Queue = Queue()

        # 설정
        self.max_concurrent = 5
        self.max_1fichier_concurrent = 1

        # 스레드 안전성
        self._lock = threading.RLock()

        # 처리 스레드
        self._processor_running = False
        self._processor_thread = None

        # 1fichier 쿨다운
        self.last_1fichier_completion = 0
        self.fichier_cooldown_seconds = 10

    def start_processor(self):
        """명령 처리 스레드 시작"""
        with self._lock:
            if self._processor_running:
                return

            self._processor_running = True
            self._processor_thread = threading.Thread(
                target=self._process_commands,
                daemon=True,
                name="DownloadCommandProcessor"
            )
            self._processor_thread.start()
            print("[LOG] Download command processor started")

    def stop_processor(self):
        """명령 처리 스레드 정지"""
        with self._lock:
            if not self._processor_running:
                return

            self._processor_running = False
            # 종료 명령 추가
            self.command_queue.put(None)

        if self._processor_thread:
            self._processor_thread.join(timeout=5)
            print("[LOG] Download command processor stopped")

    def _process_commands(self):
        """명령 처리 메인 루프"""
        while self._processor_running:
            try:
                # 0.1초 타임아웃으로 명령 대기
                command = self.command_queue.get(timeout=0.1)

                if command is None:  # 종료 신호
                    break

                self._handle_command(command)

            except Empty:
                # 타임아웃 - 대기 중인 다운로드 확인
                self._check_pending_downloads()
                continue
            except Exception as e:
                print(f"[ERROR] Command processing error: {e}")

    def _handle_command(self, command: DownloadCommand):
        """개별 명령 처리"""
        try:
            if command.command == "start":
                self._handle_start_command(command)
            elif command.command == "stop":
                self._handle_stop_command(command)
            elif command.command == "pause":
                self._handle_pause_command(command)
            elif command.command == "resume":
                self._handle_resume_command(command)

        except Exception as e:
            print(f"[ERROR] Command handling error: {e}")

    def _handle_start_command(self, command: DownloadCommand):
        """시작 명령 처리"""
        download_id = command.download_id

        with self._lock:
            # 이미 실행 중이면 무시
            if download_id in self.active_downloads:
                print(f"[LOG] Download {download_id} already active")
                return

            # 동시 다운로드 제한 확인
            if not self._can_start_download(download_id):
                print(f"[LOG] Cannot start download {download_id} - limits reached")
                return

            # DB에서 정보 로드
            db = next(get_db())
            try:
                req = db.query(DownloadRequest).filter(
                    DownloadRequest.id == download_id
                ).first()

                if not req:
                    print(f"[ERROR] Download {download_id} not found in DB")
                    return

                # 메모리에 등록
                task = DownloadTask(
                    id=download_id,
                    url=req.url,
                    use_proxy=req.use_proxy,
                    status=StatusEnum.parsing,
                    start_time=time.time()
                )

                self.active_downloads[download_id] = task

                # DB 상태 업데이트
                req.status = StatusEnum.parsing
                db.commit()

                print(f"[LOG] Download {download_id} started (active: {len(self.active_downloads)})")

                print(f"[LOG] Download {download_id} registered successfully")

            finally:
                db.close()

    def _handle_stop_command(self, command: DownloadCommand):
        """정지 명령 처리"""
        download_id = command.download_id

        with self._lock:
            if download_id not in self.active_downloads:
                print(f"[LOG] Download {download_id} not active")
                return

            task = self.active_downloads[download_id]
            task.stop_requested = True

            # 비동기 태스크 취소
            if task.task and not task.task.done():
                task.task.cancel()

            # DB 상태 업데이트
            self._update_db_status(download_id, StatusEnum.stopped)

            print(f"[LOG] Download {download_id} stop requested")

    def _handle_pause_command(self, command: DownloadCommand):
        """일시정지 명령 처리"""
        self._handle_stop_command(command)  # 일시정지는 정지와 동일

    def _handle_resume_command(self, command: DownloadCommand):
        """재개 명령 처리"""
        # 재개는 새로운 시작 명령과 동일
        start_command = DownloadCommand("start", command.download_id)
        self._handle_start_command(start_command)

    def _can_start_download(self, download_id: int) -> bool:
        """다운로드 시작 가능 여부 확인"""
        # 전체 제한
        if len(self.active_downloads) >= self.max_concurrent:
            return False

        # 1fichier 제한 확인
        db = next(get_db())
        try:
            req = db.query(DownloadRequest).filter(
                DownloadRequest.id == download_id
            ).first()

            if req and "1fichier.com" in req.url and not req.use_proxy:
                # 1fichier 로컬 다운로드 개수 확인
                fichier_count = sum(
                    1 for task in self.active_downloads.values()
                    if "1fichier.com" in task.url and not task.use_proxy
                )

                if fichier_count >= self.max_1fichier_concurrent:
                    return False

                # 쿨다운 확인
                if self._is_1fichier_cooldown():
                    return False

        finally:
            db.close()

        return True

    def _is_1fichier_cooldown(self) -> bool:
        """1fichier 쿨다운 중인지 확인"""
        if self.last_1fichier_completion == 0:
            return False

        elapsed = time.time() - self.last_1fichier_completion
        return elapsed < self.fichier_cooldown_seconds

    def _check_pending_downloads(self):
        """대기 중인 다운로드 확인 및 시작"""
        try:
            db = next(get_db())
            try:
                # pending 상태인 다운로드들 조회
                pending = db.query(DownloadRequest).filter(
                    DownloadRequest.status == StatusEnum.pending
                ).order_by(DownloadRequest.requested_at.asc()).all()

                for req in pending:
                    if self._can_start_download(req.id):
                        # 자동 시작 명령 추가
                        command = DownloadCommand("start", req.id)
                        self.command_queue.put(command)
                        break  # 한 번에 하나씩

            finally:
                db.close()

        except Exception as e:
            print(f"[ERROR] Check pending downloads failed: {e}")

    def _update_db_status(self, download_id: int, status: StatusEnum):
        """DB 상태 업데이트"""
        try:
            db = next(get_db())
            try:
                req = db.query(DownloadRequest).filter(
                    DownloadRequest.id == download_id
                ).first()

                if req:
                    req.status = status
                    db.commit()

            finally:
                db.close()

        except Exception as e:
            print(f"[ERROR] DB status update failed: {e}")

    def _cleanup_download(self, download_id: int):
        """다운로드 정리"""
        with self._lock:
            task = self.active_downloads.pop(download_id, None)
            if task:
                # 1fichier 완료 시 쿨다운 시작
                if ("1fichier.com" in task.url and not task.use_proxy and
                    not task.stop_requested):
                    self.last_1fichier_completion = time.time()

                print(f"[LOG] Download {download_id} cleaned up (active: {len(self.active_downloads)})")

    # 공개 API
    def start_download(self, download_id: int):
        """다운로드 시작 요청"""
        command = DownloadCommand("start", download_id)
        self.command_queue.put(command)

    def stop_download(self, download_id: int):
        """다운로드 정지 요청"""
        command = DownloadCommand("stop", download_id)
        self.command_queue.put(command)

    def pause_download(self, download_id: int):
        """다운로드 일시정지 요청"""
        command = DownloadCommand("pause", download_id)
        self.command_queue.put(command)

    def resume_download(self, download_id: int):
        """다운로드 재개 요청"""
        command = DownloadCommand("resume", download_id)
        self.command_queue.put(command)

    def finish_download(self, download_id: int, success: bool = True):
        """다운로드 완료 처리"""
        self._cleanup_download(download_id)

        # DB 상태 업데이트
        status = StatusEnum.done if success else StatusEnum.failed
        self._update_db_status(download_id, status)

    def is_download_active(self, download_id: int) -> bool:
        """다운로드 활성 상태 확인"""
        with self._lock:
            return download_id in self.active_downloads

    def is_download_stopped(self, download_id: int) -> bool:
        """다운로드 정지 요청 확인"""
        with self._lock:
            task = self.active_downloads.get(download_id)
            return task.stop_requested if task else False

    def get_active_count(self) -> int:
        """활성 다운로드 수"""
        with self._lock:
            return len(self.active_downloads)

    def get_active_downloads(self) -> Dict[int, Dict]:
        """활성 다운로드 목록"""
        with self._lock:
            return {
                task_id: {
                    "url": task.url,
                    "use_proxy": task.use_proxy,
                    "status": task.status.value,
                    "start_time": task.start_time,
                    "stop_requested": task.stop_requested
                }
                for task_id, task in self.active_downloads.items()
            }


# 전역 다운로드 매니저 인스턴스
download_manager = DownloadManager()