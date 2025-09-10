# -*- coding: utf-8 -*-
import asyncio
import os
import time
import threading
import requests
import cloudscraper
from pathlib import Path
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session

from core.models import DownloadRequest, StatusEnum
from core.config import get_download_path
from core.db import get_db
from core.i18n import get_message
from core.proxy_manager import get_unused_proxies, mark_proxy_used
from services.sse_manager import sse_manager
from services.download_manager import download_manager

class AsyncDownloadService:
    def __init__(self):
        self.download_tasks: Dict[int, asyncio.Task] = {}
        self.executor = None

    async def start(self):
        """서비스 시작"""
        # ThreadPoolExecutor는 필요시 생성
        print("[LOG] AsyncDownloadService started")

    async def stop(self):
        """서비스 정지 및 정리"""
        print(
            f"[LOG] Stopping AsyncDownloadService... ({len(self.download_tasks)} active tasks)")

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
        print("[LOG] AsyncDownloadService stopped")

    async def start_download(self, request_id: int, lang: str = "ko", use_proxy: bool = True) -> bool:
        """비동기 다운로드 시작 (똑똑한 매니저 사용)"""
        if request_id in self.download_tasks:
            print(f"[WARNING] Download {request_id} already running")
            return False

        # DB에서 다운로드 정보 조회
        db = next(get_db())
        try:
            req = db.query(DownloadRequest).filter(DownloadRequest.id == request_id).first()
            if not req:
                print(f"[ERROR] Download request {request_id} not found")
                return False

            # 다운로드 매니저로 시작 가능 여부 확인
            if not download_manager.can_start(request_id, req.url):
                print(f"[LOG] Cannot start download {request_id} - download manager blocked")
                return False

            # 다운로드 시작 등록
            download_manager.start(request_id, req.url)

            # 백그라운드 태스크로 다운로드 시작
            task = asyncio.create_task(
                self._download_file_async(request_id, lang, use_proxy)
            )
            self.download_tasks[request_id] = task

            # 태스크 완료 시 자동 정리
            task.add_done_callback(lambda t: self._cleanup_task(request_id))

            print(f"[LOG] Started async download for request {request_id}")
            return True

        finally:
            db.close()

    async def cancel_download(self, request_id: int) -> bool:
        """다운로드 취소"""
        if request_id not in self.download_tasks:
            return False

        task = self.download_tasks[request_id]
        if not task.done():
            task.cancel()

        # DB 상태 업데이트
        await self._update_download_status(request_id, StatusEnum.stopped)

        print(f"[LOG] Cancelled download for request {request_id}")
        return True

    def _cleanup_task(self, request_id: int):
        """태스크 정리"""
        if request_id in self.download_tasks:
            del self.download_tasks[request_id]

    async def _download_file_async(self, request_id: int, lang: str, use_proxy: bool):
        """비동기 다운로드 메인 함수"""
        try:
            print("=" * 80)
            print(f"[LOG] *** ASYNC DOWNLOAD START ***")
            print(
                f"[LOG] Request ID: {request_id}, Lang: {lang}, Use Proxy: {use_proxy}")
            print(f"[LOG] Started at: {time.strftime('%H:%M:%S')}")
            print("=" * 80)

            # CPU 집약적 작업은 ThreadPoolExecutor로 실행
            loop = asyncio.get_event_loop()

            # 블로킹 다운로드 작업을 별도 스레드에서 실행
            await loop.run_in_executor(
                None,  # 기본 ThreadPoolExecutor 사용
                self._download_file_blocking,
                request_id, lang, use_proxy
            )

        except asyncio.CancelledError:
            print(f"[LOG] Download {request_id} was cancelled")
            await self._update_download_status(request_id, StatusEnum.stopped)

        except Exception as e:
            print(f"[ERROR] Download {request_id} failed: {e}")
            await self._update_download_status(request_id, StatusEnum.failed, str(e))
            
            # 실패시에도 매니저에서 정리
            db = next(get_db())
            try:
                req = db.query(DownloadRequest).filter(DownloadRequest.id == request_id).first()
                if req:
                    download_manager.finish(request_id, req.url, success=False)
            finally:
                db.close()

    def _download_file_blocking(self, request_id: int, lang: str, use_proxy: bool):
        """블로킹 다운로드 로직 (기존 download_1fichier_file_NEW_VERSION 로직)"""
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
                print(
                    f"[LOG] Resuming from .part file: {initial_downloaded_size} bytes")
            elif file_path.exists():
                initial_downloaded_size = file_path.stat().st_size
                print(
                    f"[LOG] Resuming from existing file: {initial_downloaded_size} bytes")
            else:
                # 새 다운로드는 .part 파일로 시작
                file_path = part_file_path
                print(f"[LOG] Starting new download: {file_path}")
                if req.downloaded_size > 0:
                    req.downloaded_size = 0

            # 실제 다운로드 로직 (기존 코드 축약)
            self._perform_download(
                req, file_path, initial_downloaded_size, use_proxy, db)

        except Exception as e:
            print(f"[ERROR] Download error: {e}")
            # 동기적으로 상태 업데이트 (ThreadPoolExecutor에서 실행 중)
            self._update_download_status_sync(
                request_id, StatusEnum.failed, str(e))
        finally:
            db.close()

    def _perform_download(self, req, file_path, initial_downloaded_size, use_proxy, db):
        """실제 다운로드 수행"""
        import time
        import re
        from urllib.parse import urlparse, unquote
        
        print(f"[LOG] Performing download for {req.id}")
        
        # 시작 시간 기록
        start_time = time.time()
        max_duration = 300  # 5분
        
        # 상태를 proxying으로 설정
        req.status = StatusEnum.proxying
        db.commit()
        self._notify_status_update_sync(db, req.id)
        
        # 프록시 설정
        available_proxies = []
        if use_proxy:
            available_proxies = get_unused_proxies(db)
            print(f"[LOG] 사용 가능한 프록시: {len(available_proxies)}개")
        
        # 이어받기인 경우 direct_link 재파싱
        force_reparse = initial_size > 0
        if force_reparse:
            print(f"[LOG] 이어받기 감지. direct_link 재파싱 수행")
        
        # Direct Link 파싱 with 프록시 순환
        direct_link = None
        used_proxy_addr = None
        download_proxies = None
        
        # URL 유효성 검증 (파일 존재 확인)
        try:
            import requests
            print(f"[LOG] URL 유효성 검증: {req.url}")
            test_response = requests.get(req.url, timeout=10)
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
                
                try:
                    from core.parser_service import get_or_parse_direct_link
                    direct_link = get_or_parse_direct_link(req, use_proxy=True, force_reparse=force_reparse, proxy_addr=proxy_addr)
                    
                    if direct_link:
                        used_proxy_addr = proxy_addr
                        download_proxies = {
                            'http': f'http://{proxy_addr}',
                            'https': f'http://{proxy_addr}'
                        }
                        print(f"[LOG] Direct Link 파싱 성공 - 프록시: {proxy_addr}")
                        break
                except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, 
                        requests.exceptions.Timeout, requests.exceptions.ProxyError) as e:
                    print(f"[LOG] Direct Link 파싱 실패 - 프록시 {proxy_addr}: {e}")
                    continue
                except Exception as e:
                    print(f"[LOG] Direct Link 파싱 오류 - 프록시 {proxy_addr}: {e}")
                    continue
        else:
            # 프록시 없이 시도
            from core.parser_service import get_or_parse_direct_link
            direct_link = get_or_parse_direct_link(req, use_proxy=False, force_reparse=force_reparse, proxy_addr=None)
        
        if not direct_link:
            raise Exception("Cannot find download link from 1fichier. Site structure may have changed or proxy issue.")
        
        # 다운로드 링크를 데이터베이스에 저장
        req.direct_link = direct_link
        db.commit()

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
                    
                    response = requests.get(url, stream=True, allow_redirects=True, headers=current_headers, proxies=proxies, timeout=(1, 5))
                    print(f"[LOG] 응답 상태 코드: {response.status_code}")
                    
                    # 409 에러 처리 (Range 헤더 제거)
                    if response.status_code == 409 and "Range" in current_headers:
                        print(f"[LOG] 409 에러 - Range 헤더 제거 후 재시도")
                        current_headers.pop("Range", None)
                        range_removed = True
                        response = requests.get(url, stream=True, allow_redirects=True, headers=current_headers, proxies=proxies, timeout=(1, 5))
                    
                    response.raise_for_status()
                    return response, range_removed
                    
                except requests.exceptions.HTTPError as e:
                    if e.response and e.response.status_code in [403, 404, 410]:
                        print(f"[LOG] HTTP {e.response.status_code} - 링크 만료")
                        raise e
                    if attempt < max_retries - 1:
                        print(f"[LOG] HTTP 에러 재시도...")
                        time.sleep(1)
                        continue
                    raise e
                    
                except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, 
                        requests.exceptions.Timeout, requests.exceptions.ProxyError) as e:
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
        
        if initial_size > 0:
            try:
                print(f"[LOG] HEAD 요청으로 서버 파일 정보 확인...")
                head_response = requests.head(str(direct_link), allow_redirects=True, proxies=download_proxies, timeout=(2, 5))
                
                accept_ranges = head_response.headers.get('Accept-Ranges', '').lower()
                server_file_size = head_response.headers.get('Content-Length')
                
                if accept_ranges == 'bytes' and server_file_size:
                    server_file_size = int(server_file_size)
                    print(f"[LOG] 서버 파일 크기: {server_file_size}, 현재 다운로드된 크기: {initial_size}")
                    
                    if initial_size < server_file_size:
                        resume_supported = True
                        print(f"[LOG] 이어받기 지원됨")
                    elif initial_size >= server_file_size:
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
        if resume_supported and initial_size > 0:
            headers["Range"] = f"bytes={initial_size}-"
            print(f"[LOG] 이어받기 요청 헤더: {headers}")
        else:
            if initial_size > 0:
                print(f"[LOG] 이어받기 실패. 처음부터 다시 다운로드")
                initial_size = 0
        
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
        if resume_supported and initial_size > 0:
            download_headers["Range"] = f"bytes={initial_size}-"

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
            initial_size = 0
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
                if initial_size > 0:
                    total_size = initial_size + content_length
                else:
                    total_size = content_length
            
            if server_file_size and server_file_size > total_size:
                total_size = server_file_size

            downloaded_size = initial_size
            req.total_size = total_size
            db.commit()
            db.refresh(req)
            self._notify_status_update_sync(db, req.id)

            # 파일 쓰기
            mode = "ab" if initial_size > 0 and resume_supported else "wb"
            print(f"[LOG] Opening file in mode: {mode}")
            
            if mode == "wb" and file_path.exists():
                print(f"[LOG] 기존 파일 삭제 후 새로 시작: {file_path}")
                file_path.unlink()
                
            with open(str(file_path), mode) as f:
                chunk_count = 0
                last_status_check = time.time()
                status_check_interval = 2.0
                
                for chunk in r.iter_content(chunk_size=8192):
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

        # 다운로드 완료
        req.status = StatusEnum.done
        req.downloaded_size = total_size
        import datetime
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
        download_manager.finish(req.id, req.url, success=True)

    def _notify_status_update_sync(self, db, download_id):
        """동기적 상태 업데이트"""
        try:
            import asyncio
            import json
            # SSE 메시지 전송 (동기적으로 처리)
            from services.sse_manager import sse_manager
            
            req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
            if req:
                # 동기적으로 SSE 메시지 큐에 추가하는 방법
                # asyncio.create_task를 사용할 수 없으므로 간단한 방법 사용
                print(f"[LOG] Status updated to {req.status.value} for request {req.id}")
        except Exception as e:
            print(f"[LOG] SSE 상태 업데이트 실패: {e}")

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
        """부모 프로세스 감시 (기존 로직)"""
        import psutil

        parent_pid = os.getppid()
        while True:
            try:
                time.sleep(5)
                if not psutil.pid_exists(parent_pid):
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

                # SSE로 상태 브로드캐스트
                await sse_manager.broadcast_message("status_update", {
                    "id": req.id,
                    "status": status.value,
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
        finally:
            db.close()


# 전역 다운로드 서비스 인스턴스
download_service = AsyncDownloadService()
