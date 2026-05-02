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
import re
import traceback
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator
from sqlalchemy.orm import Session

from .models import DownloadRequest, StatusEnum
from .config import get_download_path
from .db import SessionLocal
from services.sse_manager import sse_manager
from services.notification_service import send_telegram_start_notification, send_telegram_notification
from utils.file_helpers import download_file_content, generate_file_path, get_final_file_path
from core.proxy_manager import proxy_manager
from urllib.parse import urlparse, unquote, urlunparse
from core.models import ProxyStatus
from core.simple_parser import (
    parse_1fichier_simple_sync,
    preparse_1fichier_standalone,
    clean_1fichier_url,
)
from core.error_messages import format_error
from core import fichier_auth
from core import cancel_signal


DEFAULT_DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def get_fichier_account_cookies() -> Dict[str, str]:
    """설정에 저장된 1fichier 자격증명으로 로그인해 세션 쿠키 dict 를 반환.

    자격증명이 없거나 로그인 실패 시 빈 dict 반환 (호출자는 게스트로 진행).
    """
    try:
        from core.config import get_config
        cfg = get_config()
        email = (cfg.get("fichier_email") or "").strip()
        password = cfg.get("fichier_password") or ""
        if not email or not password:
            return {}
        return fichier_auth.get_session_cookies(email, password)
    except fichier_auth.FichierLoginError as exc:
        print(f"[WARNING] 1fichier 로그인 실패 (게스트로 진행): {exc}")
        return {}
    except Exception as exc:
        print(f"[WARNING] 1fichier 자격증명 처리 중 예외 (게스트로 진행): {exc}")
        return {}


