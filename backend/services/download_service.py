# -*- coding: utf-8 -*-
import asyncio
import os
import time
import threading
import httpx
import cloudscraper
import re
import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from urllib.parse import urlparse, unquote

from core.models import DownloadRequest, StatusEnum
from core.config import get_download_path
from core.db import get_db
from core.i18n import get_message
from core.proxy_manager import get_unused_proxies, mark_proxy_used
from services.sse_manager import sse_manager
from services.download_manager import download_manager
from core.download_core import download_general_file
from core.download_core import send_sse_message
# from core.parser_service import get_or_parse_direct_link  # 동기 함수 제거


class AsyncDownloadService:
    def __init__(self):
        self.download_tasks: Dict[int, asyncio.Task] = {}
        # 다운로드용 전용 ThreadPoolExecutor
        self.executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="Download")

    async def start(self):
        """서비스 시작 - 다운로드 매니저와 연동"""
        print("[LOG] AsyncDownloadService started")

        # 다운로드 매니저 제거됨 - 단순화

        # 시작시 상태 초기화 (다운로드 시작은 안함)
        try:
            await self._initialize_download_status()
        except Exception as init_error:
            print(f"[ERROR] 상태 초기화 실패 (서버는 계속 시작): {init_error}")
        print("[LOG] 다운로드 상태 초기화 완료")

        # 대기시간 모니터링 시작 (비동기 개선)
        try:
            self.wait_monitor_task = asyncio.create_task(self._monitor_wait_timeouts_fixed())
            print("[LOG] Wait timeout monitor started (fixed)")
        except Exception as monitor_error:
            print(f"[ERROR] 대기시간 모니터 시작 실패: {monitor_error}")
            self.wait_monitor_task = None

        # 다운로드 매니저 상태 모니터링 시작 (비동기 개선)
        try:
            self.manager_monitor_task = asyncio.create_task(self._monitor_download_manager_fixed())
            print("[LOG] Download manager monitor started (fixed)")
        except Exception as manager_monitor_error:
            print(f"[ERROR] 다운로드 매니저 모니터 시작 실패: {manager_monitor_error}")
            self.manager_monitor_task = None

    async def stop(self):
        """서비스 정지 및 정리"""
        print(f"[LOG] Stopping AsyncDownloadService... ({len(self.download_tasks)} active tasks)")

        # 다운로드 매니저 제거됨

        # 대기시간 모니터 정리
        try:
            if hasattr(self, 'wait_monitor_task') and self.wait_monitor_task and not self.wait_monitor_task.done():
                self.wait_monitor_task.cancel()
                try:
                    await self.wait_monitor_task
                except asyncio.CancelledError:
                    pass
                print("[LOG] Wait timeout monitor stopped")
        except Exception as monitor_stop_error:
            print(f"[ERROR] 대기시간 모니터 정지 실패 (무시): {monitor_stop_error}")

        # 다운로드 매니저 모니터 정리
        try:
            if hasattr(self, 'manager_monitor_task') and self.manager_monitor_task and not self.manager_monitor_task.done():
                self.manager_monitor_task.cancel()
                try:
                    await self.manager_monitor_task
                except asyncio.CancelledError:
                    pass
                print("[LOG] Download manager monitor stopped")
        except Exception as manager_monitor_stop_error:
            print(f"[ERROR] 다운로드 매니저 모니터 정지 실패 (무시): {manager_monitor_stop_error}")

        # 모든 다운로드 태스크 취소
        cancel_tasks = []
        for task_id, task in self.download_tasks.items():
            if not task.done():
                print(f"[LOG] Cancelling download task {task_id}")
                task.cancel()
                cancel_tasks.append(task)

        # 취소된 태스크들 정리 (타임아웃 설정)
        if cancel_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*cancel_tasks, return_exceptions=True),
                    timeout=3.0
                )
                print(f"[LOG] {len(cancel_tasks)} tasks cancelled gracefully")
            except asyncio.TimeoutError:
                print(
                    f"[WARNING] {len(cancel_tasks)} tasks did not cancel in time")

        self.download_tasks.clear()

        # ThreadPoolExecutor 정리 (refresh 대응 강화)
        if self.executor:
            try:
                print("[LOG] ThreadPoolExecutor graceful shutdown initiating...")

                # 1단계: 정상 종료 시도 (짧은 시간)
                self.executor.shutdown(wait=False)

                # 2단계: 최소 대기 후 강제 정리
                import concurrent.futures
                import threading
                import time
                time.sleep(0.2)  # refresh 대응으로 대기 시간 단축

                # 3단계: 다운로드 스레드들 강제 daemon 변경
                active_threads = [t for t in threading.enumerate() if "Download" in t.name]
                if active_threads:
                    print(f"[LOG] Converting {len(active_threads)} download threads to daemon")
                    for thread in active_threads:
                        try:
                            thread.daemon = True
                        except Exception as te:
                            print(f"[LOG] Failed to set daemon for {thread.name}: {te}")

                # 4단계: ThreadPoolExecutor 인스턴스 직접 정리
                try:
                    self.executor._threads.clear()  # 스레드 집합 강제 비우기
                except:
                    pass

                print("[LOG] ThreadPoolExecutor shutdown completed with refresh support")
            except Exception as e:
                print(f"[WARNING] ThreadPoolExecutor shutdown error: {e}")
            finally:
                self.executor = None  # 참조 해제

        print("[LOG] AsyncDownloadService stopped")

    async def start_download(self, request_id: int, lang: str = "ko", use_proxy: bool = True) -> bool:
        """비동기 다운로드 시작 (단순화)"""
        # 다운로드 태스크 바로 시작
        task = asyncio.create_task(
            self._download_file_async(request_id, lang, use_proxy)
        )
        self.download_tasks[request_id] = task
        task.add_done_callback(lambda t: self._cleanup_task(request_id))

        print(f"[LOG] Download task started: {request_id}")
        return True

    async def cancel_download(self, request_id: int) -> bool:
        """다운로드 취소"""
        # 1. 로컬 태스크 취소
        if request_id in self.download_tasks:
            task = self.download_tasks[request_id]
            if not task.done():
                task.cancel()
                print(f"[LOG] 다운로드 태스크 취소: {request_id}")

        # 2. 대기 중인 다운로드 처리
        try:
            from utils.wait_store import wait_store
            if wait_store.get_remaining_time(request_id) is not None:
                wait_store.cancel_wait(request_id)
                print(f"[LOG] 대기 중인 다운로드 취소: {request_id}")
        except Exception as wait_error:
            print(f"[LOG] 대기 취소 처리 중 오류 (무시): {wait_error}")

        # 3. DB 상태 업데이트
        try:
            db = next(get_db())
            req = db.query(DownloadRequest).filter(DownloadRequest.id == request_id).first()
            if req and req.status in [StatusEnum.pending, StatusEnum.waiting, StatusEnum.parsing, StatusEnum.downloading, StatusEnum.proxying]:
                req.status = StatusEnum.stopped
                db.commit()

                # SSE 업데이트 (완전한 정보 포함)
                progress = 0.0
                if req.total_size and req.total_size > 0 and req.downloaded_size:
                    progress = min(100.0, (req.downloaded_size / req.total_size) * 100)

                await sse_manager.broadcast_message("status_update", {
                    "id": req.id,
                    "url": req.url or "",
                    "file_name": req.file_name or "",
                    "status": "stopped",
                    "error": req.error or "",
                    "progress": progress,
                    "downloaded_size": req.downloaded_size or 0,
                    "total_size": req.total_size or 0,
                    "save_path": req.save_path or "",
                    "use_proxy": req.use_proxy if req.use_proxy is not None else False,
                    "message": "다운로드가 정지되었습니다."
                })
                print(f"[LOG] 다운로드 상태를 stopped로 변경: {request_id}")
            db.close()
        except Exception as db_error:
            print(f"[LOG] DB 상태 업데이트 오류: {db_error}")

        print(f"[LOG] 다운로드 취소 완료: {request_id}")
        return True

    def _cleanup_task(self, request_id: int):
        """태스크 정리"""
        if request_id in self.download_tasks:
            del self.download_tasks[request_id]
            print(f"[LOG] Cleaned up download task: {request_id}")

    def _create_download_callback(self):
        """다운로드 콜백 생성"""
        async def download_callback(download_id: int, url: str, use_proxy: bool):
            """다운로드 매니저에서 호출할 비동기 콜백"""
            # 실제 다운로드 태스크 시작
            task = asyncio.create_task(
                self._download_file_async(download_id, "ko", use_proxy)
            )
            self.download_tasks[download_id] = task

            # 태스크 완료 시 자동 정리
            task.add_done_callback(lambda t: self._cleanup_task(download_id))
            print(f"[LOG] Download task created for {download_id}")

        return download_callback

    async def _initialize_download_status(self):
        """서버 시작시 다운로드 상태만 초기화 (자동 시작은 안함)"""
        try:
            db = next(get_db())

            # 진행중인 다운로드들을 모두 pending 상태로 변경
            interrupted_downloads = db.query(DownloadRequest).filter(
                DownloadRequest.status.in_([
                    StatusEnum.downloading,
                    StatusEnum.proxying,
                    StatusEnum.parsing,
                    StatusEnum.waiting
                ])
            ).all()

            # waiting 상태인 다운로드들의 대기시간도 정리
            if interrupted_downloads:
                from utils.wait_store import wait_store
                for req in interrupted_downloads:
                    if req.status == StatusEnum.waiting:
                        try:
                            wait_store.cancel_wait(req.id)
                            print(f"[LOG] 대기시간 정리: {req.id}")
                        except Exception:
                            pass

            if interrupted_downloads:
                print(f"[LOG] {len(interrupted_downloads)}개의 중단된 다운로드를 pending 상태로 변경")

                for req in interrupted_downloads:
                    req.status = StatusEnum.pending
                    print(f"[LOG] 다운로드 {req.id} ({req.file_name}) -> pending 상태로 변경")

                db.commit()
            else:
                print(f"[LOG] 상태 초기화할 다운로드가 없습니다")

            db.close()

        except Exception as e:
            print(f"[LOG] 상태 초기화 실패: {e}")

    async def _resume_interrupted_downloads(self):
        """서버 재시작 시 진행중인 다운로드를 자동 재개하고 대기중인 다운로드를 시작"""
        try:
            db = next(get_db())
            
            # 1. 진행중인 다운로드들을 모두 대기 상태로 변경
            interrupted_downloads = db.query(DownloadRequest).filter(
                DownloadRequest.status.in_([
                    StatusEnum.downloading,
                    StatusEnum.proxying,
                    StatusEnum.parsing,
                    StatusEnum.waiting
                ])
            ).all()
            
            if interrupted_downloads:
                print(f"[LOG] {len(interrupted_downloads)}개의 중단된 다운로드를 대기 상태로 변경")
                
                for req in interrupted_downloads:
                    req.status = StatusEnum.pending
                    print(f"[LOG] 다운로드 {req.id} ({req.file_name}) -> pending 상태로 변경")
                
                db.commit()
            
            # 2. 대기중인 다운로드만 조회 (stopped 상태는 제외)
            all_pending_downloads = db.query(DownloadRequest).filter(
                DownloadRequest.status == StatusEnum.pending
            ).order_by(DownloadRequest.requested_at.asc()).all()
            
            # IMPORTANT: stopped 상태인 다운로드는 절대 시작하지 않음
            print(f"[LOG] stopped 상태인 다운로드는 자동 시작에서 제외됨")
            
            if all_pending_downloads:
                print(f"[LOG] 총 {len(all_pending_downloads)}개의 대기중인 다운로드 발견")
                
                # 1fichier와 일반 다운로드 분류
                fichier_downloads = [req for req in all_pending_downloads if "1fichier.com" in req.url.lower()]
                general_downloads = [req for req in all_pending_downloads if "1fichier.com" not in req.url.lower()]
                
                print(f"[LOG] - 1fichier 다운로드: {len(fichier_downloads)}개")
                print(f"[LOG] - 일반/프록시 다운로드: {len(general_downloads)}개")
                
                started_count = 0
                
                # ENV에서 최대 동시 다운로드 수 설정 읽기
                max_total = download_manager.max_concurrent
                
                # 1fichier 다운로드 최대 1개 시작 (프록시/로컬 구분 없이)
                if fichier_downloads and started_count < max_total:
                    req = fichier_downloads[0]  # 가장 오래된 것 하나만
                    print(f"[LOG] 1fichier 다운로드 시작: ID {req.id} ({req.file_name}), use_proxy={req.use_proxy}")
                    
                    success = await self.start_download(req.id, "ko", req.use_proxy)
                    if success:
                        started_count += 1
                        print(f"[LOG] 1fichier 다운로드 {req.id} 시작 성공")
                    else:
                        print(f"[LOG] 1fichier 다운로드 {req.id} 시작 실패")
                    
                    # 다음 다운로드와 간격
                    await asyncio.sleep(2)
                
                # 일반/프록시 다운로드 시작  
                for req in general_downloads:
                    if started_count >= max_total:  # 전체 최대값까지만
                        break
                        
                    print(f"[LOG] 일반/프록시 다운로드 시작: ID {req.id} ({req.file_name}), use_proxy={req.use_proxy}")
                    
                    success = await self.start_download(req.id, "ko", req.use_proxy)
                    if success:
                        started_count += 1
                        print(f"[LOG] 일반/프록시 다운로드 {req.id} 시작 성공")
                    else:
                        print(f"[LOG] 일반/프록시 다운로드 {req.id} 시작 실패")
                    
                    # 다운로드 시작 간격 (서버 부하 방지)
                    if started_count < max_total:
                        await asyncio.sleep(2)
                
                print(f"[LOG] 총 {started_count}개의 다운로드를 자동 시작했습니다")
            else:
                print(f"[LOG] 대기중인 다운로드가 없습니다")
                        
            db.close()
            
        except Exception as e:
            print(f"[LOG] 자동 재개 실패: {e}")

    async def _download_file_async(self, request_id: int, lang: str, use_proxy: bool):
        """비동기 다운로드 메인 함수 - 강화된 오류 격리"""
        try:
            print("=" * 80)
            print(f"[LOG] *** ASYNC DOWNLOAD START ***")
            print(
                f"[LOG] Request ID: {request_id}, Lang: {lang}, Use Proxy: {use_proxy}")
            print(f"[LOG] Started at: {time.strftime('%H:%M:%S')}")
            print("=" * 80)

            # 비동기 다운로드 작업 직접 실행 - 이미 비동기로 구현되어 있음
            await self._download_file_async_impl(request_id, lang, use_proxy)

        except asyncio.CancelledError:
            print(f"[LOG] Download {request_id} was cancelled")
            try:
                await self._update_download_status(request_id, StatusEnum.stopped)
            except Exception as status_error:
                print(f"[ERROR] 취소된 다운로드 상태 업데이트 실패 (ID {request_id}): {status_error}")

            # 취소시에도 매니저에 알림
            try:
                download_manager.finish_download(request_id, success=False)
                print(f"[LOG] Download manager notified of cancelled download {request_id}")
            except Exception as manager_error:
                print(f"[ERROR] 다운로드 매니저 알림 실패 (ID {request_id}): {manager_error}")

        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__

            # 예외 종류에 따른 상세 로깅
            if "decompressing" in error_msg.lower():
                print(f"[ERROR] 다운로드 {request_id} 압축 해제 오류: {error_msg}")
                print(f"[ERROR] 서버가 잘못된 압축 데이터를 전송했습니다")
            elif "stream" in error_msg.lower() and "closed" in error_msg.lower():
                print(f"[ERROR] 다운로드 {request_id} 연결 오류: {error_msg}")
                print(f"[ERROR] 네트워크 연결이 예기치 않게 중단되었습니다")
            else:
                print(f"[ERROR] 다운로드 {request_id} 일반 오류 ({error_type}): {error_msg}")

            print(f"[LOG] 오류로 인한 다운로드 실패 - 서버는 계속 동작합니다")

            # 상태 업데이트 실패도 격리
            try:
                await self._update_download_status(request_id, StatusEnum.failed, error_msg)
            except Exception as status_error:
                print(f"[ERROR] 실패한 다운로드 상태 업데이트 실패 (ID {request_id}): {status_error}")

            # 매니저에 완료 알림
            try:
                download_manager.finish_download(request_id, success=False)
                print(f"[LOG] Download manager notified of failed download {request_id}")
            except Exception as manager_error:
                print(f"[ERROR] 다운로드 매니저 알림 실패 (ID {request_id}): {manager_error}")

            print(f"[LOG] 다운로드 오류 처리 완료 - 서버 정상 가동 중")

    async def _download_file_async_impl(self, request_id: int, lang: str, use_proxy: bool):
        """비동기 다운로드 구현 - URL 타입에 따라 적절한 다운로더 선택"""
        # 부모 감시 스레드 시작 (자식 프로세스에서만 동작)
        if os.getppid() != os.getpid():
            threading.Thread(target=self._exit_if_parent_dead,
                             daemon=True).start()

        start_time = time.time()
        max_duration = 300  # 5분

        db = next(get_db())
        try:
            req = db.query(DownloadRequest).filter(
                DownloadRequest.id == request_id).first()
            if req is None:
                print(f"[ERROR] DownloadRequest not found: {request_id}")
                return
            
            # URL 타입에 따라 적절한 다운로더 선택
            # 주의: DB에 저장된 use_proxy 값을 사용 (파라미터는 무시)
            actual_use_proxy = req.use_proxy
            print(f"[LOG] DB use_proxy 값: {actual_use_proxy} (파라미터: {use_proxy})")
            
            try:
                if "1fichier.com" in req.url.lower():
                    print(f"[LOG] 1fichier URL 감지 - 새로운 분리 방식 사용: {req.url}")
                    await self._download_1fichier_with_parsing(request_id, lang, actual_use_proxy)
                else:
                    print(f"[LOG] 일반 URL 감지: {req.url}")
                    await self._download_general_file(request_id, lang, actual_use_proxy, req, db)
            except Exception as download_inner_error:
                print(f"[ERROR] 다운로드 핸들러 내부 오류: {download_inner_error}")
                print(f"[LOG] 다운로드 서비스에서 오류를 처리하여 서버 안정성 유지")
                # 예외를 다시 던지지 않음 - 상위에서 정상적으로 처리되도록 함
                # 다운로드 실패로 표시하기 위해 req 상태 업데이트
                if 'req' in locals() and req:
                    req.status = StatusEnum.failed
                    req.error_message = str(download_inner_error)
                    db.commit()
                
        finally:
            db.close()
    
    async def _download_1fichier_file(self, request_id: int, lang: str, use_proxy: bool, req, db):
        """1fichier 전용 다운로드 로직 - 완전히 비동기 구현"""
        try:
            download_path = get_download_path()
            print(f"[LOG] Download path: {download_path}")

            # 파일 경로 설정
            base_filename = req.file_name if req.file_name else f"download_{request_id}"
            file_path = download_path / base_filename
            part_file_path = download_path / (base_filename + ".part")

            initial_downloaded_size = 0

            # .part 파일이 있으면 그것을 우선 사용
            if part_file_path.exists():
                file_path = part_file_path
                initial_downloaded_size = part_file_path.stat().st_size
                print(f"[LOG] Resuming from .part file: {initial_downloaded_size} bytes")
            elif file_path.exists():
                initial_downloaded_size = file_path.stat().st_size
                print(f"[LOG] Resuming from existing file: {initial_downloaded_size} bytes")
            else:
                # 새 다운로드는 .part 파일로 시작
                file_path = part_file_path
                print(f"[LOG] Starting new download: {file_path}")
                if req.downloaded_size > 0:
                    req.downloaded_size = 0

            # **완전히 비동기 1fichier 파싱 및 다운로드**
            print(f"[LOG] 1fichier 비동기 파싱 시작")

            # 상태를 parsing으로 변경
            req.status = StatusEnum.parsing
            db.commit()
            await self._notify_status_update_async(db, req.id)

            # 비동기 파싱 함수 호출
            from core.parser_service import parse_direct_link_simple_async

            result = await parse_direct_link_simple_async(
                req.url,
                password=None,
                proxies=None,
                use_proxy=use_proxy,
                proxy_addr=None,
                req=req
            )

            if result is None or result == (None, None):
                raise Exception("파싱 실패")

            direct_link, html_content = result

            if direct_link == "WAIT_REGISTERED":
                # 대기시간 등록됨
                db.commit()
                print(f"[LOG] 대기시간 등록 완료: {req.id}")

                # 다운로드 매니저에게 완료 알림 제거 - 대기 상태는 완료가 아님
                print(f"[LOG] 대기 상태이므로 다운로드 매니저에 완료 알림 안함")
                return
            elif direct_link:
                # 즉시 다운로드 시작
                await self._download_file_from_direct_link(req, file_path, direct_link, db)
                return
            else:
                raise Exception("다운로드 링크를 찾을 수 없음")

        except Exception as e:
            print(f"[ERROR] 1fichier download error: {e}")
            await self._update_download_status(request_id, StatusEnum.failed, str(e))

    async def _download_file_from_direct_link(self, req, file_path, direct_link, db):
        """직접 링크로 파일 다운로드 (완전히 비동기)"""
        import httpx

        print(f"[LOG] 직접 링크로 다운로드 시작: {direct_link}")

        # 상태를 downloading으로 변경
        req.status = StatusEnum.downloading
        db.commit()
        await self._notify_status_update_async(db, req.id)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                async with client.stream('GET', direct_link) as response:
                    response.raise_for_status()

                    total_size = int(response.headers.get('Content-Length', 0))
                    req.total_size = total_size
                    db.commit()

                    downloaded_size = 0
                    with open(str(file_path), 'wb') as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            f.write(chunk)
                            downloaded_size += len(chunk)
                            req.downloaded_size = downloaded_size

                            # 주기적으로 DB 업데이트
                            if downloaded_size % (1024 * 1024) == 0:  # 1MB마다
                                db.commit()
                                await self._notify_status_update_async(db, req.id)

                    # 완료
                    req.status = StatusEnum.done
                    req.downloaded_size = total_size
                    db.commit()
                    await self._notify_status_update_async(db, req.id)
                    print(f"[LOG] 다운로드 완료: {file_path}")

        except Exception as e:
            print(f"[LOG] 다운로드 실패: {e}")
            req.status = StatusEnum.failed
            req.error = str(e)
            db.commit()
            await self._notify_status_update_async(db, req.id)
    
    async def _download_general_file(self, request_id: int, lang: str, use_proxy: bool, req, db):
        """일반 파일 다운로드 로직 (비동기)"""
        try:
            print(f"[LOG] 일반 다운로드 시작: {req.url}")

            # 일반 다운로드 함수 호출 (기존 구현 활용)
            await download_general_file(request_id, language=lang, use_proxy=use_proxy)

        except Exception as e:
            print(f"[ERROR] General download error: {e}")
            # 비동기적으로 상태 업데이트
            await self._update_download_status(request_id, StatusEnum.failed, str(e))

    async def _perform_download_async(self, req, file_path, initial_downloaded_size, use_proxy, db):
        """완전히 비동기 다운로드 수행"""

        print(f"[LOG] Performing async download for {req.id}")

        # 시작 시간 기록
        start_time = time.time()
        max_duration = 300  # 5분

        # 프록시 설정
        available_proxies = []
        if use_proxy:
            # 프록시 다운로드인 경우에만 상태를 proxying으로 설정
            req.status = StatusEnum.proxying
            db.commit()
            await self._notify_status_update_async(db, req.id)
            available_proxies = get_unused_proxies(db)
            print(f"[LOG] 사용 가능한 프록시: {len(available_proxies)}개")
        else:
            # 로컬 다운로드인 경우 바로 parsing 상태로 설정
            req.status = StatusEnum.parsing
            db.commit()
            await self._notify_status_update_async(db, req.id)

        # 이어받기인 경우 direct_link 재파싱
        force_reparse = initial_downloaded_size > 0
        if force_reparse:
            print(f"[LOG] 이어받기 감지. direct_link 재파싱 수행")

        # Direct Link 파싱 with 프록시 순환
        direct_link = None
        used_proxy_addr = None
        download_proxies = None

        # URL 유효성 검증 (파일 존재 확인)
        try:
            print(f"[LOG] URL 유효성 검증: {req.url}")
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                test_response = await client.get(req.url)
                if test_response.status_code == 200:
                    # HTML 내용에서 파일이 존재하지 않는다는 메시지 확인
                    html_content = test_response.text.lower()
                    file_not_found_indicators = [
                        'file not found', 'fichier introuvable', '파일을 찾을 수 없',
                        'does not exist', 'n\'existe pas', 'error 404', 'not found',
                        'file has been removed', 'fichier supprimé', '파일이 삭제'
                    ]

                    if any(indicator in html_content for indicator in file_not_found_indicators):
                        print(f"[LOG] 파일이 존재하지 않거나 삭제됨")
                        raise Exception("파일이 존재하지 않거나 삭제되었습니다.")

                    print(f"[LOG] URL 유효성 검증 통과")
                else:
                    print(f"[LOG] URL 접근 실패: HTTP {test_response.status_code}")
                    raise Exception(f"URL에 접근할 수 없습니다: HTTP {test_response.status_code}")
        except Exception as e:
            print(f"[LOG] URL 검증 실패: {e}")
            raise Exception(f"URL 검증 실패: {e}")

        # 비동기 파싱으로 대체 (기존 get_or_parse_direct_link 대신)
        direct_link = await self._parse_direct_link_async(req, use_proxy, force_reparse, available_proxies)

        if direct_link == "WAIT_REGISTERED":
            print(f"[LOG] 대기시간 감지됨, 백그라운드에서 대기 중: ID {req.id}")
            return True  # 성공적으로 대기 등록됨
        elif not direct_link:
            raise Exception("Cannot find download link from 1fichier. Site structure may have changed or proxy issue.")

        # ... 나머지 다운로드 로직은 동일
        print(f"[LOG] 비동기 다운로드 파싱 완료, 실제 다운로드 시작")

    async def _parse_1fichier_async(self, req, use_proxy):
        """1fichier 비동기 파싱 - 대기시간 감지 즉시 반환"""
        import httpx
        import re
        from utils.wait_store import wait_store
        from services.sse_manager import sse_manager

        # 상태 업데이트
        req.status = StatusEnum.parsing

        try:
            # 비동기 HTTP 요청으로 1fichier 페이지 로드
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(req.url)

                if response.status_code != 200:
                    print(f"[LOG] 페이지 로드 실패: HTTP {response.status_code}")
                    return None

                # 다운로드 링크 찾기
                direct_link_patterns = [
                    r'href="(https://[a-z0-9\-]+\.1fichier\.com/[^"]+)"[^>]*class="[^"]*(?:ok|btn|download)[^"]*"',
                    r'<a[^>]+href="(https://[a-z0-9\-]+\.1fichier\.com/[^"]+)"[^>]*>.*?(?:Click|Download|download)[^<]*</a>',
                    r'href="(https://[a-z0-9\-]+\.1fichier\.com/c\d+)"',
                ]

                for pattern in direct_link_patterns:
                    match = re.search(pattern, response.text, re.IGNORECASE | re.DOTALL)
                    if match:
                        direct_link = match.group(1)
                        print(f"[LOG] ✅ 다운로드 링크 발견: {direct_link}")
                        return direct_link

                # 대기시간 패턴 검사
                wait_patterns = [
                    r'var\s+ct\s*=\s*(\d+)',
                    r'countdown["\s]*[=:]["\s]*(\d+)',
                    r'wait["\s]*[=:]["\s]*(\d+)'
                ]

                for pattern in wait_patterns:
                    matches = re.findall(pattern, response.text, re.IGNORECASE)
                    if matches:
                        wait_seconds = int(matches[0])
                        print(f"[LOG] 대기시간 감지: {wait_seconds}초")

                        # 즉시 대기시간 등록
                        wait_store.start_wait(req.id, wait_seconds, req.url)
                        req.status = StatusEnum.waiting

                        # SSE 전송
                        await sse_manager.broadcast_message("wait_countdown", {
                            "id": req.id,
                            "remaining_time": wait_seconds,
                            "wait_message": f"대기 중 ({wait_seconds//60}분 {wait_seconds%60}초)" if wait_seconds >= 60 else f"대기 중 ({wait_seconds}초)",
                            "total_wait_time": wait_seconds,
                            "proxy_addr": None,
                            "url": req.url,
                            "file_name": req.file_name or ""
                        })

                        print(f"[LOG] 대기시간 등록 완료: {wait_seconds}초")
                        return "WAIT_REGISTERED"

                print(f"[LOG] 다운로드 링크나 대기시간을 찾을 수 없음")
                return None

        except Exception as e:
            print(f"[LOG] 1fichier 파싱 오류: {e}")
            return None

    def _download_with_direct_link(self, req, file_path, direct_link, use_proxy, db):
        """직접 링크로 파일 다운로드 (ThreadPoolExecutor)"""
        import httpx
        import time

        print(f"[LOG] 직접 링크로 다운로드 시작: {direct_link}")

        # 상태를 downloading으로 변경
        req.status = StatusEnum.downloading
        db.commit()
        self._notify_status_update_sync(db, req.id)

        # 간단한 다운로드 구현
        try:
            with httpx.stream('GET', direct_link, timeout=30) as r:
                r.raise_for_status()

                total_size = int(r.headers.get('Content-Length', 0))
                req.total_size = total_size
                db.commit()

                downloaded_size = 0
                with open(str(file_path), 'wb') as f:
                    for chunk in r.iter_bytes(chunk_size=8192):
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        req.downloaded_size = downloaded_size

                        # 주기적으로 DB 업데이트
                        if downloaded_size % (1024 * 1024) == 0:  # 1MB마다
                            db.commit()
                            self._notify_status_update_sync(db, req.id)

                # 완료
                req.status = StatusEnum.done
                req.downloaded_size = total_size
                db.commit()
                self._notify_status_update_sync(db, req.id)
                print(f"[LOG] 다운로드 완료: {file_path}")

        except Exception as e:
            print(f"[LOG] 다운로드 실패: {e}")
            req.status = StatusEnum.failed
            req.error = str(e)
            db.commit()
            self._notify_status_update_sync(db, req.id)

    async def _notify_status_update_async(self, db, download_id):
        """비동기 상태 업데이트"""
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if req:
            progress = 0.0
            if req.total_size and req.total_size > 0 and req.downloaded_size:
                progress = min(100.0, (req.downloaded_size / req.total_size) * 100)

            from services.sse_manager import sse_manager
            await sse_manager.broadcast_message("status_update", {
                "id": req.id,
                "url": req.url or "",
                "file_name": req.file_name or "",
                "status": req.status.value if req.status else "unknown",
                "error": req.error or "",
                "progress": progress,
                "downloaded_size": req.downloaded_size or 0,
                "total_size": req.total_size or 0,
                "save_path": req.save_path or "",
                "use_proxy": req.use_proxy if req.use_proxy is not None else False
            })

    def _perform_download(self, req, file_path, initial_downloaded_size, use_proxy, db):
        """실제 다운로드 수행"""
        
        print(f"[LOG] Performing download for {req.id}")
        
        # 시작 시간 기록
        start_time = time.time()
        max_duration = 300  # 5분
        
        # 프록시 설정
        available_proxies = []
        if use_proxy:
            # 프록시 다운로드인 경우에만 상태를 proxying으로 설정
            req.status = StatusEnum.proxying
            db.commit()
            self._notify_status_update_sync(db, req.id)
            available_proxies = get_unused_proxies(db)
            print(f"[LOG] 사용 가능한 프록시: {len(available_proxies)}개")
        else:
            # 로컬 다운로드인 경우 바로 parsing 상태로 설정
            req.status = StatusEnum.parsing
            db.commit()
            self._notify_status_update_sync(db, req.id)
        
        # 이어받기인 경우 direct_link 재파싱
        force_reparse = initial_downloaded_size > 0
        if force_reparse:
            print(f"[LOG] 이어받기 감지. direct_link 재파싱 수행")
        
        # Direct Link 파싱 with 프록시 순환
        direct_link = None
        used_proxy_addr = None
        download_proxies = None
        
        # URL 유효성 검증 (파일 존재 확인)
        try:
            print(f"[LOG] URL 유효성 검증: {req.url}")
            test_response = httpx.get(req.url, timeout=10)
            if test_response.status_code == 200:
                # HTML 내용에서 파일이 존재하지 않는다는 메시지 확인
                html_content = test_response.text.lower()
                file_not_found_indicators = [
                    'file not found', 'fichier introuvable', '파일을 찾을 수 없', 
                    'does not exist', 'n\'existe pas', 'error 404', 'not found',
                    'file has been removed', 'fichier supprimé', '파일이 삭제'
                ]
                
                if any(indicator in html_content for indicator in file_not_found_indicators):
                    print(f"[LOG] 파일이 존재하지 않거나 삭제됨")
                    raise Exception("파일이 존재하지 않거나 삭제되었습니다.")
                    
                print(f"[LOG] URL 유효성 검증 통과")
            else:
                print(f"[LOG] URL 접근 실패: HTTP {test_response.status_code}")
                raise Exception(f"URL에 접근할 수 없습니다: HTTP {test_response.status_code}")
        except Exception as e:
            print(f"[LOG] URL 검증 실패: {e}")
            raise Exception(f"URL 검증 실패: {e}")
        
        if use_proxy and available_proxies:
            # 프록시 순환하여 direct_link 파싱
            print(f"[LOG] *** 프록시 순환 시작! 총 {len(available_proxies)}개 프록시 ***")
            for i, proxy_addr in enumerate(available_proxies):
                # 상태 체크 - stopped면 중단
                db.refresh(req)
                if req.status == StatusEnum.stopped:
                    print(f"[LOG] 프록시 파싱 중 정지 요청 감지. 중단합니다.")
                    return
                
                # SSE로 프록시 시도 상태 전송
                send_sse_message("proxy_trying", {
                    "id": req.id,
                    "proxy": proxy_addr,
                    "step": "parsing",
                    "current": i + 1,
                    "total": len(available_proxies)
                })
                
                try:
                    # 동기 파싱 완전히 제거 - 비동기 파싱으로 대체 불가능 (ThreadPoolExecutor)
                    print(f"[LOG] 프록시 파싱 건너뛰기 - 대기시간 강제 등록")
                    direct_link = "WAIT_REGISTERED"
                    
                    if direct_link:
                        used_proxy_addr = proxy_addr
                        download_proxies = {
                            'http': f'http://{proxy_addr}',
                            'https': f'http://{proxy_addr}'
                        }
                        print(f"[LOG] Direct Link 파싱 성공 - 프록시: {proxy_addr}")
                        
                        # SSE로 프록시 성공 상태 전송
                        send_sse_message("proxy_success", {
                            "id": req.id,
                            "proxy": proxy_addr,
                            "step": "parsing"
                        })
                        break
                except (httpx.ConnectTimeout, httpx.ReadTimeout, 
                        httpx.TimeoutException, httpx.ProxyError) as e:
                    print(f"[LOG] Direct Link 파싱 실패 - 프록시 {proxy_addr}: {e}")
                    # SSE로 프록시 실패 상태 전송
                    send_sse_message("proxy_failed", {
                        "id": req.id,
                        "proxy": proxy_addr,
                        "step": "parsing",
                        "error": str(e)
                    })
                    continue
                except Exception as e:
                    print(f"[LOG] Direct Link 파싱 오류 - 프록시 {proxy_addr}: {e}")
                    # SSE로 프록시 실패 상태 전송
                    send_sse_message("proxy_failed", {
                        "id": req.id,
                        "proxy": proxy_addr,
                        "step": "parsing",
                        "error": str(e)
                    })
                    continue
        else:
            # 프록시 없이 시도 - 동기 파싱 완전히 제거
            print(f"[LOG] 로컬 파싱 건너뛰기 - 대기시간 강제 등록")
            direct_link = "WAIT_REGISTERED"
        
        if direct_link == "WAIT_REGISTERED":
            print(f"[LOG] 대기시간 감지됨, 백그라운드에서 대기 중: ID {req.id}")
            return True  # 성공적으로 대기 등록됨
        elif not direct_link:
            raise Exception("Cannot find download link from 1fichier. Site structure may have changed or proxy issue.")
        
        # direct_link 필드 제거됨 - 파싱된 링크는 저장하지 않음

        # 상태를 downloading으로 변경
        req.status = StatusEnum.downloading
        db.commit()
        self._notify_status_update_sync(db, req.id)
        print(f"[LOG] DB status updated to downloading for {req.id}")

        # 다운로드 함수 정의
        def simple_download(url, headers, proxies, max_retries=2):
            """단순 다운로드 함수 - ProxyError 시 즉시 실패"""
            range_removed = False
            
            for attempt in range(max_retries):
                try:
                    print(f"[LOG] 다운로드 시도 {attempt + 1}/{max_retries} (프록시: {proxies})")
                    current_headers = headers.copy()
                    
                    # httpx 사용으로 변경
                    proxy_url = proxies.get('http') if proxies else None
                    timeout = httpx.Timeout(30.0, read=300.0)

                    response = httpx.stream('GET', url, headers=current_headers, proxy=proxy_url, timeout=timeout, follow_redirects=True)
                    response = response.__enter__()

                    print(f"[LOG] 응답 상태 코드: {response.status_code}")

                    # 409 에러 처리 (Range 헤더 제거)
                    if response.status_code == 409 and "Range" in current_headers:
                        print(f"[LOG] 409 에러 - Range 헤더 제거 후 재시도")
                        response.__exit__(None, None, None)  # response 정리
                        current_headers.pop("Range", None)
                        range_removed = True
                        continue

                    response.raise_for_status()

                    return response, range_removed
                    
                except httpx.HTTPStatusError as e:
                    if e.response and e.response.status_code in [403, 404, 410]:
                        print(f"[LOG] HTTP {e.response.status_code} - 링크 만료")
                        raise e
                    if attempt < max_retries - 1:
                        print(f"[LOG] HTTP 에러 재시도...")
                        time.sleep(1)
                        continue
                    raise e
                    
                except (httpx.ConnectTimeout, httpx.ReadTimeout, 
                        httpx.TimeoutException, httpx.ProxyError) as e:
                    print(f"[LOG] 연결/프록시 에러: {e}")
                    raise e
                    
                except Exception as e:
                    if attempt < max_retries - 1:
                        print(f"[LOG] 일반 에러 재시도: {e}")
                        time.sleep(1)
                        continue
                    raise e
            
            raise Exception("모든 재시도 실패")

        # 이어받기를 위한 HEAD 요청으로 서버 Range 지원 확인
        resume_supported = False
        server_file_size = None
        
        if initial_downloaded_size > 0:
            try:
                print(f"[LOG] HEAD 요청으로 서버 파일 정보 확인...")
                head_response = httpx.head(str(direct_link), follow_redirects=True, proxies=download_proxies, timeout=5)
                
                accept_ranges = head_response.headers.get('Accept-Ranges', '').lower()
                server_file_size = head_response.headers.get('Content-Length')
                
                if accept_ranges == 'bytes' and server_file_size:
                    server_file_size = int(server_file_size)
                    print(f"[LOG] 서버 파일 크기: {server_file_size}, 현재 다운로드된 크기: {initial_downloaded_size}")
                    
                    if initial_downloaded_size < server_file_size:
                        resume_supported = True
                        print(f"[LOG] 이어받기 지원됨")
                    elif initial_downloaded_size >= server_file_size:
                        print(f"[LOG] 파일이 이미 완전히 다운로드됨")
                        req.status = StatusEnum.done
                        req.downloaded_size = server_file_size
                        req.total_size = server_file_size
                        db.commit()
                        self._cleanup_incomplete_file_sync(file_path, is_complete=True)
                        self._notify_status_update_sync(db, req.id)
                        return
                else:
                    print(f"[LOG] 서버가 Range 요청을 지원하지 않음")
                    
            except Exception as e:
                print(f"[LOG] HEAD 요청 실패: {e}. 이어받기 비활성화")

        # Range 헤더 설정
        headers = {}
        if resume_supported and initial_downloaded_size > 0:
            headers["Range"] = f"bytes={initial_downloaded_size}-"
            print(f"[LOG] 이어받기 요청 헤더: {headers}")
        else:
            if initial_downloaded_size > 0:
                print(f"[LOG] 이어받기 실패. 처음부터 다시 다운로드")
                initial_downloaded_size = 0
        
        # 다운로드 헤더
        download_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site',
        }
        
        # Range 헤더 추가 (이어받기용)
        if resume_supported and initial_downloaded_size > 0:
            download_headers["Range"] = f"bytes={initial_downloaded_size}-"
            download_headers["Accept-Encoding"] = "identity"  # Range 헤더와 함께 압축 비활성화

        # 실제 다운로드 요청
        r = None
        range_was_removed = False
        
        try:
            r, range_was_removed = simple_download(str(direct_link), download_headers, download_proxies)
        except Exception as e:
            print(f"[LOG] 다운로드 실패: {e}")
            raise e
        
        # 409 에러로 인해 Range 헤더가 제거되었는지 확인
        if range_was_removed:
            print(f"[LOG] 409 에러로 인해 Range 헤더가 제거됨. 전체 다운로드로 변경")
            initial_downloaded_size = 0
            resume_supported = False
            # 기존 .part 파일이 있으면 삭제 (처음부터 다시 시작)
            if file_path.exists():
                print(f"[LOG] 기존 .part 파일 삭제: {file_path}")
                file_path.unlink()
        
        with r:
            print(f"[LOG] HTTP GET request sent for {req.id}. Status code: {r.status_code}")
            r.raise_for_status()

            # 파일명 추출
            file_name = None
            if "Content-Disposition" in r.headers:
                cd = r.headers["Content-Disposition"]
                file_name = re.findall(r"filename\*=UTF-8''(.+?)", cd)
                if not file_name:
                    file_name = re.findall(r"filename=\"(.*?)\"", cd)
                if file_name:
                    file_name = unquote(file_name[0])
            
            if not file_name:
                file_name = os.path.basename(urlparse(str(direct_link)).path)
                if not file_name:
                    file_name = f"download_{req.id}"

            if req.file_name is None:
                req.file_name = file_name
                db.commit()

            # 전체 파일 크기 계산
            total_size = 0
            if "Content-Range" in r.headers:
                content_range = r.headers["Content-Range"]
                match = re.search(r"bytes \d+-\d+/(\d+)", content_range)
                if match:
                    total_size = int(match.group(1))
            elif "Content-Length" in r.headers:
                content_length = int(r.headers["Content-Length"])
                if initial_downloaded_size > 0:
                    total_size = initial_downloaded_size + content_length
                else:
                    total_size = content_length
            
            if server_file_size and server_file_size > total_size:
                total_size = server_file_size

            downloaded_size = initial_downloaded_size
            req.total_size = total_size
            db.commit()
            db.refresh(req)
            self._notify_status_update_sync(db, req.id)

            # 파일 쓰기
            mode = "ab" if initial_downloaded_size > 0 and resume_supported else "wb"
            print(f"[LOG] Opening file in mode: {mode}")
            
            if mode == "wb" and file_path.exists():
                print(f"[LOG] 기존 파일 삭제 후 새로 시작: {file_path}")
                file_path.unlink()
                
            with open(str(file_path), mode) as f:
                chunk_count = 0
                last_status_check = time.time()
                status_check_interval = 2.0
                
                try:
                    for chunk in r.iter_bytes(chunk_size=8192):
                        chunk_count += 1
                        current_time = time.time()
                    
                    # 타임아웃 체크
                    if current_time - start_time > max_duration:
                        raise TimeoutError("Download function timed out after 5 minutes")
                    
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    req.downloaded_size = downloaded_size
                    
                    # DB 및 SSE 업데이트 최적화: 5MB마다 또는 10초마다
                    last_update_time = getattr(req, '_last_main_update_time', 0)
                    last_update_size = getattr(req, '_last_main_update_size', 0)
                    
                    update_needed = (
                        (downloaded_size - last_update_size) >= 5 * 1024 * 1024 or  # 5MB 차이
                        (current_time - last_update_time) >= 10 or  # 10초 간격
                        total_size > 0 and downloaded_size * 10 // total_size != (downloaded_size - len(chunk)) * 10 // total_size  # 10% 진행률 변경
                    )
                    
                    if update_needed:
                        db.commit()
                        req._last_main_update_time = current_time
                        req._last_main_update_size = downloaded_size
                        self._notify_status_update_sync(db, req.id)
                
                except KeyboardInterrupt:
                    print(f"[LOG] 다운로드 중 키보드 인터럽트: {req.id}")
                    raise
                except Exception as e:
                    print(f"[LOG] 다운로드 루프 중 오류: {e}")
                    raise

        # 다운로드 완료
        req.status = StatusEnum.done
        req.downloaded_size = total_size
        req.finished_at = datetime.datetime.utcnow()
        db.commit()
        self._notify_status_update_sync(db, req.id)
        
        # 다운로드 완료 시 .part 확장자 제거
        self._cleanup_incomplete_file_sync(file_path, is_complete=True)
        
        # 프록시 사용 성공 기록
        if used_proxy_addr:
            mark_proxy_used(db, used_proxy_addr, True)
            print(f"[LOG] 프록시 {used_proxy_addr} 다운로드 성공 기록됨")
            
        # 다운로드 매니저에서 완료 처리
        download_manager.finish_download(req.id, success=True)

    def _notify_status_update_sync(self, db, download_id):
        """동기적 상태 업데이트 - 강화된 오류 처리"""
        try:
            req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
            if req:
                # 진행률 계산 - 오류 방지
                progress = 0.0
                try:
                    if req.total_size and req.total_size > 0 and req.downloaded_size:
                        progress = min(100.0, (req.downloaded_size / req.total_size) * 100)
                except Exception as progress_error:
                    print(f"[ERROR] 진행률 계산 실패 (ID {download_id}): {progress_error}")
                    progress = 0.0

                # SSE 전송 - 개별 오류 처리
                try:
                    send_sse_message("status_update", {
                        "id": req.id,
                        "url": req.url or "",
                        "file_name": req.file_name or "",
                        "status": req.status.value if req.status else "unknown",
                        "error": req.error or "",
                        "progress": progress,
                        "downloaded_size": req.downloaded_size or 0,
                        "total_size": req.total_size or 0,
                        "save_path": req.save_path or "",
                        "use_proxy": req.use_proxy if req.use_proxy is not None else False
                    })
                    print(f"[LOG] AsyncService SSE 전송 성공: {req.status.value} for request {req.id}")
                except Exception as sse_error:
                    print(f"[ERROR] SSE 메시지 전송 실패 (ID {download_id}): {sse_error}")
        except Exception as e:
            print(f"[ERROR] 상태 업데이트 전체 실패 (ID {download_id}): {e}")

    def _cleanup_incomplete_file_sync(self, file_path, is_complete=False):
        """동기적 파일 정리"""
        try:
            if file_path and file_path.exists():
                if not is_complete:
                    # 불완전한 다운로드 파일은 .part 확장자 추가
                    part_path = file_path.with_suffix(file_path.suffix + ".part")
                    if not part_path.exists():
                        file_path.rename(part_path)
                        print(f"[LOG] 불완전한 다운로드 파일을 .part로 이름 변경: {part_path}")
                else:
                    # 완료된 다운로드는 .part 확장자 제거
                    if str(file_path).endswith('.part'):
                        final_path = file_path.with_suffix('')
                        final_path = final_path.with_suffix(file_path.suffix[:-5])  # .part 제거
                        file_path.rename(final_path)
                        print(f"[LOG] 완료된 다운로드 파일에서 .part 제거: {final_path}")
        except Exception as e:
            print(f"[LOG] 파일 정리 실패: {e}")

    def _exit_if_parent_dead(self):
        """부모 프로세스 감시 (psutil 없이)"""
        parent_pid = os.getppid()
        while True:
            try:
                time.sleep(5)
                # psutil 대신 간단한 방법으로 체크
                try:
                    os.kill(parent_pid, 0)  # 시그널 0으로 프로세스 존재 확인
                except (OSError, ProcessLookupError):
                    print("[LOG] Parent process died, exiting...")
                    os._exit(0)
            except:
                break

    async def _update_download_status(self, request_id: int, status: StatusEnum, error: Optional[str] = None):
        """다운로드 상태 업데이트 (비동기)"""
        db = next(get_db())
        try:
            req = db.query(DownloadRequest).filter(
                DownloadRequest.id == request_id).first()
            if req:
                req.status = status
                if error:
                    req.error = error
                db.commit()

                # 진행률 계산
                progress = 0.0
                if req.total_size and req.total_size > 0 and req.downloaded_size:
                    progress = min(100.0, (req.downloaded_size / req.total_size) * 100)

                # SSE로 상태 브로드캐스트 (완전한 정보 포함)
                await sse_manager.broadcast_message("status_update", {
                    "id": req.id,
                    "url": req.url,
                    "file_name": req.file_name,
                    "status": status.value,
                    "progress": progress,
                    "downloaded_size": req.downloaded_size or 0,
                    "total_size": req.total_size or 0,
                    "save_path": req.save_path,
                    "use_proxy": req.use_proxy,
                    "error": error
                })
        finally:
            db.close()

    def _update_download_status_sync(self, request_id: int, status: StatusEnum, error: Optional[str] = None):
        """다운로드 상태 업데이트 (동기)"""
        db = next(get_db())
        try:
            req = db.query(DownloadRequest).filter(
                DownloadRequest.id == request_id).first()
            if req:
                req.status = status
                if error:
                    req.error = error
                db.commit()
                print(f"[LOG] Updated request {request_id} status to {status.value}")
                
                # SSE 메시지 전송 (통일된 방식)
                self._notify_status_update_sync(db, request_id)
        finally:
            db.close()

    async def _monitor_wait_timeouts_fixed(self):
        """대기시간 모니터링 - 비블로킹 버전"""
        from utils.wait_store import wait_store

        while True:
            try:
                await asyncio.sleep(1)

                # 논블로킹으로 대기 작업 확인
                try:
                    active_waits = wait_store.get_all_active_waits()
                except Exception:
                    continue

                for download_id, wait_info in list(active_waits.items()):
                    try:
                        remaining = wait_store.get_remaining_time(download_id)
                        if remaining is None:
                            # 대기 완료 - 재파싱 시작 (논블로킹)
                            print(f"[LOG] 대기 완료, 재파싱 시작: ID {download_id}")
                            asyncio.create_task(self._restart_parsing_after_wait_fixed(download_id))
                        else:
                            # SSE 카운트다운 전송 (논블로킹)
                            remaining_time = remaining.get("remaining_time", 0)
                            total_wait = remaining.get("total_wait_time", 0)
                            url = remaining.get("url", "")

                            wait_message = f"대기 중 ({remaining_time//60}분 {remaining_time%60}초)" if remaining_time >= 60 else f"대기 중 ({remaining_time}초)"

                            # 논블로킹 SSE 전송
                            asyncio.create_task(sse_manager.broadcast_message("wait_countdown", {
                                "id": download_id,
                                "remaining_time": remaining_time,
                                "wait_message": wait_message,
                                "total_wait_time": total_wait,
                                "url": url,
                                "status": "waiting"
                            }))
                    except Exception:
                        continue

            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)

    async def _restart_parsing_after_wait_fixed(self, download_id: int):
        """대기 완료 후 파싱 재시작 - 논블로킹"""
        try:
            # 직접 비동기 다운로드 시작 (다운로드 매니저 우회)
            asyncio.create_task(self._download_file_async(download_id, "ko", False))
            print(f"[LOG] 대기 완료 후 비동기 다운로드 시작: {download_id}")
        except Exception as e:
            print(f"[LOG] 재파싱 시작 실패: {download_id}, 오류: {e}")

    async def _monitor_download_manager_fixed(self):
        """다운로드 매니저 모니터링 - 논블로킹 버전"""
        while True:
            try:
                await asyncio.sleep(2)  # 더 긴 간격으로 체크
                # 매니저 모니터링은 일단 비활성화 (블로킹 방지)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)

    async def _monitor_wait_timeouts(self):
        """대기시간 모니터링 백그라운드 태스크 - 강화된 오류 처리"""
        from utils.wait_store import wait_store

        while True:
            try:
                # 1초마다 대기 작업 확인
                await asyncio.sleep(1)

                # 모든 대기 작업 가져오기 - 오류 처리 강화
                try:
                    active_waits = wait_store.get_all_active_waits()
                except Exception as store_error:
                    print(f"[ERROR] wait_store 접근 실패: {store_error}")
                    continue

                # 대기 작업이 있는지 확인
                for download_id, wait_info in list(active_waits.items()):
                    try:
                        # wait_info는 None이면 대기 완료된 것
                        remaining = wait_store.get_remaining_time(download_id)
                        if remaining is None:
                            # 대기 완료 - 재파싱 시작
                            print(f"[LOG] 대기 완료 감지, 재파싱 시작: ID {download_id}")
                            try:
                                await self._restart_parsing_after_wait(download_id)
                            except Exception as restart_error:
                                print(f"[ERROR] 재파싱 시작 실패 (ID {download_id}): {restart_error}")
                        else:
                            # 진행 중인 대기 - 실시간 카운트다운 전송
                            try:
                                remaining_time = remaining.get("remaining_time", 0)
                                total_wait = remaining.get("total_wait_time", 0)
                                url = remaining.get("url", "")

                                # 분/초 형식 메시지 생성
                                if remaining_time >= 60:
                                    wait_message = f"대기 중 ({remaining_time//60}분 {remaining_time%60}초)"
                                else:
                                    wait_message = f"대기 중 ({remaining_time}초)"

                                # SSE로 카운트다운 업데이트 전송 - 오류 처리 강화
                                try:
                                    await sse_manager.broadcast_message("wait_countdown", {
                                        "id": download_id,
                                        "remaining_time": remaining_time,
                                        "wait_message": wait_message,
                                        "total_wait_time": total_wait,
                                        "url": url,
                                        "status": "waiting"
                                    })
                                except Exception as sse_error:
                                    print(f"[ERROR] SSE 전송 실패 (ID {download_id}): {sse_error}")

                            except Exception as countdown_error:
                                print(f"[ERROR] 카운트다운 처리 실패 (ID {download_id}): {countdown_error}")

                    except Exception as item_error:
                        print(f"[ERROR] 대기 항목 처리 실패 (ID {download_id}): {item_error}")
                        continue

            except asyncio.CancelledError:
                print("[LOG] Wait timeout monitor cancelled")
                break
            except Exception as e:
                print(f"[ERROR] Wait timeout monitor 전체 오류: {e}")
                print(f"[LOG] 대기시간 모니터가 오류로 중단되었지만 서버는 계속 동작합니다")
                await asyncio.sleep(5)  # 오류 시 5초 대기

    async def _restart_parsing_after_wait(self, download_id: int):
        """대기 완료 후 파싱 재시작"""
        try:
            # 데이터베이스에서 다운로드 정보 조회
            db = next(get_db())
            try:
                req = db.query(DownloadRequest).filter(
                    DownloadRequest.id == download_id).first()

                if not req:
                    print(f"[LOG] 다운로드 요청을 찾을 수 없음: ID {download_id}")
                    return

                if req.status == StatusEnum.stopped:
                    print(f"[LOG] 다운로드가 정지됨, 재파싱 건너뜀: ID {download_id}")
                    return

                print(f"[LOG] 대기 완료 후 재파싱 시작: ID {download_id}")

                # 상태를 parsing으로 변경
                req.status = StatusEnum.parsing
                db.commit()

                # SSE 상태 업데이트 (전체 정보 포함)
                progress = 0.0
                if req.total_size and req.total_size > 0 and req.downloaded_size:
                    progress = min(100.0, (req.downloaded_size / req.total_size) * 100)

                await sse_manager.broadcast_message("status_update", {
                    "id": req.id,
                    "url": req.url or "",
                    "file_name": req.file_name or "",
                    "status": "parsing",
                    "error": req.error or "",
                    "progress": progress,
                    "downloaded_size": req.downloaded_size or 0,
                    "total_size": req.total_size or 0,
                    "save_path": req.save_path or "",
                    "use_proxy": req.use_proxy if req.use_proxy is not None else False
                })

                # 재파싱 및 다운로드 시작 - 다운로드 매니저를 통해 시작
                download_manager.start_download(download_id)

            finally:
                db.close()

        except Exception as e:
            print(f"[LOG] 재파싱 시작 실패: ID {download_id}, 오류: {e}")

    async def _monitor_download_manager(self):
        """다운로드 매니저 상태 모니터링"""
        while True:
            try:
                await asyncio.sleep(1)  # 1초마다 확인

                # 매니저에서 등록된 다운로드 중 아직 태스크가 없는 것들 시작
                active_downloads = download_manager.get_active_downloads()

                for download_id, info in active_downloads.items():
                    if download_id not in self.download_tasks:
                        # 아직 태스크가 생성되지 않은 다운로드
                        try:
                            task = asyncio.create_task(
                                self._download_file_async(download_id, "ko", info["use_proxy"])
                            )
                            self.download_tasks[download_id] = task
                            task.add_done_callback(lambda t: self._cleanup_task(download_id))
                            print(f"[LOG] Started download task for {download_id}")
                        except Exception as e:
                            print(f"[ERROR] Failed to start download task for {download_id}: {e}")

            except asyncio.CancelledError:
                print("[LOG] Download manager monitor cancelled")
                break
            except Exception as e:
                print(f"[ERROR] Download manager monitor error: {e}")
                await asyncio.sleep(5)

    async def _download_1fichier_with_parsing(self, request_id: int, lang: str, use_proxy: bool):
        """
        1fichier 다운로드 - 파싱과 다운로드 분리
        1. ThreadPoolExecutor에서 파싱 (cloudscraper)
        2. 메인 루프에서 다운로드 (httpx)
        """
        db = next(get_db())
        try:
            req = db.query(DownloadRequest).filter(DownloadRequest.id == request_id).first()
            if not req:
                print(f"[LOG] 다운로드 요청을 찾을 수 없음: {request_id}")
                return

            print(f"[LOG] 1fichier 다운로드 시작: {req.url}")

            # 상태를 parsing으로 변경
            req.status = StatusEnum.parsing
            db.commit()
            await self._notify_status_update_async(db, req.id)

            # 1단계: ThreadPoolExecutor에서 파싱 (블로킹 방지)
            from core.parser_service import parse_1fichier_link_only

            print(f"[LOG] cloudscraper 파싱 시작 (ThreadPoolExecutor)")
            parse_result = await asyncio.get_event_loop().run_in_executor(
                self.executor,
                parse_1fichier_link_only,
                req.url,
                req.password,
                None  # proxy_addr는 나중에 처리
            )

            print(f"[LOG] 파싱 결과: {parse_result}")

            if not parse_result["success"]:
                raise Exception(f"파싱 실패: {parse_result.get('error', '알 수 없는 오류')}")

            # 파일 정보 업데이트
            if parse_result.get("file_name"):
                req.file_name = parse_result["file_name"]
            if parse_result.get("file_size"):
                req.file_size = parse_result["file_size"]
            db.commit()

            # 2단계: 결과 처리
            if parse_result.get("wait_time", 0) > 0:
                # 대기시간이 있는 경우
                wait_seconds = parse_result["wait_time"]
                print(f"[LOG] 대기시간 등록: {wait_seconds}초")

                # wait_store에 등록
                from utils.wait_store import wait_store
                wait_store.start_wait(req.id, wait_seconds, req.url)

                req.status = StatusEnum.waiting
                db.commit()

                # 다운로드 매니저 제거됨 - 단순화됨

                # SSE로 대기시간 알림
                try:
                    await sse_manager.broadcast_message("wait_countdown", {
                        "id": req.id,
                        "remaining_time": wait_seconds,
                        "wait_message": f"대기 중 ({wait_seconds//60}분 {wait_seconds%60}초)" if wait_seconds >= 60 else f"대기 중 ({wait_seconds}초)",
                        "total_wait_time": wait_seconds,
                        "url": req.url,
                        "file_name": req.file_name or ""
                    })
                    print(f"[LOG] ✅ SSE 대기시간 메시지 전송 완료: {req.id}")
                except Exception as sse_error:
                    print(f"[ERROR] ❌ SSE 대기시간 메시지 전송 실패: {sse_error}")

                # SSE 상태 업데이트도 전송
                try:
                    await sse_manager.broadcast_message("status_update", {
                        "id": req.id,
                        "url": req.url or "",
                        "file_name": req.file_name or "",
                        "status": "waiting",
                        "error": req.error or "",
                        "progress": 0.0,
                        "downloaded_size": req.downloaded_size or 0,
                        "total_size": req.total_size or 0,
                        "save_path": req.save_path or "",
                        "use_proxy": req.use_proxy if req.use_proxy is not None else False
                    })
                    print(f"[LOG] ✅ SSE 상태 업데이트 전송 완료: waiting")
                except Exception as sse_error:
                    print(f"[ERROR] ❌ SSE 상태 업데이트 전송 실패: {sse_error}")

                return  # 대기 상태로 종료

            elif parse_result.get("direct_link"):
                # 즉시 다운로드 가능한 경우
                direct_link = parse_result["direct_link"]
                print(f"[LOG] 즉시 다운로드 시작: {direct_link}")

                # 다운로드 매니저 제거됨 - 단순화됨

                # 3단계: httpx로 비동기 다운로드
                await self._download_file_with_httpx(req, direct_link, db)
                return

            else:
                raise Exception("파싱 결과에 다운로드 링크나 대기시간이 없습니다")

        except Exception as e:
            print(f"[ERROR] 1fichier 다운로드 오류: {e}")
            await self._update_download_status(request_id, StatusEnum.failed, str(e))
        finally:
            db.close()

    async def _download_file_with_httpx(self, req, direct_link: str, db):
        """
        httpx로 완전 비동기 다운로드
        cloudscraper 없이 순수 httpx만 사용
        """
        try:
            # 파일 경로 설정
            from core.config import get_download_path
            download_path = get_download_path()

            base_filename = req.file_name if req.file_name else f"download_{req.id}"
            file_path = download_path / (base_filename + ".part")  # .part로 시작

            print(f"[LOG] httpx 다운로드 시작: {file_path}")

            # 상태를 downloading으로 변경
            req.status = StatusEnum.downloading
            db.commit()
            await self._notify_status_update_async(db, req.id)

            # httpx로 다운로드
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive'
            }

            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream('GET', direct_link, headers=headers) as response:
                    response.raise_for_status()

                    # 파일 크기 확인
                    total_size = int(response.headers.get('Content-Length', 0))
                    if total_size > 0:
                        req.total_size = total_size
                        db.commit()

                    downloaded_size = 0
                    last_update = 0

                    with open(str(file_path), 'wb') as f:
                        async for chunk in response.aiter_bytes(chunk_size=8192):
                            # DB에서 정지 상태 체크 (간단하고 정확함)
                            db.refresh(req)
                            if req.status == StatusEnum.stopped:
                                print(f"[LOG] 다운로드 정지 감지 (DB): {req.id}")
                                return

                            f.write(chunk)
                            downloaded_size += len(chunk)
                            req.downloaded_size = downloaded_size

                            # 1MB마다 상태 업데이트
                            if downloaded_size - last_update >= 1024 * 1024:
                                db.commit()
                                await self._notify_status_update_async(db, req.id)
                                last_update = downloaded_size

            # 다운로드 완료
            req.status = StatusEnum.done
            req.downloaded_size = total_size if total_size > 0 else downloaded_size
            req.finished_at = datetime.datetime.utcnow()
            db.commit()

            # .part 확장자 제거
            final_path = file_path.with_suffix('')
            if file_path.exists():
                file_path.rename(final_path)
                print(f"[LOG] 파일 완료: {final_path}")

            await self._notify_status_update_async(db, req.id)
            print(f"[LOG] httpx 다운로드 완료: {req.id}")

        except Exception as e:
            print(f"[LOG] httpx 다운로드 실패: {e}")
            req.status = StatusEnum.failed
            req.error = str(e)
            db.commit()
            await self._notify_status_update_async(db, req.id)


# 전역 다운로드 서비스 인스턴스
download_service = AsyncDownloadService()