def build_download_headers(user_agent: Optional[str] = None, referer: Optional[str] = None) -> Dict[str, str]:
    """파싱 세션과 동일한 컨텍스트로 다운로드 요청을 보내기 위한 헤더 생성.

    1fichier 의 a-X.1fichier.com 같은 다운로드 서버는 User-Agent / Referer 가
    없으면 404 를 내려 보내는 경우가 많다. 호출부는 파싱 단계에서 사용한
    값을 그대로 전달하면 된다.
    """
    headers = {
        "User-Agent": user_agent or DEFAULT_DOWNLOAD_USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    return headers


class DownloadCore:
    """비동기 다운로드 코어"""

    def __init__(self):
        self.download_tasks: Dict[int, asyncio.Task] = {}
        # 1fichier 로컬 다운로드 동시실행 제한 (무료 제한 회피용)
        self.MAX_FICHIER_LOCAL_DOWNLOADS = 1
        self.fichier_local_semaphore = asyncio.Semaphore(self.MAX_FICHIER_LOCAL_DOWNLOADS)
        # 프록시 및 일반 다운로드 동시실행 제한
        self.MAX_GENERAL_DOWNLOADS = 5
        self.general_download_semaphore = asyncio.Semaphore(self.MAX_GENERAL_DOWNLOADS)
        # SSE 메시지 빈도 제한용
        self.last_sse_time: Dict[int, float] = {}  # 각 다운로드별 마지막 SSE 전송 시간
        self.SSE_THROTTLE_INTERVAL = 10.0  # 10초마다만 SSE 전송
        self.SSE_THROTTLE_COUNT = 50  # 50개 실패마다만 SSE 전송

    def should_send_sse(self, req_id: int, retry_count: int) -> bool:
        """SSE 전송 여부 결정 (시간 + 카운트 기반 throttling)"""
        current_time = time.time()
        last_time = self.last_sse_time.get(req_id, 0)

        # 첫 번째 시도이거나, 50개마다이거나, 10초가 지났을 때만 전송
        if (retry_count == 1 or
            retry_count % self.SSE_THROTTLE_COUNT == 0 or
            current_time - last_time >= self.SSE_THROTTLE_INTERVAL):
            self.last_sse_time[req_id] = current_time
            return True
        return False

    async def send_download_update(self, req_id: int, update_data: Dict[str, Any]):
        """통합 다운로드 상태 업데이트 SSE 전송"""
        try:
            await sse_manager.broadcast_message("status_update", {
                "id": req_id,
                **update_data
            })
        except Exception as e:
            print(f"[ERROR] SSE 업데이트 전송 실패: {e}")

    @staticmethod
    def _make_thread_safe_sse_callback(main_loop):
        """sync executor 스레드에서 호출 가능한 SSE 콜백 생성.

        ``parse_1fichier_simple_sync`` 가 별도 스레드에서 실행되므로,
        해당 스레드는 main asyncio 루프에 직접 접근할 수 없다. 이 헬퍼는
        ``run_coroutine_threadsafe`` 로 이벤트를 main 루프로 위임한다.

        과거에 두 군데 (로컬/프록시 파싱) 에 동일한 내부 함수가 복사돼
        있던 것을 단일 헬퍼로 합침.
        """
        def sse_callback(msg_type, data):
            try:
                future = asyncio.run_coroutine_threadsafe(
                    sse_manager.broadcast_message(msg_type, data),
                    main_loop,
                )
                future.result(timeout=1.0)
            except Exception as e:
                print(f"[WARNING] SSE 전송 실패: {e}")
        return sse_callback

    async def _perform_preparse(self, req: DownloadRequest, db: Session):
        """사전파싱 수행 (세마포어 밖에서 실행)"""
        # 이미 파일 정보가 있으면 사전파싱 건너뜀
        if req.file_name and req.file_size and req.total_size and req.total_size > 0:
            print(f"[LOG] 파일 정보가 이미 있음, 사전파싱 건너뜀: {req.id} - {req.file_name} ({req.file_size})")
            return

        if "1fichier.com" in req.url:

            parse_url = req.original_url if req.original_url else req.url
            # 1fichier URL 정리: 파일 페이지(1fichier.com/?id) 의 affiliate 등 제거.
            # 다운로드 서버 호스트는 보존됨.
            parse_url = clean_1fichier_url(parse_url)
            print(f"[LOG] 사전파싱 시작: {req.id}")

            try:
                loop = asyncio.get_event_loop()
                preparse_info = await loop.run_in_executor(None, preparse_1fichier_standalone, parse_url)

                if preparse_info:
                    if preparse_info.get('name') and not req.file_name:
                        req.file_name = preparse_info['name']
                        print(f"[LOG] 사전파싱 파일명: {req.file_name}")

                    if preparse_info.get('size') and not req.file_size:
                        req.file_size = preparse_info['size']
                        print(f"[LOG] 사전파싱 파일크기: {req.file_size}")

                        # file_size 문자열을 total_size 정수로 변환
                        try:
                            size_match = re.search(r'(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)', req.file_size, re.IGNORECASE)
                            if size_match:
                                size_value = float(size_match.group(1))
                                size_unit = size_match.group(2).upper()
                                multipliers = {'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
                                total_bytes = int(size_value * multipliers.get(size_unit, 1))
                                print(f"[DEBUG] 크기 변환: {req.file_size} -> {total_bytes} bytes, 현재 total_size={req.total_size}")
                                if not req.total_size or req.total_size == 0:
                                    req.total_size = total_bytes
                                    print(f"[LOG] 사전파싱에서 total_size 설정: {total_bytes} bytes")
                                else:
                                    print(f"[DEBUG] total_size가 이미 설정됨: {req.total_size}, 변환된 값: {total_bytes}")
                        except Exception as size_convert_error:
                            print(f"[WARNING] 파일 크기 변환 실패: {size_convert_error}")

                    db.commit()

                    # DB 커밋 후 상태 확인
                    print(f"[DEBUG] DB 커밋 후 상태: req.id={req.id}, file_name='{req.file_name}', file_size='{req.file_size}', total_size={req.total_size}")

                    # 즉시 SSE로 파일 정보 전송
                    sse_data = {
                        "id": req.id,
                        "filename": req.file_name,
                        "file_size": req.file_size
                    }
                    print(f"[LOG] SSE filename_update 전송 시작: {sse_data}")
                    await sse_manager.broadcast_message("filename_update", sse_data)
                    print(f"[LOG] 사전파싱 완료 - SSE 전송 완료")
            except Exception as preparse_error:
                print(f"[WARNING] 사전파싱 실패: {preparse_error}")

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
            # 정지 후 재시작 케이스 — 이전 cancel signal 이 set 채로 남아
            # 있으면 새 다운로드의 카운트다운이 즉시 깨어나는 버그가 됨.
            cancel_signal.clear(req.id)

            # 파일 정보가 이미 있으면 파싱 건너뛰고 바로 다운로드 시작
            # 단, 1fichier의 경우 대기시간 확인과 새 다운로드 링크 획득을 위해 사전파싱 필요
            is_1fichier = "1fichier.com" in req.url
            has_file_info = req.file_name and req.file_size and req.total_size and req.total_size > 0

            # 최초 추가시 (파일명 없음) → 무조건 사전파싱 필요
            # 재시작시 (파일명 있음) → 일반파일은 건너뛰기, 1fichier는 사전파싱 필요
            skip_parsing = has_file_info and not is_1fichier

            # 1fichier 로컬 다운로드이고 파일명이 있는 경우 (재시작) 세마포어 확인
            if is_1fichier and not req.use_proxy and has_file_info:
                if self.fichier_local_semaphore._value == 0:
                    # 세마포어가 없으면 pending 상태로 대기
                    req.status = StatusEnum.pending
                    await self.send_download_update(req.id, {
                        "status": "pending",
                        "progress": 0,
                        "message": "대기중..."
                    })
                    db.commit()
                    print(f"[LOG] 1fichier 로컬 세마포어 대기: {req.id}")
                    return True

            if skip_parsing:
                print(f"[LOG] 파일 정보가 이미 있음, 파싱 건너뛰고 바로 다운로드 시작: {req.id} - {req.file_name} ({req.file_size})")
                req.status = StatusEnum.downloading
                await self.send_download_update(req.id, {
                    "status": "downloading",
                    "progress": 0,
                    "message": "다운로드 시작 중..."
                })
            else:
                # 상태를 parsing으로 변경
                req.status = StatusEnum.parsing
                await self.send_download_update(req.id, {
                    "status": "parsing",
                    "progress": 0,
                    "message": "파싱 시작 중..."
                })

            # downloaded_size는 이어받기가 아닌 경우에만 초기화
            # 기존에 total_size나 downloaded_size가 있으면 보존
            if (not req.total_size or req.total_size == 0) and (not req.downloaded_size or req.downloaded_size == 0):
                req.downloaded_size = 0
                print(f"[LOG] 새 다운로드: downloaded_size를 0으로 초기화")
            else:
                print(f"[LOG] 기존 다운로드 정보 보존: total_size={req.total_size}, downloaded_size={req.downloaded_size}")
            db.commit()

            # 비동기 다운로드 태스크 생성
            task = asyncio.create_task(self._download_task(req.id, skip_parsing))
            self.download_tasks[req.id] = task

            # 태스크 완료 콜백 등록
            task.add_done_callback(lambda t, req_id=req.id: self._task_cleanup(req_id))

            return True

        except Exception as e:
            print(f"[ERROR] 다운로드 시작 실패: {e}")
            await self.send_download_update(req.id, {
                "status": "failed",
                "message": f"다운로드 시작 실패: {str(e)}"
            })
            return False

    async def _download_task(self, req_id: int, skip_parsing: bool = False):
        """실제 다운로드 수행 태스크"""
        db = SessionLocal()
        try:
            req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
            if not req:
                await self.send_download_log(req_id, "다운로드 요청을 찾을 수 없음", "error")
                return

            print(f"[DEBUG] 다운로드 태스크 시작: ID={req_id}, URL={req.url}, USE_PROXY={req.use_proxy}")

            # 다운로드 진행 - URL과 프록시 설정 기준으로 분기
            is_1fichier = "1fichier.com" in req.url

            if is_1fichier and not req.use_proxy:
                # 1fichier 로컬 다운로드 (무료 제한 회피용 - 최대 1개)
                print(f"[DEBUG] 1fichier 로컬 다운로드 시작: {req_id}")

                # 파싱 건너뛰기 조건 확인 후 사전파싱 실행
                if not skip_parsing:
                    await self._perform_preparse(req, db)
                else:
                    print(f"[LOG] 파일 정보 존재로 사전파싱 건너뜀: {req_id}")

                # 1fichier 로컬 다운로드 동시실행 제한 적용
                # 세마포어 대기 여부 확인
                if self.fichier_local_semaphore._value == 0:  # 세마포어가 이미 사용 중인 경우
                    print(f"[DEBUG] 1fichier 로컬 다운로드 제한 도달, 순서 대기 중: {req_id}")
                    await self.send_download_update(req_id, {
                        "status": "pending",
                        "message": f"다운로드 순서를 기다리는 중... (최대 {self.MAX_FICHIER_LOCAL_DOWNLOADS}개 동시 실행)"
                    })
                    # 상태 DB 업데이트
                    req.status = StatusEnum.pending
                    db.commit()

                async with self.fichier_local_semaphore:
                    print(f"[DEBUG] 1fichier 로컬 다운로드 세마포어 획득: {req_id}")

                    if skip_parsing:
                        # 파일 정보가 있어서 파싱을 건너뛰는 경우 바로 다운로드 시작
                        await self.send_download_update(req_id, {
                            "status": "downloading",
                            "message": "다운로드 시작 중..."
                        })
                        req.status = StatusEnum.downloading
                    else:
                        # 파싱이 필요한 경우
                        await self.send_download_update(req_id, {
                            "status": "parsing",
                            "message": "대기 완료, 1fichier 로컬 다운로드 시작 중..."
                        })
                        req.status = StatusEnum.parsing
                    db.commit()

                    await self._download_with_proxy_async(req, db, skip_preparse=skip_parsing)  # 파싱 건너뛰기 여부에 따라
                    print(f"[DEBUG] 1fichier 로컬 다운로드 세마포어 해제: {req_id}")
            else:
                # 일반 다운로드 (1fichier 프록시 포함, 일반 URL 포함 - 최대 5개)
                if is_1fichier:
                    download_type = "1fichier 프록시"
                else:
                    download_type = "일반"
                print(f"[DEBUG] {download_type} 다운로드 시작: {req_id}")

                # 일반 다운로드 동시실행 제한 적용
                # 세마포어 대기 여부 확인
                if self.general_download_semaphore._value == 0:  # 세마포어가 이미 사용 중인 경우
                    print(f"[DEBUG] {download_type} 다운로드 제한 도달, 순서 대기 중: {req_id}")
                    await self.send_download_update(req_id, {
                        "status": "pending",
                        "message": f"다운로드 순서를 기다리는 중... (최대 {self.MAX_GENERAL_DOWNLOADS}개 동시 실행)"
                    })
                    # 상태 DB 업데이트
                    req.status = StatusEnum.pending
                    db.commit()

                async with self.general_download_semaphore:
                    print(f"[DEBUG] {download_type} 다운로드 세마포어 획득: {req_id}")

                    if skip_parsing:
                        # 파일 정보가 있어서 파싱을 건너뛰는 경우 바로 다운로드 시작
                        await self.send_download_update(req_id, {
                            "status": "downloading",
                            "message": f"{download_type} 다운로드 시작 중..."
                        })
                        req.status = StatusEnum.downloading
                    else:
                        # 파싱이 필요한 경우
                        await self.send_download_update(req_id, {
                            "status": "parsing",
                            "message": f"대기 완료, {download_type} 다운로드 시작 중..."
                        })
                        req.status = StatusEnum.parsing
                    db.commit()

                    if is_1fichier:
                        await self._download_with_proxy_async(req, db, skip_preparse=skip_parsing)  # 1fichier 프록시 다운로드
                    else:
                        await self._download_local_async(req, db)  # 일반 URL 다운로드
                    print(f"[DEBUG] {download_type} 다운로드 세마포어 해제: {req_id}")

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
                user_message = format_error("다운로드", str(e))
                req.status = StatusEnum.failed
                req.error = user_message
                db.commit()
                await self.send_download_update(req_id, {
                    "status": "failed",
                    "message": user_message,
                    "stage": "다운로드",
                    "raw_error": str(e),
                })
        finally:
            db.close()

    async def _download_with_proxy_async(self, req: DownloadRequest, db: Session, skip_preparse: bool = False):
        """1fichier 프록시 다운로드 (원래 함수명)"""
        print(f"[DEBUG] _download_with_proxy_async 시작: {req.id}")
        await self.send_download_log(req.id, "1fichier 다운로드 시작")

        # 단계 추적용 플래그 — 다운로드 단계 진입 후 실패한 경우와
        # 파싱 단계에서 실패한 경우를 라벨링에서 구분하기 위함.
        download_started = False

        # 초기 상태 설정
        print(f"[DEBUG] 초기 상태 설정: {req.id}")
        if req.use_proxy:
            # 프록시 모드: proxying -> parsing -> waiting -> downloading
            await self.send_download_update(req.id, {
                "status": "proxying",
                "progress": 0
            })
        else:
            # 로컬 모드: parsing -> waiting -> downloading
            await self.send_download_update(req.id, {
                "status": "parsing",
                "progress": 0
            })

        # 실제 1fichier 파싱 로직 실행
        try:
            # 프록시 설정 - 실패한 프록시 제외하고 다음 프록시 선택
            proxies = None
            proxy_addr = None
            if req.use_proxy:
                try:
                    from core.proxy_manager import proxy_manager
                    # 프록시 매니저에서 프록시 가져오기
                    proxy_list = await proxy_manager.get_user_proxy_list(db)
                    if proxy_list:
                        # 사용 가능한 프록시 선택 (실패한 프록시 제외)
                        proxy_addr = await proxy_manager.get_next_available_proxy(db, req.id)
                        if proxy_addr:
                            # 다양한 프록시 타입 지원: HTTP/HTTPS 프록시 모두 시도
                            # 대부분의 프록시는 HTTP 프록시이므로 HTTPS 터널링 사용
                            proxies = {
                                "http": f"http://{proxy_addr}",
                                "https": f"http://{proxy_addr}"  # HTTP 프록시를 통한 HTTPS 터널링
                            }
                            print(f"[LOG] 프록시 사용: {proxy_addr}")
                        else:
                            print(f"[WARNING] 사용 가능한 프록시가 없음")
                    else:
                        print(f"[WARNING] 프록시 모드 설정되었지만 프록시 목록이 비어있음")
                except Exception as e:
                    print(f"[ERROR] 프록시 설정 실패: {e}")

            # 1fichier 파싱 실행 (이미 비동기 함수)
            # 1fichier인 경우에만 original_url 사용, 일반 다운로드는 현재 url 사용
            # 1fichier 로컬의 경우 재시작 시에도 대기시간 확인을 위해 파싱 필요
            is_1fichier = "1fichier.com" in (req.original_url or req.url)
            is_local_1fichier = is_1fichier and not req.use_proxy

            # 로컬 1fichier는 항상 파싱 필요, 프록시 1fichier는 파일 정보가 있으면 건너뛰기 가능
            should_skip_preparse = skip_preparse

            if should_skip_preparse and "1fichier.com" in (req.original_url or req.url):
                print(f"[LOG] 파일 정보가 이미 있음, 전체 파싱 건너뛰고 바로 다운로드: {req.id} - {req.file_name} ({req.file_size})")

                # 파싱을 건너뛰고 바로 다운로드 시작
                await self.send_download_update(req.id, {
                    "status": "downloading",
                    "progress": 0,
                    "message": "downloading_in_progress"
                })
                req.status = StatusEnum.downloading
                db.commit()

                # 기존 다운로드 URL이 있으면 사용, 없으면 원본 URL 사용
                download_url = req.original_url if req.original_url else req.url
                await self._perform_file_download_async(req, db, download_url, proxy_addr)
                return

            elif "1fichier.com" in (req.original_url or req.url) and not should_skip_preparse:
                parse_url = req.original_url if req.original_url else req.url
                print(f"[DEBUG] 1fichier 파싱 URL: {parse_url}")

                # 즉시 사전파싱으로 파일명/크기 추출
                print(f"[LOG] 사전파싱 시작: {req.id}")
                try:
                    loop = asyncio.get_event_loop()
                    preparse_info = await loop.run_in_executor(None, preparse_1fichier_standalone, parse_url)

                    if preparse_info:
                        if preparse_info.get('name') and not req.file_name:
                            req.file_name = preparse_info['name']
                            print(f"[LOG] 사전파싱 파일명: {req.file_name}")

                        if preparse_info.get('size') and not req.file_size:
                            req.file_size = preparse_info['size']
                            print(f"[LOG] 사전파싱 파일크기: {req.file_size}")

                            # file_size 문자열을 total_size 정수로 변환
                            try:
                                size_match = re.search(r'(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)', req.file_size, re.IGNORECASE)
                                if size_match:
                                    size_value = float(size_match.group(1))
                                    size_unit = size_match.group(2).upper()
                                    multipliers = {'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
                                    total_bytes = int(size_value * multipliers.get(size_unit, 1))
                                    print(f"[DEBUG] 크기 변환: {req.file_size} -> {total_bytes} bytes, 현재 total_size={req.total_size}")
                                    if not req.total_size or req.total_size == 0:
                                        req.total_size = total_bytes
                                        print(f"[LOG] 사전파싱에서 total_size 설정: {total_bytes} bytes")
                                    else:
                                        print(f"[DEBUG] total_size가 이미 설정됨: {req.total_size}, 변환된 값: {total_bytes}")
                            except Exception as size_convert_error:
                                print(f"[WARNING] 파일 크기 변환 실패: {size_convert_error}")

                        db.commit()

                        # DB 커밋 후 상태 확인
                        print(f"[DEBUG] DB 커밋 후 상태: req.id={req.id}, file_name='{req.file_name}', file_size='{req.file_size}', total_size={req.total_size}")

                        # 즉시 SSE로 파일 정보 전송
                        sse_data = {
                            "id": req.id,
                            "filename": req.file_name,
                            "file_size": req.file_size
                        }
                        print(f"[LOG] SSE filename_update 전송 시작: {sse_data}")
                        await sse_manager.broadcast_message("filename_update", sse_data)
                        print(f"[LOG] 사전파싱 완료 - SSE 전송 완료")
                except Exception as preparse_error:
                    print(f"[WARNING] 사전파싱 실패: {preparse_error}")
            else:
                parse_url = req.url
                print(f"[DEBUG] 일반 다운로드 URL: {parse_url}")

                # 일반 다운로드도 URL에서 파일명 추출 시도
                print(f"[LOG] 일반 다운로드 파일명 추출 시작: {parse_url}")
                try:
                    from urllib.parse import urlparse, unquote
                    parsed_url = urlparse(parse_url)
                    path = unquote(parsed_url.path)
                    filename = path.split('/')[-1] if '/' in path else path
                    print(f"[LOG] URL 파싱 결과 - path: {path}, filename: {filename}")

                    if filename and '.' in filename and not req.file_name:
                        req.file_name = filename
                        db.commit()
                        print(f"[LOG] 일반 다운로드 파일명 추출: {filename}")

                        # SSE로 파일 정보 전송
                        await sse_manager.broadcast_message("filename_update", {
                            "id": req.id,
                            "filename": req.file_name,
                            "file_size": req.file_size
                        })
                except Exception as url_parse_error:
                    print(f"[WARNING] URL 파일명 추출 실패: {url_parse_error}")

            # 1fichier만 파싱 로직 실행 - 사용 가능한 프록시가 있는 동안 재시도
            if "1fichier.com" in parse_url:
                parse_result = None
                retry_count = 0

                # 프록시 모드가 아니면 일반 망으로 한 번만 시도
                if not req.use_proxy:
                    print(f"[LOG] 일반 망으로 파싱 시도")

                    main_loop = asyncio.get_event_loop()
                    sse_callback = self._make_thread_safe_sse_callback(main_loop)
                    loop = main_loop

                    # 1fichier 계정 자격증명이 있으면 로그인된 세션 쿠키 확보
                    # (게스트 슬롯 부족/CGNAT/광고검증 우회용)
                    account_cookies = await loop.run_in_executor(
                        None, get_fichier_account_cookies
                    )
                    if account_cookies:
                        print(f"[LOG] 1fichier 계정 세션 사용 (cookies={len(account_cookies)})")

                    parse_result = await loop.run_in_executor(
                        None,
                        lambda: parse_1fichier_simple_sync(
                            parse_url,
                            req.password,
                            None,  # 프록시 없음
                            None,  # 프록시 주소 없음
                            req.id,
                            sse_callback,
                            account_cookies=account_cookies,
                        )
                    )
                else:
                    # 프록시 모드일 때는 프록시가 있어야만 시도
                    if not proxy_addr:
                        raise Exception("프록시 모드이지만 사용 가능한 프록시가 없음")

                    # 프록시 연결 완료, 파싱 단계로 전환
                    await self.send_download_update(req.id, {
                        "status": "parsing",
                        "progress": 0
                    })

                    # 총 프록시 개수와 실패 건수 추적
                    from core.proxy_manager import proxy_manager
                    total_proxy_list = await proxy_manager.get_user_proxy_list(db)
                    total_proxies = len(total_proxy_list) if total_proxy_list else 0
                    failed_count = 0
                    MAX_PROXY_PARSE_RETRIES = min(100, total_proxies)  # 파싱은 최대 100개까지

                    while parse_result is None and proxy_addr and retry_count < MAX_PROXY_PARSE_RETRIES:
                        # 다운로드 정지 상태 체크
                        db.refresh(req)
                        if req.status == StatusEnum.stopped:
                            print(f"[LOG] 다운로드 정지됨, 프록시 파싱 중단: {req.id}")
                            return

                        try:
                            print(f"[LOG] 프록시 파싱 시도 {retry_count + 1}: {proxy_addr}")

                            # 프록시 시도 시작 - proxying 상태로 변경
                            await self.send_download_update(req.id, {
                                "status": "proxying",
                                "progress": 0
                            })

                            # 전체 실패 개수 조회
                            total_failed_count = await proxy_manager.get_total_failed_count(db)

                            # 기존 proxy_trying 메시지 시스템 사용
                            await sse_manager.broadcast_message("proxy_trying", {
                                "id": req.id,
                                "proxy": proxy_addr,
                                "step": "파싱",
                                "current": retry_count + 1,
                                "total": total_proxies,
                                "failed": total_failed_count
                            })

                            main_loop = asyncio.get_event_loop()
                            sse_callback = self._make_thread_safe_sse_callback(main_loop)

                            loop = main_loop
                            account_cookies_proxy = await loop.run_in_executor(
                                None, get_fichier_account_cookies
                            )
                            parse_result = await loop.run_in_executor(
                                None,
                                lambda: parse_1fichier_simple_sync(
                                    parse_url,
                                    req.password,
                                    proxies,
                                    proxy_addr,
                                    req.id,
                                    sse_callback,
                                    account_cookies=account_cookies_proxy,
                                )
                            )

                            # 성공하면 즉시 루프 종료 (다른 프록시 시도 중단)
                            if parse_result:
                                print(f"[LOG] 프록시 파싱 성공: {proxy_addr} - 다른 프록시 시도 중단")

                                # 프록시 파싱 성공 시 프록시 상태 창 업데이트 (대기중으로 변경)
                                try:
                                    from core.config import get_config
                                    from core.i18n import get_translations

                                    config = get_config()
                                    user_language = config.get("language", "ko")
                                    translations = get_translations(user_language)

                                    success_msg = translations.get("proxy_parsing_success", "파싱 성공, 대기 중")

                                    await sse_manager.broadcast_message("proxy_success", {
                                        "id": req.id,
                                        "proxy": proxy_addr,
                                        "message": success_msg
                                    })
                                except Exception as sse_error:
                                    print(f"[WARNING] 프록시 성공 SSE 전송 실패: {sse_error}")

                                break

                        except Exception as proxy_parse_error:
                            print(f"[ERROR] 프록시 파싱 실패 ({retry_count + 1}): {proxy_parse_error}")

                            if req.use_proxy and proxy_addr:
                                # 실패한 프록시 기록 및 실패 건수 증가
                                await proxy_manager.mark_proxy_failed(db, proxy_addr)
                                failed_count += 1

                                # SSE 전송 빈도 제한 (50개마다 또는 10초마다)
                                if self.should_send_sse(req.id, retry_count + 1):
                                    # 전체 실패 개수 조회
                                    total_failed_count = await proxy_manager.get_total_failed_count(db)

                                    await sse_manager.broadcast_message("proxy_trying", {
                                        "id": req.id,
                                        "proxy": proxy_addr,
                                        "step": "파싱 실패",
                                        "current": retry_count + 1,
                                        "total": total_proxies,
                                        "failed": total_failed_count
                                    })
                                    print(f"[LOG] SSE 파싱실패 전송: {retry_count + 1}/{total_proxies} (실패: {total_failed_count})")
                                else:
                                    print(f"[LOG] SSE 파싱실패 스킵: {retry_count + 1}/{total_proxies} (실패: {total_failed_count})")

                                # 다음 프록시 가져오기
                                proxy_addr = await proxy_manager.get_next_available_proxy(db, req.id)
                                if proxy_addr:
                                    proxies = {
                                        "http": f"http://{proxy_addr}",
                                        "https": f"http://{proxy_addr}"  # HTTP 프록시를 통한 HTTPS 터널링
                                    }
                                    print(f"[LOG] 다음 프록시로 재시도: {proxy_addr}")
                                    continue
                                else:
                                    print(f"[ERROR] 더 이상 사용 가능한 프록시가 없음")
                                    raise Exception("모든 프록시 시도 실패")
                            else:
                                raise proxy_parse_error

                        retry_count += 1

                        # 최대 재시도 횟수 체크
                        if retry_count >= MAX_PROXY_PARSE_RETRIES:
                            print(f"[ERROR] 최대 프록시 파싱 재시도 횟수({MAX_PROXY_PARSE_RETRIES}) 초과")
                            break

                if not parse_result:
                    # 프록시 파싱 실패 시 프록시 상태 초기화
                    if req.use_proxy:
                        try:
                            from core.config import get_config
                            from core.i18n import get_translations

                            config = get_config()
                            user_language = config.get("language", "ko")
                            translations = get_translations(user_language)

                            failed_msg = translations.get("proxy_all_failed", "모든 프록시 시도 실패")

                            await sse_manager.broadcast_message("proxy_failed", {
                                "id": req.id,
                                "message": failed_msg
                            })
                        except Exception as sse_error:
                            print(f"[WARNING] 프록시 실패 SSE 전송 실패: {sse_error}")

                        if retry_count >= MAX_PROXY_PARSE_RETRIES:
                            raise Exception(f"프록시 파싱 실패 - 최대 재시도 횟수({MAX_PROXY_PARSE_RETRIES}) 초과")
                        else:
                            raise Exception("프록시 파싱 실패 - 사용 가능한 프록시가 없음")
                    else:
                        raise Exception("파싱 실패")
            else:
                # 일반 다운로드는 파싱 없이 바로 다운로드
                parse_result = {
                    'download_link': parse_url,  # 원본 URL을 다운로드 링크로 사용
                    'file_info': None,
                    'wait_time': None
                }

            # 1fichier 파일 정보가 있으면 즉시 저장 (사전파싱)
            if parse_result and parse_result.get('file_info'):
                file_info = parse_result['file_info']
                if file_info.get('name') and not req.file_name:
                    req.file_name = file_info['name']
                    print(f"[LOG] 파일명 저장: {req.file_name}")

                if file_info.get('size') and not req.file_size:
                    req.file_size = file_info['size']
                    print(f"[LOG] 파일크기 저장: {req.file_size}")

                db.commit()

                # SSE로 파일 정보 즉시 전송
                print(f"[LOG] SSE로 파일 정보 전송 중: ID={req.id}, 파일명={req.file_name}, 크기={req.file_size}")
                await sse_manager.broadcast_message("filename_update", {
                    "id": req.id,
                    "filename": req.file_name,
                    "file_size": req.file_size
                })
                print(f"[LOG] SSE 파일 정보 전송 완료")

            if parse_result and parse_result.get('wait_time'):
                # 대기시간은 이미 simple_parser에서 처리됨
                wait_seconds = parse_result['wait_time']
                print(f"[LOG] 대기시간은 이미 파싱 중에 처리됨: {wait_seconds}초")

            # 다운로드 링크 확인
            print(f"[DEBUG] parse_result 전체: {parse_result}")
            if parse_result and parse_result.get('download_link'):
                download_url = parse_result['download_link']
                # 파싱 세션의 쿠키/헤더를 다운로드에 함께 사용 (1fichier 세션 유지용)
                # 파서 세션 쿠키 (Cloudflare 우회 토큰 등) + 1fichier 계정 쿠키 합치기.
                # aiohttp 세션이 정확히 같은 인증/세션 컨텍스트를 사용하도록 한다.
                session_cookies = dict(parse_result.get('cookies') or {})
                try:
                    fichier_cookies = await asyncio.get_event_loop().run_in_executor(
                        None, get_fichier_account_cookies
                    )
                    if fichier_cookies:
                        session_cookies.update(fichier_cookies)
                except Exception as cookie_merge_error:
                    print(f"[WARNING] 1fichier 계정 쿠키 병합 실패: {cookie_merge_error}")
                session_user_agent = parse_result.get('user_agent')
                session_referer = parse_result.get('referer') or parse_url
                print(f"[LOG] 다운로드 링크 획득: {download_url} (cookies={len(session_cookies)})")

                # 1fichier인 경우에만 원본 URL 저장 (처음 한 번만)
                if not req.original_url and "1fichier.com" in parse_url:
                    req.original_url = download_url  # 파싱된 다운로드 링크를 저장
                    db.commit()

                # URL은 변경하지 않고, 다운로드만 새로운 링크로 진행

                print(f"[DEBUG] 다운로드 상태를 downloading으로 변경: {req.id}")
            else:
                print(f"[ERROR] parse_result에서 다운로드 링크를 찾을 수 없음!")
                print(f"[ERROR] parse_result: {parse_result}")
                if parse_result:
                    print(f"[ERROR] parse_result keys: {list(parse_result.keys())}")
                raise Exception("파싱 결과에서 다운로드 링크를 찾을 수 없음")

            await self.send_download_update(req.id, {
                "status": "downloading",
                "progress": 0,
                "message": "downloading_in_progress"
            })

            # 즉시 파일 다운로드 시작
            req.status = StatusEnum.downloading
            db.commit()
            download_started = True  # 이후 실패는 다운로드 단계 실패로 라벨링

            print(f"[DEBUG] 로컬 방식으로 직접 다운로드 시작: {req.id}")

            # 파일 저장 경로 설정
            if not req.save_path:
                filename_to_use = req.file_name or f"download_{req.id}"
                from utils.file_helpers import generate_file_path
                req.save_path = generate_file_path(filename_to_use, is_temporary=True)
                db.commit()

            # 다운로드 시작 시간 설정
            if not req.started_at:
                req.started_at = datetime.datetime.now()
                db.commit()

            # 로컬 다운로드 방식으로 직접 다운로드 (파서 세션의 쿠키/헤더 전달)
            await self._download_file_directly(
                req, db, download_url,
                cookies=session_cookies,
                user_agent=session_user_agent,
                referer=session_referer,
                parse_url=parse_url,  # 다운로드 도중 404/410 시 재파싱에 사용
            )
            print(f"[DEBUG] 직접 다운로드 완료: {req.id}")
            return True

        except Exception as e:
            print(f"[ERROR] 1fichier 처리 실패: {e}")
            print(f"[ERROR] 오류 상세:\n{traceback.format_exc()}")

            # 현재 상태 확인 - 정지된 경우 상태 유지
            db.refresh(req)
            if req.status == StatusEnum.stopped:
                print(f"[LOG] 다운로드 {req.id}가 이미 정지됨, 상태 유지")
                return False

            # 단계 라벨 결정: 다운로드 단계 진입 여부에 따라 구분
            # (내부 함수가 status를 failed로 바꾼 후 re-raise 할 수 있어
            # req.status가 아닌 자체 플래그로 판단해야 함)
            stage = "다운로드" if download_started else "파싱"
            user_message = format_error(stage, str(e))

            req.status = StatusEnum.failed
            req.error = user_message
            req.finished_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "failed",
                "message": user_message,
                "stage": stage,
                "raw_error": str(e),
            })
            return False

    async def _consume_response_and_finish(
        self,
        req: DownloadRequest,
        db: Session,
        response,
        initial_size: int,
        download_mode: str,
    ):
        """200/206 응답을 받은 뒤 본문을 받아서 완료 처리까지 한다."""
        # Content-Length 갱신
        content_length = response.headers.get('Content-Length')
        if content_length and (not req.total_size or req.total_size == 0):
            req.total_size = int(content_length) + initial_size
            db.commit()
            print(f"[LOG] Content-Length로 total_size 설정: {req.total_size}")

        # 텔레그램 다운로드 시작 알림
        try:
            file_name = req.file_name or "Unknown File"
            file_size = req.file_size
            send_telegram_start_notification(file_name, download_mode, "ko", file_size)
            print(f"[LOG] 텔레그램 다운로드 시작 알림 전송: {file_name}")
        except Exception as telegram_error:
            print(f"[WARNING] 텔레그램 다운로드 시작 알림 실패: {telegram_error}")

        # 실제 파일 다운로드
        print(f"[DEBUG] 파일 다운로드 시작 - 초기크기: {initial_size}, 총크기: {req.total_size}")
        downloaded_size = await download_file_content(
            response, req.save_path, initial_size, req.total_size, req, db
        )
        print(f"[DEBUG] 파일 다운로드 완료 - 최종크기: {downloaded_size}")

        # .part → 최종 파일명 리네임
        final_path = get_final_file_path(req.save_path)
        if req.save_path != final_path:
            try:
                shutil.move(req.save_path, final_path)
                print(f"[DEBUG] 파일 리네임: {req.save_path} -> {final_path}")
                req.save_path = final_path
                db.commit()
            except Exception as rename_error:
                print(f"[WARNING] 파일 리네임 실패: {rename_error}")

        # 완료 처리
        print(f"[LOG] 다운로드 완료 처리 시작: {req.id}")
        req.status = StatusEnum.done
        req.downloaded_size = downloaded_size
        req.finished_at = datetime.datetime.now()
        db.commit()

        await self.send_download_update(req.id, {
            "status": "done",
            "progress": 100,
            "message": "다운로드 완료"
        })

        # 텔레그램 성공 알림
        try:
            processing_time = None
            if req.started_at and req.finished_at:
                time_diff = req.finished_at - req.started_at
                hours, remainder = divmod(int(time_diff.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                processing_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            send_telegram_notification(
                req.file_name, "success", language="ko",
                file_size_str=req.file_size, save_path=req.save_path,
                requested_time=processing_time, download_mode=download_mode,
            )
        except Exception as telegram_error:
            print(f"[WARNING] 텔레그램 성공 알림 실패: {telegram_error}")

        # 1fichier 연속 요청 방지를 위한 쿨다운
        if "1fichier" in req.url.lower():
            print(f"[LOG] 1fichier 다운로드 완료 - 5초 쿨다운 시작")
            await asyncio.sleep(5)
            print(f"[LOG] 1fichier 쿨다운 완료")

    async def _reparse_for_retry(
        self,
        req: DownloadRequest,
        parse_url: str,
        proxy_addr: Optional[str] = None,
        proxies: Optional[Dict[str, str]] = None,
    ):
        """다운로드 도중 404/410 등으로 링크 만료가 감지됐을 때 다시 파싱한다.

        반환값은 ``parse_1fichier_simple_sync`` 의 결과 dict 와 동일한 형식.
        실패 시 ``None``.
        """
        if not parse_url or "1fichier.com" not in parse_url:
            return None
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: parse_1fichier_simple_sync(
                    parse_url,
                    req.password,
                    proxies,
                    proxy_addr,
                    req.id,
                ),
            )
        except Exception as reparse_error:
            print(f"[ERROR] 재파싱 오류: {reparse_error}")
            return None

    async def _download_file_directly(
        self,
        req: DownloadRequest,
        db: Session,
        download_url: str,
        cookies: Optional[Dict[str, str]] = None,
        user_agent: Optional[str] = None,
        referer: Optional[str] = None,
        parse_url: Optional[str] = None,
        max_reparse: int = 1,
    ):
        """직접 다운로드 (로컬 방식과 동일).

        cookies, user_agent, referer 는 파싱 단계에서 cloudscraper 가 사용한
        세션 정보를 그대로 전달받기 위한 인자다. 1fichier 의 다운로드 서버는
        파싱 세션과 동일한 쿠키/UA 가 없으면 404 를 반환하기 때문에 반드시
        함께 전달해야 한다.

        ``parse_url`` 이 주어지면, 다운로드 도중 404/410 을 받았을 때 최대
        ``max_reparse`` 회 자동으로 재파싱하여 새로운 download_url/세션을
        받아 재시도한다. (1fichier 다운로드 링크는 발급 후 곧 만료되거나
        세션 손실로 404 가 되는 일이 잦음.)
        """
        try:
            print(f"[LOG] 직접 다운로드 시작: {download_url}")

            # 다운로드 시작 시간 설정 (중복 방지)
            if not req.started_at:
                req.started_at = datetime.datetime.now()
                db.commit()

            timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=300)

            reparse_attempted = 0
            current_url = download_url
            current_cookies = cookies or {}
            current_ua = user_agent
            current_referer = referer

            while True:
                try:
                    async with aiohttp.ClientSession(timeout=timeout, cookies=current_cookies) as session:
                        headers = build_download_headers(user_agent=current_ua, referer=current_referer)
                        initial_size = 0

                        # 기존 파일 확인 (이어받기 지원)
                        if os.path.exists(req.save_path):
                            initial_size = os.path.getsize(req.save_path)
                            headers['Range'] = f'bytes={initial_size}-'
                            print(f"[DEBUG] 이어받기: {initial_size} bytes")

                        async with session.get(current_url, headers=headers) as response:
                            if response.status not in [200, 206]:
                                raise Exception(f"HTTP {response.status}: {response.reason}")
                            # 응답 처리는 아래 with-블록 외부의 코드를 그대로 사용하기 위해
                            # 같은 들여쓰기 레벨에서 이어서 처리한다.
                            await self._consume_response_and_finish(
                                req, db, response, initial_size,
                                download_mode="proxy" if req.use_proxy else "local",
                            )
                            return  # 성공 시 즉시 종료
                except Exception as e:
                    err_text = str(e)
                    expired = ("HTTP 404" in err_text or "HTTP 410" in err_text
                               or "Not Found" in err_text or "Gone" in err_text)
                    can_reparse = (
                        parse_url
                        and expired
                        and reparse_attempted < max_reparse
                        and "1fichier.com" in parse_url
                    )
                    if not can_reparse:
                        raise

                    reparse_attempted += 1
                    print(f"[WARNING] 다운로드 링크 만료/세션손실 감지({err_text}), "
                          f"재파싱 시도 {reparse_attempted}/{max_reparse}")

                    new_result = await self._reparse_for_retry(
                        req, parse_url, proxy_addr=None, proxies=None,
                    )
                    if not new_result or not new_result.get('download_link'):
                        raise Exception("재파싱 실패: 새 다운로드 링크를 얻지 못함")

                    current_url = new_result['download_link']
                    current_cookies = new_result.get('cookies') or current_cookies
                    current_ua = new_result.get('user_agent') or current_ua
                    current_referer = new_result.get('referer') or current_referer
                    print(f"[LOG] 재파싱으로 새 다운로드 링크 획득: {current_url}")
                    # 다음 루프에서 재시도

        except Exception as e:
            print(f"[ERROR] 직접 다운로드 실패: {e}")
            user_message = format_error("다운로드", str(e))
            req.status = StatusEnum.failed
            req.error = user_message
            req.finished_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "failed",
                "message": user_message,
                "stage": "다운로드",
                "raw_error": str(e),
            })

            # 텔레그램 실패 알림
            try:
                # 처리 시간 계산 (실패 시에도)
                processing_time = None
                if req.started_at and req.finished_at:
                    time_diff = req.finished_at - req.started_at
                    hours, remainder = divmod(int(time_diff.total_seconds()), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    processing_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

                print(f"[DEBUG] 텔레그램 실패 알림 전송 시작: {req.file_name}")
                send_telegram_notification(req.file_name, "failed", error=user_message, language="ko",
                                         file_size_str=req.file_size, requested_time=processing_time)
            except Exception as telegram_error:
                print(f"[WARNING] 텔레그램 실패 알림 실패: {telegram_error}")

            raise e

    async def _download_local_async(self, req: DownloadRequest, db: Session):
        """순수 로컬 다운로드 비동기 구현 (1fichier 제외)"""
        print(f"[DEBUG] _download_local_async 시작: {req.id}")
        await self.send_download_log(req.id, "로컬 다운로드 시작")

        # 로컬 다운로드 로직
        req.status = StatusEnum.downloading
        db.commit()

        await self.send_download_update(req.id, {
            "status": "downloading",
            "progress": 0,
            "message": "로컬 다운로드 중..."
        })

        # 실제 로컬 다운로드 구현
        await self._perform_local_download_async(req, db)

    async def _perform_file_download_async(
        self,
        req: DownloadRequest,
        db: Session,
        download_url: str = None,
        success_proxy: str = None,
        cookies: Optional[Dict[str, str]] = None,
        user_agent: Optional[str] = None,
        referer: Optional[str] = None,
    ):
        """실제 파일 다운로드 수행 (파싱 세션 컨텍스트 포함)."""
        try:
            print(f"[DEBUG] 파일 다운로드 시작: {req.id}")

            # 파일 저장 경로 생성 (.part 확장자 포함)
            print(f"[LOG] 다운로드 파일명 확인: req.file_name={req.file_name}, save_path={req.save_path}")
            if not req.save_path:
                filename_to_use = req.file_name or f"download_{req.id}"
                print(f"[LOG] 파일명 결정: '{filename_to_use}'")
                req.save_path = generate_file_path(filename_to_use, is_temporary=True)
                print(f"[LOG] 생성된 저장 경로: '{req.save_path}'")
                db.commit()

            # 프록시 다운로드 재시도 로직 - 사용 가능한 프록시가 있는 동안 재시도
            timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=300)
            download_success = False
            retry_count = 0
            proxy_addr = None

            # 프록시 모드일 때 총 개수와 실패 건수 추적
            total_proxies = 0
            failed_count = 0
            if req.use_proxy:
                from core.proxy_manager import proxy_manager
                total_proxy_list = await proxy_manager.get_user_proxy_list(db)
                total_proxies = len(total_proxy_list) if total_proxy_list else 0

            # 프록시 다운로드: 프록시 수만큼, 일반 다운로드: 3회 재시도
            MAX_DOWNLOAD_RETRIES = min(20, total_proxies) if req.use_proxy else 3
            while not download_success and retry_count < MAX_DOWNLOAD_RETRIES:
                # 다운로드 정지 상태 체크
                db.refresh(req)
                if req.status == StatusEnum.stopped:
                    print(f"[LOG] 다운로드 정지됨, 다운로드 중단: {req.id}")
                    return

                if req.use_proxy:
                    # 첫 시도는 파싱에 성공한 프록시 사용
                    if retry_count == 0 and success_proxy:
                        proxy_addr = success_proxy
                        print(f"[LOG] 파싱 성공 프록시 재사용: {proxy_addr}")
                    else:
                        proxy_addr = await proxy_manager.get_next_available_proxy(db, req.id)
                        if not proxy_addr:
                            print(f"[ERROR] 더 이상 사용 가능한 프록시가 없음")
                            raise Exception("모든 프록시 시도 실패")

                try:
                    # 프록시 설정
                    connector = None
                    if req.use_proxy and proxy_addr:
                        print(f"[LOG] 다운로드 프록시 시도 {retry_count + 1}: {proxy_addr}")

                        # SSE 전송 빈도 제한 (50개마다 또는 10초마다)
                        if self.should_send_sse(req.id, retry_count + 1):
                            total_failed_count = await proxy_manager.get_total_failed_count(db)
                            await sse_manager.broadcast_message("proxy_trying", {
                                "id": req.id,
                                "proxy": proxy_addr,
                                "step": "다운로드",
                                "current": retry_count + 1,
                                "total": total_proxies,
                                "failed": total_failed_count
                            })
                            print(f"[LOG] SSE 다운로드시도 전송: {retry_count + 1}/{total_proxies} (실패: {total_failed_count})")
                        else:
                            total_failed_count = await proxy_manager.get_total_failed_count(db)
                            print(f"[LOG] SSE 다운로드시도 스킵: {retry_count + 1}/{total_proxies} (실패: {total_failed_count})")

                        connector = aiohttp.TCPConnector()

                    proxy_url = f"http://{proxy_addr}" if req.use_proxy and proxy_addr else None
                    session_cookies = cookies or {}
                    async with aiohttp.ClientSession(
                        timeout=timeout,
                        connector=connector,
                        cookies=session_cookies,
                    ) as session:
                            headers = build_download_headers(user_agent=user_agent, referer=referer)
                            initial_size = 0

                            # 기존 파일 확인 (이어받기 지원)
                            if os.path.exists(req.save_path):
                                initial_size = os.path.getsize(req.save_path)
                                headers['Range'] = f'bytes={initial_size}-'
                                print(f"[DEBUG] 이어받기: {initial_size} bytes")

                            actual_url = download_url if download_url else req.url
                            async with session.get(actual_url, headers=headers, proxy=proxy_url) as response:
                                if response.status not in [200, 206]:
                                    raise Exception(f"HTTP {response.status}: {response.reason}")

                    # Content-Length 가져오기 (사전파싱에서 얻은 total_size가 있으면 덮어쓰지 않음)
                    content_length = response.headers.get('Content-Length')
                    if content_length and (not req.total_size or req.total_size == 0):
                        req.total_size = int(content_length) + initial_size
                        db.commit()
                        print(f"[LOG] Content-Length로 total_size 설정: {req.total_size}")

                    # 텔레그램 다운로드 시작 알림 (HTTP 연결 성공 후)
                    try:
                        file_name = req.file_name or "Unknown File"
                        file_size = req.file_size
                        download_mode = "proxy" if proxy_url else "local"
                        send_telegram_start_notification(file_name, download_mode, "ko", file_size)
                        print(f"[LOG] 텔레그램 다운로드 시작 알림 전송: {file_name}")
                    except Exception as telegram_error:
                        print(f"[WARNING] 텔레그램 다운로드 시작 알림 실패: {telegram_error}")

                    # 실제 파일 다운로드
                    print(f"[DEBUG] 파일 다운로드 시작 - 초기크기: {initial_size}, 총크기: {req.total_size}")
                    downloaded_size = await download_file_content(
                        response, req.save_path, initial_size, req.total_size, req, db
                    )
                    print(f"[DEBUG] 파일 다운로드 완료 - 최종크기: {downloaded_size}")

                    # .part 파일을 최종 파일명으로 리네임
                    final_path = get_final_file_path(req.save_path)
                    if req.save_path != final_path:
                        try:
                            shutil.move(req.save_path, final_path)
                            print(f"[DEBUG] 파일 리네임: {req.save_path} -> {final_path}")
                            req.save_path = final_path
                            db.commit()  # 파일 경로 변경 즉시 커밋
                        except Exception as rename_error:
                            print(f"[WARNING] 파일 리네임 실패: {rename_error}")

                    # 완료 처리
                    print(f"[LOG] 다운로드 완료 처리 시작: {req.id}")
                    req.status = StatusEnum.done
                    req.downloaded_size = downloaded_size
                    req.finished_at = datetime.datetime.now()
                    print(f"[LOG] 상태를 done으로 변경 완료")

                    db.commit()
                    download_success = True
                    break  # 성공하면 재시도 루프 종료

                except Exception as download_error:
                    print(f"[ERROR] 다운로드 실패 ({retry_count + 1}): {download_error}")

                    # 404/410 모두 링크 만료 또는 세션 손실 신호 - 재파싱 시도
                    err_text = str(download_error)
                    expired = (
                        "404" in err_text or "410" in err_text
                        or "Gone" in err_text or "Not Found" in err_text
                    )
                    if expired:
                        print(f"[WARNING] 다운로드 링크 만료/세션 손실 감지 - 재파싱 시도")
                        try:
                            # 재파싱
                            parse_url = req.original_url if req.original_url else req.url
                            from core.simple_parser import parse_1fichier_simple_sync

                            loop = asyncio.get_event_loop()
                            new_parse_result = await loop.run_in_executor(
                                None,
                                lambda: parse_1fichier_simple_sync(
                                    parse_url,
                                    req.password,
                                    {"http": f"http://{proxy_addr}", "https": f"http://{proxy_addr}"} if proxy_addr else None,
                                    proxy_addr,
                                    req.id
                                )
                            )

                            if new_parse_result and new_parse_result.get('download_link'):
                                download_url = new_parse_result['download_link']
                                # 재파싱으로 얻은 세션 컨텍스트도 갱신
                                cookies = new_parse_result.get('cookies') or cookies
                                user_agent = new_parse_result.get('user_agent') or user_agent
                                referer = new_parse_result.get('referer') or referer
                                print(f"[LOG] 재파싱 성공, 새 다운로드 링크: {download_url}")
                                # 새 링크로 다시 시도하기 위해 continue
                                continue
                            else:
                                print(f"[ERROR] 재파싱 실패")
                        except Exception as reparse_error:
                            print(f"[ERROR] 재파싱 오류: {reparse_error}")

                    if req.use_proxy and proxy_addr:
                        # 실패한 프록시 기록 및 실패 건수 증가
                        await proxy_manager.mark_proxy_failed(db, proxy_addr)
                        failed_count += 1
                        retry_count += 1
                        print(f"[LOG] 다음 프록시로 재시도... ({retry_count}/{MAX_DOWNLOAD_RETRIES})")

                        # SSE 전송 빈도 제한 (50개마다 또는 10초마다)
                        if self.should_send_sse(req.id, retry_count):
                            total_failed_count = await proxy_manager.get_total_failed_count(db)
                            await sse_manager.broadcast_message("proxy_trying", {
                                "id": req.id,
                                "proxy": proxy_addr,
                                "step": "다운로드 실패",
                                "current": retry_count,
                                "total": total_proxies,
                                "failed": total_failed_count
                            })
                            print(f"[LOG] SSE 다운로드실패 전송: {retry_count}/{total_proxies} (실패: {total_failed_count})")
                        else:
                            total_failed_count = await proxy_manager.get_total_failed_count(db)
                            print(f"[LOG] SSE 다운로드실패 스킵: {retry_count}/{total_proxies} (실패: {total_failed_count})")

                        # 최대 재시도 횟수 체크
                        if retry_count >= MAX_DOWNLOAD_RETRIES:
                            print(f"[ERROR] 최대 다운로드 재시도 횟수({MAX_DOWNLOAD_RETRIES}) 초과")
                            break

                        continue
                    else:
                        raise download_error

            if not download_success:
                if req.use_proxy:
                    if retry_count >= MAX_DOWNLOAD_RETRIES:
                        raise Exception(f"다운로드 실패 - 최대 재시도 횟수({MAX_DOWNLOAD_RETRIES}) 초과")
                    else:
                        raise Exception("다운로드 실패 - 사용 가능한 프록시가 없음")
                else:
                    raise Exception("다운로드 실패")

            await self.send_download_update(req.id, {
                "status": "done",
                "progress": 100,
                "message": f"다운로드 완료! 저장 위치: {req.save_path}"
            })
            print(f"[LOG] SSE 완료 메시지 전송 완료")

            # 텔레그램 성공 알림
            print(f"[DEBUG] 텔레그램 성공 알림 전송 시작 (경로2): {req.file_name}")
            try:
                # 처리 시간 계산
                processing_time = None
                if req.started_at and req.finished_at:
                    time_diff = req.finished_at - req.started_at
                    hours, remainder = divmod(int(time_diff.total_seconds()), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    processing_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

                download_mode = "proxy" if req.use_proxy else "local"
                send_telegram_notification(req.file_name, "success", language="ko",
                                         file_size_str=req.file_size, save_path=req.save_path,
                                         requested_time=processing_time, download_mode=download_mode)
            except Exception as telegram_error:
                print(f"[WARNING] 텔레그램 성공 알림 실패: {telegram_error}")

            print(f"[LOG] 다운로드 완료 처리 전체 완료: {req.save_path}")

            # 1fichier 연속 요청 방지를 위한 쿨다운
            if "1fichier" in req.url.lower():
                print(f"[LOG] 1fichier 다운로드 완료 - 5초 쿨다운 시작")
                await asyncio.sleep(5)
                print(f"[LOG] 1fichier 쿨다운 완료")

        except Exception as e:
            print(f"[ERROR] 파일 다운로드 실패: {e}")
            user_message = format_error("다운로드", str(e))
            req.status = StatusEnum.failed
            req.error = user_message
            req.finished_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "failed",
                "message": user_message,
                "stage": "다운로드",
                "raw_error": str(e),
            })

            # 텔레그램 실패 알림
            try:
                # 처리 시간 계산 (실패 시에도)
                processing_time = None
                if req.started_at and req.finished_at:
                    time_diff = req.finished_at - req.started_at
                    hours, remainder = divmod(int(time_diff.total_seconds()), 3600)
                    minutes, seconds = divmod(remainder, 60)
                    processing_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

                print(f"[DEBUG] 텔레그램 실패 알림 전송 시작: {req.file_name}")
                send_telegram_notification(req.file_name, "failed", error=user_message, language="ko",
                                         file_size_str=req.file_size, requested_time=processing_time)
            except Exception as telegram_error:
                print(f"[WARNING] 텔레그램 실패 알림 실패: {telegram_error}")

        finally:
            # 강제 상태 확인 및 로그
            try:
                db.refresh(req)
                print(f"[LOG] 최종 상태 확인: ID={req.id}, 상태={req.status}, 완료시간={req.finished_at}")
            except Exception as final_error:
                print(f"[ERROR] 최종 상태 확인 실패: {final_error}")

    async def _perform_local_download_async(self, req: DownloadRequest, db: Session):
        """로컬 다운로드 수행"""
        try:
            print(f"[DEBUG] 로컬 다운로드 시작: {req.id}")

            # 파일명 추출 (아직 추출되지 않은 경우)
            if not req.file_name:
                await self._extract_filename_from_url(req, db)

            # 실제 파일 다운로드 수행
            await self._perform_file_download_async(req, db)

        except Exception as e:
            print(f"[ERROR] 로컬 다운로드 실패: {e}")
            req.status = StatusEnum.failed
            req.error = str(e)
            req.finished_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "failed",
                "message": f"로컬 다운로드 실패: {str(e)}"
            })
            raise Exception(f"로컬 다운로드 실패: {e}")

    async def stop_download_async(self, req_id: int, db: Session) -> bool:
        """비동기 다운로드 중지"""
        try:
            print(f"[DEBUG] 다운로드 중지 시작 - ID: {req_id}")

            # 0. cancel signal 즉시 set — 1fichier 카운트다운/대기 루프가
            #    DB 폴링 없이 깨어남.
            cancel_signal.signal_cancel(req_id)

            # 1. 실행 중인 태스크 즉시 취소
            task_cancelled = False
            if req_id in self.download_tasks:
                try:
                    task = self.download_tasks[req_id]
                    task.cancel()
                    print(f"[DEBUG] 태스크 취소 요청 완료: {req_id}")

                    # 짧은 타임아웃으로 빠른 취소
                    try:
                        await asyncio.wait_for(task, timeout=1.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass

                    # 태스크 즉시 제거
                    del self.download_tasks[req_id]
                    task_cancelled = True
                    print(f"[DEBUG] 태스크 정리 완료: {req_id}")
                except Exception as e:
                    print(f"[ERROR] 태스크 취소 실패: {e}")

            # 2. DB 상태 업데이트
            try:
                req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
                if req:
                    req.status = StatusEnum.stopped
                    req.progress = 0
                    req.message = "다운로드가 중지되었습니다."
                    db.commit()
                    print(f"[DEBUG] DB 상태 업데이트 완료: {req_id}")
                else:
                    print(f"[WARNING] DB에서 다운로드 요청을 찾을 수 없음: {req_id}")
            except Exception as e:
                print(f"[ERROR] DB 업데이트 실패: {e}")

            # 3. SSE 업데이트 전송
            try:
                await self.send_download_update(req_id, {
                    "status": "stopped",
                    "progress": 0,
                    "message": "다운로드가 중지되었습니다."
                })
                print(f"[DEBUG] SSE 업데이트 전송 완료: {req_id}")
            except Exception as e:
                print(f"[ERROR] SSE 전송 실패: {e}")

            print(f"[DEBUG] 다운로드 중지 완료 - ID: {req_id}")
            return True

        except Exception as e:
            print(f"[ERROR] 다운로드 중지 실패 - ID: {req_id}, 에러: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def _extract_filename_from_url(self, req: DownloadRequest, db: Session):
        """URL에서 파일명 추출"""
        try:
            print(f"[LOG] URL에서 파일명 추출 시도: {req.url}")

            from urllib.parse import urlparse, unquote

            parsed_url = urlparse(req.url)
            path = unquote(parsed_url.path)

            # Opendrive 특수 처리
            if "opendrive.com" in req.url.lower():
                # URL 패턴: https://www.opendrive.com/d/ODlfMzkzMTYwMTlf/Hollow%20Knight%20Silksong_U%201.0.28497%20%28Kor%29.nsp
                # 파일명이 URL 경로에 포함되어 있음
                path_parts = path.split('/')
                if len(path_parts) >= 3:
                    filename = unquote(path_parts[-1])  # 마지막 부분이 파일명
                    if filename and '.' in filename:
                        req.file_name = filename
                        print(f"[LOG] Opendrive 파일명 추출: {filename}")
                        db.commit()

                        # 새로운 파일명으로 저장 경로 재설정
                        req.save_path = generate_file_path(req.file_name, is_temporary=True)
                        print(f"[LOG] Opendrive 저장경로 재설정: {req.save_path}")
                        db.commit()

                        # SSE로 파일명 업데이트 전송
                        await sse_manager.broadcast_message("filename_update", {
                            "id": req.id,
                            "filename": req.file_name,
                            "file_size": req.file_size
                        })
                        return

            # 일반적인 URL에서 파일명 추출
            if path and '/' in path:
                filename = path.split('/')[-1]
                if filename and '.' in filename:
                    req.file_name = filename
                    print(f"[LOG] 일반 URL 파일명 추출: {filename}")

                    # 새로운 파일명으로 저장 경로 재설정
                    req.save_path = generate_file_path(req.file_name, is_temporary=True)
                    print(f"[LOG] 일반 URL 저장경로 재설정: {req.save_path}")
                    db.commit()

                    # SSE로 파일명 업데이트 전송
                    await sse_manager.broadcast_message("filename_update", {
                        "id": req.id,
                        "filename": req.file_name,
                        "file_size": req.file_size
                    })
                    return

            # Content-Disposition 헤더에서 파일명 추출 시도
            try:
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.head(req.url) as response:
                        if response.status == 200:
                            content_disposition = response.headers.get('Content-Disposition', '')
                            if content_disposition:
                                # Content-Disposition: attachment; filename="filename.ext"
                                filename_match = re.search(r'filename[*]?=([^;]+)', content_disposition, re.IGNORECASE)
                                if filename_match:
                                    filename = filename_match.group(1).strip().strip('"\'')
                                    if filename:
                                        req.file_name = filename
                                        print(f"[LOG] Content-Disposition에서 파일명 추출: {filename}")

                                        # 새로운 파일명으로 저장 경로 재설정
                                        req.save_path = generate_file_path(req.file_name, is_temporary=True)
                                        print(f"[LOG] Content-Disposition 저장경로 재설정: {req.save_path}")
                                        db.commit()

                                        # SSE로 파일명 업데이트 전송
                                        await sse_manager.broadcast_message("filename_update", {
                                            "id": req.id,
                                            "filename": req.file_name,
                                            "file_size": req.file_size
                                        })
                                        return
            except Exception as head_error:
                print(f"[WARNING] HEAD 요청 실패: {head_error}")

            print(f"[WARNING] URL에서 파일명 추출 실패: {req.url}")

        except Exception as e:
            print(f"[ERROR] 파일명 추출 실패: {e}")

    def _task_cleanup(self, req_id: int):
        """태스크 정리"""
        # cancel signal 도 같이 정리해서 in-memory 누수 방지.
        cancel_signal.clear(req_id)

        if req_id in self.download_tasks:
            del self.download_tasks[req_id]
            print(f"[LOG] 다운로드 태스크 정리: {req_id}")

            # 정지된 다운로드인지 확인 후 자동시작 여부 결정
            try:
                db = SessionLocal()
                req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
                if req and req.status == StatusEnum.stopped:
                    print(f"[LOG] 정지된 다운로드이므로 자동시작 건너뜀: {req_id}")
                    db.close()
                    return
                db.close()
            except Exception as e:
                print(f"[WARNING] 상태 확인 실패, 자동시작 진행: {e}")

            # 다운로드 완료 후 대기중인 다운로드 자동 시작 (약간의 지연을 두어 세마포어 해제 대기)
            asyncio.create_task(self._delayed_start_next_pending())

    async def _delayed_start_next_pending(self):
        """세마포어 해제를 위한 지연 후 대기중인 다운로드 시작"""
        try:
            # 세마포어 해제를 위해 잠시 대기 (async with 블록 종료 대기)
            await asyncio.sleep(0.5)
            print(f"[DEBUG] 세마포어 해제 대기 완료, 자동 시작 체크")

            # 현재 세마포어 상태 로깅
            print(f"[DEBUG] 현재 세마포어 상태 - 1fichier: {self.fichier_local_semaphore._value}, 일반: {self.general_download_semaphore._value}")

            await self._start_next_pending_download()
        except Exception as e:
            print(f"[ERROR] 지연된 자동 시작 실패: {e}")

    async def _start_next_pending_download(self):
        """대기중인 다운로드를 자동으로 시작 (요청시간 순서대로)"""
        try:
            db = SessionLocal()

            # 대기중인 모든 다운로드 조회 (요청시간 오름차순으로 정렬)
            pending_downloads = db.query(DownloadRequest).filter(
                DownloadRequest.status == StatusEnum.pending
            ).order_by(DownloadRequest.requested_at.asc()).all()

            if not pending_downloads:
                print("[LOG] 대기중인 다운로드 없음")
                return

            started_count = 0

            for req in pending_downloads:
                is_1fichier = "1fichier.com" in req.url

                if is_1fichier and not req.use_proxy:
                    # 1fichier 로컬 다운로드 (최대 1개)
                    if self.fichier_local_semaphore._value > 0:
                        success = await self.start_download_async(req, db)
                        if success:
                            started_count += 1
                            print(f"[LOG] 1fichier 로컬 자동 시작: {req.id}")
                            break  # 1fichier 로컬은 최대 1개이므로 시작하면 중단
                else:
                    # 일반 다운로드 (1fichier 프록시 포함, 최대 5개)
                    if self.general_download_semaphore._value > 0:
                        success = await self.start_download_async(req, db)
                        if success:
                            started_count += 1
                            print(f"[LOG] 일반/프록시 다운로드 자동 시작: {req.id}")

                            # 일반 다운로드 세마포어가 모두 사용되면 중단
                            if self.general_download_semaphore._value == 0:
                                break

            if started_count > 0:
                print(f"[LOG] 총 {started_count}개 다운로드 자동 시작됨")

        except Exception as e:
            print(f"[ERROR] 자동 다운로드 시작 실패: {e}")
        finally:
            db.close()

    async def auto_start_pending_downloads(self):
        """대기중인 다운로드들을 자동으로 시작 (공개 메서드)"""
        await self._start_next_pending_download()

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
                "progress": round((req.downloaded_size / req.total_size * 100), 1) if req.total_size and req.total_size > 0 else 0,
                "url": req.url,
                "filename": req.file_name,
                "error_message": req.error
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