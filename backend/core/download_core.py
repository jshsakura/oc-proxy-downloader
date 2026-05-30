# -*- coding: utf-8 -*-
"""
Async download core module
- Unified SSE messaging
- Async download logic
- Real-time status updates
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
from .config import get_download_path, get_config
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
    choose_1fichier_parse_url,
    is_1fichier_placeholder_name,
)
from core.hoster_parsers import (
    get_flaresolverr_context_for_url,
    is_special_hoster_url,
    parse_special_hoster_sync,
)
from core.error_messages import apply_failure_to_request, KIND_BLOCKED, KIND_RATE_LIMITED
from core.mega_hoster import (
    MegaApiError,
    download_mega_file,
    fetch_mega_file_info,
    is_mega_url,
    mega_error_message,
    parse_mega_url,
)
from core import fichier_auth
from core import cancel_signal
from core.config import get_config
from core.i18n import get_translations


DEFAULT_DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Retry caps
# - Proxy parsing: more than 100 attempts is pointless even with many user proxies
# - Proxy download: trying too many proxies for one download wastes time
# - Local download: unless the network itself is down, 3 attempts recover most cases
MAX_PROXY_PARSE_RETRIES_CAP = 100
MAX_DOWNLOAD_RETRIES_PROXY_CAP = 20
MAX_DOWNLOAD_RETRIES_LOCAL = 3

# 1fichier free-tier host backoff. When 1fichier rejects the download form or
# signals a quota block, the server IP is flagged — hammering it just cascades
# the same block to every queued download. Instead, pause ALL 1fichier-local
# downloads for an increasing cooldown (reset on the next success), so a flagged
# IP gets time to recover the way slow manual pacing used to.
FICHIER_HOST_BACKOFF_SECONDS = (120, 300, 900, 1800)  # 2m → 5m → 15m → 30m (capped)

# Per-site concurrent-download limits (host substring -> max concurrent).
# Different hosts tolerate different parallelism, so each gets its own queue
# instead of sharing one global limit. Unlisted hosts use MAX_PER_HOST_DOWNLOADS.
# (1fichier local has its own dedicated semaphore — max 1 — handled separately.)
SITE_DOWNLOAD_LIMITS = {
    "megaup.net": 2,
    "datanodes.to": 3,
    "gofile.io": 3,
    "rapidgator.net": 1,
    "send.now": 1,
}

# Smart-download concurrency defaults (overridable via config.json).
# - GLOBAL ceiling: hard cap on total simultaneous downloads (the "max download
#   count"). Held only AFTER a per-host slot is acquired, so it bounds the total
#   without ever letting one host's queue block another host.
# - PER-HOST default: hosts not in SITE_DOWNLOAD_LIMITS each get their own queue
#   of this size, instead of all sharing a single pool. This is what lets a
#   small file on host B start while big files saturate host A.
DEFAULT_MAX_CONCURRENT_DOWNLOADS = 8
DEFAULT_MAX_PER_HOST_DOWNLOADS = 3
# Sane bounds so a bad config value can't open unlimited sockets or stall everything.
CONCURRENCY_MIN = 1
CONCURRENCY_MAX = 32


def _read_concurrency_limits() -> tuple:
    """Read (global_ceiling, per_host_default) from config, clamped to sane bounds.

    External/user data, so validate at the boundary and fall back to defaults on
    anything non-numeric instead of letting a bad value break admission control.
    """
    cfg = get_config()

    def _clamp(value, fallback):
        try:
            n = int(value)
        except (TypeError, ValueError):
            return fallback
        return max(CONCURRENCY_MIN, min(CONCURRENCY_MAX, n))

    global_ceiling = _clamp(cfg.get("max_concurrent_downloads"), DEFAULT_MAX_CONCURRENT_DOWNLOADS)
    per_host_default = _clamp(cfg.get("max_per_host_downloads"), DEFAULT_MAX_PER_HOST_DOWNLOADS)
    # Per-host can never exceed the global ceiling — that would be meaningless.
    per_host_default = min(per_host_default, global_ceiling)
    return global_ceiling, per_host_default

# Wait limit for when the SSE callback pushes a message to the main loop's event queue.
# Too long blocks the sync executor thread; too short drops SSE under heavy load.
SSE_CALLBACK_TIMEOUT_SEC = 1.0

# Wait limit for a download task to respond to cancellation.
TASK_CANCEL_TIMEOUT_SEC = 1.0

# Hard cap on resolving a special-hoster page (MegaUp/DataNodes/etc.) to its
# final link. The underlying calls (cloudscraper + up to two FlareSolverr
# solves + a requests fetch) are each individually bounded, but if any of them
# stalls — e.g. FlareSolverr unreachable/co-located behind a hung socket, or a
# server that sends headers then trickles the body — the download can sit in
# the "parsing" state indefinitely and never release its per-site semaphore.
# Exceeding this cap fails the download with a clear message and frees the slot.
SPECIAL_HOSTER_PARSE_TIMEOUT_SEC = 300  # 5 minutes


def _clear_failure_metadata(req) -> None:
    """On a successful completion, wipe leftover failure flags so the row no
    longer carries a stale ``error`` / ``failure_kind`` / ``next_retry_at`` /
    ``attempt_count`` into the 완료됨 tab. Retries that succeed shouldn't keep
    dragging the old failure label, tooltip text, or cooldown countdown.
    ``hasattr`` guards keep this safe on older schema versions.
    """
    req.error = None
    if hasattr(req, "failure_kind"):
        req.failure_kind = None
    if hasattr(req, "next_retry_at"):
        req.next_retry_at = None
    if hasattr(req, "attempt_count"):
        req.attempt_count = 0


def _build_proxy_dict(proxy_addr: Optional[str]) -> Optional[Dict[str, str]]:
    """Convert ``proxy_addr`` (e.g. ``1.2.3.4:8080``) into the proxies dict that
    requests/aiohttp accept. Returns None if given None.

    HTTPS traffic is also CONNECT-tunneled through the HTTP proxy, so the https
    key keeps the ``http://`` scheme.
    """
    if not proxy_addr:
        return None
    url = f"http://{proxy_addr}"
    return {"http": url, "https": url}


def get_fichier_account_cookies() -> Dict[str, str]:
    """Log in with the 1fichier credentials saved in the config and return the session cookies dict.

    Returns an empty dict if there are no credentials or login fails (the caller proceeds as a guest).
    """
    try:
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
    """Build headers to send the download request in the same context as the parsing session.

    1fichier download servers like a-X.1fichier.com often return a 404 when the
    User-Agent / Referer are missing. The caller should pass the same values it
    used during the parsing stage.
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


def _should_replace_file_name(current_name: Optional[str], new_name: Optional[str]) -> bool:
    """Replace the name when the current one is missing, a placeholder, or a bare
    code without an extension (e.g. a DataNodes file code) and a real name exists."""
    return bool(new_name) and _name_needs_resolution(current_name)


_CD_FILENAME_STAR = re.compile(r"filename\*\s*=\s*[^']*''([^;]+)", re.IGNORECASE)
_CD_FILENAME = re.compile(r'filename\s*=\s*"?([^";\r\n]+)"?', re.IGNORECASE)


def _filename_from_disposition(disposition: Optional[str]) -> str:
    """Extract the filename from a Content-Disposition header (RFC 5987 aware)."""
    if not disposition:
        return ""
    match = _CD_FILENAME_STAR.search(disposition)
    if match:
        return unquote(match.group(1)).strip().strip('"')
    match = _CD_FILENAME.search(disposition)
    if match:
        return match.group(1).strip()
    return ""


def _name_needs_resolution(name: Optional[str]) -> bool:
    """True when the stored name is missing, a placeholder, or a bare code
    without an extension — i.e. we should prefer the server-provided filename."""
    if not name:
        return True
    if is_1fichier_placeholder_name(name):
        return True
    return "." not in name


def _size_text_to_bytes(size_text: Optional[str]) -> int:
    """Convert a displayed size like ``2.19 GB`` into bytes. Returns 0 on failure."""
    if not size_text:
        return 0
    match = re.search(r'(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)', size_text, re.IGNORECASE)
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).upper()
    multipliers = {'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
    return int(value * multipliers.get(unit, 1))


def _format_bytes(num: int) -> str:
    """Render a byte count as a display string (e.g. ``70.40 MB``).

    Used for hosts that report raw byte sizes (MEGA), so the UI's file_size
    column matches the page-string sizes other hosters provide.
    """
    size = float(max(0, num))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{int(size)} B" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


class DownloadCore:
    """Async download core"""

    def __init__(self):
        self.download_tasks: Dict[int, asyncio.Task] = {}
        # Concurrency limit for 1fichier local downloads (to work around the free-tier limit)
        self.MAX_FICHIER_LOCAL_DOWNLOADS = 1
        self.fichier_local_semaphore = asyncio.Semaphore(self.MAX_FICHIER_LOCAL_DOWNLOADS)
        # Smart-download admission control. Every non-1fichier-local download
        # acquires its per-host semaphore first (host isolation), then the global
        # ceiling (total cap). Limits come from config so the user can tune them.
        self.MAX_CONCURRENT_DOWNLOADS, self.MAX_PER_HOST_DOWNLOADS = _read_concurrency_limits()
        self.total_download_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_DOWNLOADS)
        # Per-host semaphores (lazily created in the running loop), keyed by the
        # SITE_DOWNLOAD_LIMITS host substring or, for unlisted hosts, the hostname.
        self._site_semaphores: Dict[str, asyncio.Semaphore] = {}
        # For throttling SSE message frequency
        self.last_sse_time: Dict[int, float] = {}  # Last SSE send time per download
        self.SSE_THROTTLE_INTERVAL = 10.0  # Send SSE only every 10 seconds
        self.SSE_THROTTLE_COUNT = 50  # Send SSE only every 50 failures
        # 1fichier-local host backoff state (see FICHIER_HOST_BACKOFF_SECONDS).
        # A consecutive block streak lengthens the cooldown; a success resets it.
        self._fichier_cooldown_until: Optional[datetime.datetime] = None
        self._fichier_block_streak = 0

    def refresh_concurrency_settings(self) -> None:
        """Re-read concurrency limits from config and apply them to NEW downloads.

        Called when settings are saved so changes take effect without a restart.
        In-flight downloads keep the semaphore objects they already acquired, so
        the new caps bind as those drain — total concurrency may briefly exceed a
        lowered limit, then self-corrects. Per-host semaphores are rebuilt lazily.
        """
        self.MAX_CONCURRENT_DOWNLOADS, self.MAX_PER_HOST_DOWNLOADS = _read_concurrency_limits()
        self.total_download_semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_DOWNLOADS)
        self._site_semaphores = {}
        print(
            f"[LOG] 동시 다운로드 설정 갱신 → 전체 {self.MAX_CONCURRENT_DOWNLOADS}개 / "
            f"호스트당 {self.MAX_PER_HOST_DOWNLOADS}개"
        )

    def _resolve_host_limit(self, url: Optional[str]) -> tuple:
        """Map a URL to its (host_key, per_host_max) for per-host admission.

        Listed hosts (SITE_DOWNLOAD_LIMITS) keep their tuned limit and are keyed
        by the matched substring; every other host is keyed by its hostname and
        shares the default per-host cap. The key is what gives each host its own
        semaphore, so one host's queue never blocks another's.
        """
        host = (urlparse(url or "").hostname or "").lower()
        site_key = next((k for k in SITE_DOWNLOAD_LIMITS if k in host), None)
        if site_key is not None:
            return site_key, SITE_DOWNLOAD_LIMITS[site_key]
        return (host or "_default"), self.MAX_PER_HOST_DOWNLOADS

    def should_send_sse(self, req_id: int, retry_count: int) -> bool:
        """Decide whether to send SSE (time + count based throttling)"""
        current_time = time.time()
        last_time = self.last_sse_time.get(req_id, 0)

        # Send only on the first attempt, every 50, or once 10 seconds have passed
        if (retry_count == 1 or
            retry_count % self.SSE_THROTTLE_COUNT == 0 or
            current_time - last_time >= self.SSE_THROTTLE_INTERVAL):
            self.last_sse_time[req_id] = current_time
            return True
        return False

    def _register_fichier_block(self):
        """A 1fichier-local attempt hit a host block/quota — extend the cooldown."""
        self._fichier_block_streak += 1
        idx = min(self._fichier_block_streak - 1, len(FICHIER_HOST_BACKOFF_SECONDS) - 1)
        secs = FICHIER_HOST_BACKOFF_SECONDS[idx]
        self._fichier_cooldown_until = datetime.datetime.now() + datetime.timedelta(seconds=secs)
        print(f"[LOG] 1fichier 호스트 차단 감지 → {secs}s 백오프 (연속 {self._fichier_block_streak}회)")

    def _register_fichier_success(self):
        """A 1fichier-local download succeeded — clear the host backoff."""
        if self._fichier_block_streak or self._fichier_cooldown_until:
            print(f"[LOG] 1fichier 성공 → 호스트 백오프 해제")
        self._fichier_block_streak = 0
        self._fichier_cooldown_until = None

    async def _await_fichier_cooldown(self, req: DownloadRequest, db: Session):
        """If a 1fichier-local host backoff is active, wait it out before
        attempting, so a flagged IP isn't hammered by the queue. Cancellable via
        the stopped status. Holding the (max-1) semaphore here serializes the
        backoff across all queued 1fichier-local downloads."""
        cooldown_until = self._fichier_cooldown_until
        if not cooldown_until or cooldown_until <= datetime.datetime.now():
            return
        remaining = int((cooldown_until - datetime.datetime.now()).total_seconds())
        print(f"[LOG] 1fichier 호스트 백오프 대기 {remaining}s (id={req.id})")
        req.status = StatusEnum.pending
        db.commit()
        await self.send_download_update(req.id, {
            "status": "pending",
            "message": "1fichier 차단 회피 대기 중...",
            "next_retry_at": cooldown_until.isoformat(),
        })
        while True:
            now = datetime.datetime.now()
            target = self._fichier_cooldown_until
            if not target or target <= now:
                return
            db.refresh(req)
            if req.status == StatusEnum.stopped or cancel_signal.is_cancelled(req.id):
                print(f"[LOG] 1fichier 백오프 대기 중 정지/취소: {req.id}")
                return
            await asyncio.sleep(min(2.0, (target - now).total_seconds()))

    async def send_download_update(self, req_id: int, update_data: Dict[str, Any]):
        """Send a unified download-status-update SSE"""
        try:
            await sse_manager.broadcast_message("status_update", {
                "id": req_id,
                **update_data
            })
        except Exception as e:
            print(f"[ERROR] SSE 업데이트 전송 실패: {e}")

    @staticmethod
    def _make_thread_safe_sse_callback(main_loop):
        """Create an SSE callback that can be called from the sync executor thread.

        Since ``parse_1fichier_simple_sync`` runs in a separate thread, that
        thread cannot directly access the main asyncio loop. This helper
        delegates events to the main loop via ``run_coroutine_threadsafe``.

        Consolidates into a single helper what used to be the same inner
        function duplicated in two places (local/proxy parsing).
        """
        def sse_callback(msg_type, data):
            try:
                future = asyncio.run_coroutine_threadsafe(
                    sse_manager.broadcast_message(msg_type, data),
                    main_loop,
                )
                future.result(timeout=SSE_CALLBACK_TIMEOUT_SEC)
            except Exception as e:
                print(f"[WARNING] SSE 전송 실패: {e}")
        return sse_callback

    async def _perform_preparse(self, req: DownloadRequest, db: Session):
        """Run preparsing (executed outside the semaphore)"""
        # Skip preparsing if file info is already present
        if req.file_name and req.file_size and req.total_size and req.total_size > 0:
            print(f"[LOG] 파일 정보가 이미 있음, 사전파싱 건너뜀: {req.id} - {req.file_name} ({req.file_size})")
            return

        if "1fichier.com" in req.url:

            parse_url = choose_1fichier_parse_url(req.url, req.original_url)
            if not parse_url:
                print(f"[WARNING] 사전파싱 건너뜀: 원본 1fichier 파일 페이지 URL 없음 (id={req.id})")
                return
            # Clean the 1fichier URL: strip affiliate, etc. from the file page (1fichier.com/?id).
            # The download server host is preserved.
            print(f"[LOG] 사전파싱 시작: {req.id}")

            try:
                loop = asyncio.get_event_loop()
                preparse_info = await loop.run_in_executor(None, preparse_1fichier_standalone, parse_url)

                if preparse_info:
                    if _should_replace_file_name(req.file_name, preparse_info.get('name')):
                        req.file_name = preparse_info['name']
                        print(f"[LOG] 사전파싱 파일명: {req.file_name}")

                    if preparse_info.get('size') and not req.file_size:
                        req.file_size = preparse_info['size']
                        print(f"[LOG] 사전파싱 파일크기: {req.file_size}")

                        # Convert the file_size string into a total_size integer
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

                    # Check the state after the DB commit
                    print(f"[DEBUG] DB 커밋 후 상태: req.id={req.id}, file_name='{req.file_name}', file_size='{req.file_size}', total_size={req.total_size}")

                    # Send the file info over SSE immediately
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
        """Send a download-log SSE"""
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
        """Start an async download"""
        try:
            # Guard against duplicate tasks for the same download. Retry presses,
            # auto-start-next, and restart-after-reboot can all re-enter here for an
            # id that is already running — e.g. a download parked in the pending
            # state while it waits on a per-site semaphore still holds a live task.
            # Creating a second task would orphan the first (download_tasks only
            # tracks one per id), letting both write the same .part file and even
            # resurrect a deleted row. If a live task exists, this call is a no-op.
            existing = self.download_tasks.get(req.id)
            if existing is not None and not existing.done():
                print(f"[LOG] 이미 실행 중인 다운로드 태스크 존재, 중복 시작 방지: {req.id}")
                return True

            # Stop-then-restart case — if a previous cancel signal is left set,
            # it becomes a bug where the new download's countdown wakes up immediately.
            cancel_signal.clear(req.id)

            # If file info is already present, skip parsing and start downloading right away.
            # However, for 1fichier, preparsing is needed to check the wait time and obtain a new download link.
            is_1fichier = "1fichier.com" in req.url
            is_special_hoster = is_special_hoster_url(req.url)
            is_mega = is_mega_url(req.url)
            has_file_info = req.file_name and req.file_size and req.total_size and req.total_size > 0

            # On first add (no file name) → preparsing is always required.
            # On restart (file name present) → skip only for plain direct links.
            # Hosting pages like 1fichier/MegaUp/DataNodes/MEGA need their expiring
            # final link re-fetched, so a resolve step is required even when file
            # info is present.
            skip_parsing = (
                has_file_info and not is_1fichier and not is_special_hoster and not is_mega
            )

            # For a 1fichier local download with a file name present (restart), check the semaphore
            if is_1fichier and not req.use_proxy and has_file_info:
                if self.fichier_local_semaphore._value == 0:
                    # If the semaphore is unavailable, wait in the pending state
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
                # Change the status to parsing
                req.status = StatusEnum.parsing
                await self.send_download_update(req.id, {
                    "status": "parsing",
                    "progress": 0,
                    "message": "파싱 시작 중..."
                })

            # Reset downloaded_size only when this is not a resume
            # Preserve existing total_size or downloaded_size if present
            if (not req.total_size or req.total_size == 0) and (not req.downloaded_size or req.downloaded_size == 0):
                req.downloaded_size = 0
                print(f"[LOG] 새 다운로드: downloaded_size를 0으로 초기화")
            else:
                print(f"[LOG] 기존 다운로드 정보 보존: total_size={req.total_size}, downloaded_size={req.downloaded_size}")
            db.commit()

            # Create the async download task
            task = asyncio.create_task(self._download_task(req.id, skip_parsing))
            self.download_tasks[req.id] = task

            # Register the task completion callback
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
        """Task that performs the actual download"""
        db = SessionLocal()
        try:
            req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
            if not req:
                await self.send_download_log(req_id, "다운로드 요청을 찾을 수 없음", "error")
                return

            print(f"[DEBUG] 다운로드 태스크 시작: ID={req_id}, URL={req.url}, USE_PROXY={req.use_proxy}")

            # Proceed with the download - branch based on URL and proxy settings
            is_1fichier = "1fichier.com" in req.url

            if is_1fichier and not req.use_proxy:
                # 1fichier local download (to work around the free-tier limit - max 1)
                print(f"[DEBUG] 1fichier 로컬 다운로드 시작: {req_id}")

                # Run preparsing after checking the skip-parsing condition
                if not skip_parsing:
                    await self._perform_preparse(req, db)
                else:
                    print(f"[LOG] 파일 정보 존재로 사전파싱 건너뜀: {req_id}")

                # Apply the 1fichier local download concurrency limit
                # Check whether to wait on the semaphore
                if self.fichier_local_semaphore._value == 0:  # The semaphore is already in use
                    print(f"[DEBUG] 1fichier 로컬 다운로드 제한 도달, 순서 대기 중: {req_id}")
                    await self.send_download_update(req_id, {
                        "status": "pending",
                        "message": f"다운로드 순서를 기다리는 중... (최대 {self.MAX_FICHIER_LOCAL_DOWNLOADS}개 동시 실행)"
                    })
                    # Update the status in the DB
                    req.status = StatusEnum.pending
                    db.commit()

                async with self.fichier_local_semaphore:
                    print(f"[DEBUG] 1fichier 로컬 다운로드 세마포어 획득: {req_id}")

                    # Honor an active host backoff before touching 1fichier again
                    # (avoids cascading the same form-rejection across the queue).
                    await self._await_fichier_cooldown(req, db)
                    db.refresh(req)
                    if req.status == StatusEnum.stopped:
                        print(f"[LOG] 1fichier 백오프 후 정지 상태, 시작 안 함: {req_id}")
                        return

                    if skip_parsing:
                        # File info is present, so skip parsing and start downloading immediately
                        await self.send_download_update(req_id, {
                            "status": "downloading",
                            "message": "다운로드 시작 중..."
                        })
                        req.status = StatusEnum.downloading
                    else:
                        # When parsing is required
                        await self.send_download_update(req_id, {
                            "status": "parsing",
                            "message": "대기 완료, 1fichier 로컬 다운로드 시작 중..."
                        })
                        req.status = StatusEnum.parsing
                    db.commit()

                    await self._download_with_proxy_async(req, db, skip_preparse=skip_parsing)  # Depends on whether parsing is skipped

                    # Feed the result into the host backoff: a block/quota signal
                    # extends the cooldown for the whole queue; a success resets it.
                    db.refresh(req)
                    if req.status == StatusEnum.done:
                        self._register_fichier_success()
                    elif getattr(req, "failure_kind", None) in (KIND_BLOCKED, KIND_RATE_LIMITED):
                        self._register_fichier_block()
                    print(f"[DEBUG] 1fichier 로컬 다운로드 세마포어 해제: {req_id}")
            else:
                # General download (includes 1fichier proxy and plain URLs - max 5)
                if is_1fichier:
                    download_type = "1fichier 프록시"
                else:
                    download_type = "일반"
                print(f"[DEBUG] {download_type} 다운로드 시작: {req_id}")

                # Smart admission: every host gets its OWN queue, so several big
                # files on one host never starve a small file on another host.
                host_key, per_host_max = self._resolve_host_limit(req.original_url or req.url)
                host_semaphore = self._site_semaphores.get(host_key)
                if host_semaphore is None:
                    host_semaphore = asyncio.Semaphore(per_host_max)
                    self._site_semaphores[host_key] = host_semaphore

                # If either the host queue or the global ceiling is full, mark the
                # download pending so the UI shows it is waiting its turn.
                if host_semaphore._value == 0 or self.total_download_semaphore._value == 0:
                    print(f"[DEBUG] {download_type} 다운로드 제한 도달, 순서 대기 중: {req_id}")
                    await self.send_download_update(req_id, {
                        "status": "pending",
                        "message": (
                            f"다운로드 순서를 기다리는 중... "
                            f"(호스트당 {per_host_max}개 / 전체 {self.MAX_CONCURRENT_DOWNLOADS}개 동시 실행)"
                        )
                    })
                    # Update the status in the DB
                    req.status = StatusEnum.pending
                    db.commit()

                # Acquire the host slot FIRST, then the global ceiling. A task
                # waiting on the global cap holds only its own host slot, so it can
                # never block a different host from starting.
                async with host_semaphore:
                    async with self.total_download_semaphore:
                        print(f"[DEBUG] {download_type} 다운로드 세마포어 획득: {req_id}")

                        if skip_parsing:
                            # File info is present, so skip parsing and start downloading immediately
                            await self.send_download_update(req_id, {
                                "status": "downloading",
                                "message": f"{download_type} 다운로드 시작 중..."
                            })
                            req.status = StatusEnum.downloading
                        else:
                            # When parsing is required
                            await self.send_download_update(req_id, {
                                "status": "parsing",
                                "message": f"대기 완료, {download_type} 다운로드 시작 중..."
                            })
                            req.status = StatusEnum.parsing
                        db.commit()

                        if is_1fichier:
                            await self._download_with_proxy_async(req, db, skip_preparse=skip_parsing)  # 1fichier proxy download
                        else:
                            await self._download_local_async(req, db)  # Plain URL download
                        print(f"[DEBUG] {download_type} 다운로드 세마포어 해제: {req_id}")

        except asyncio.CancelledError:
            # Download cancelled
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
                verdict = apply_failure_to_request(req, "다운로드", str(e))
                req.status = StatusEnum.failed
                db.commit()
                await self.send_download_update(req_id, {
                    "status": "failed",
                    "message": verdict.user_message,
                    "stage": "다운로드",
                    "raw_error": str(e),
                    "failure_kind": verdict.kind,
                    "next_retry_at": verdict.next_retry_at.isoformat() if verdict.next_retry_at else None,
                    "attempt_count": verdict.attempt_count,
                })
        finally:
            db.close()

    async def _download_with_proxy_async(self, req: DownloadRequest, db: Session, skip_preparse: bool = False):
        """1fichier proxy download (original function name)"""
        print(f"[DEBUG] _download_with_proxy_async 시작: {req.id}")
        await self.send_download_log(req.id, "1fichier 다운로드 시작")

        # Flag for stage tracking — used to distinguish, in labeling, a failure
        # after entering the download stage from a failure during the parsing stage.
        download_started = False

        # Set the initial status
        print(f"[DEBUG] 초기 상태 설정: {req.id}")
        if req.use_proxy:
            # Proxy mode: proxying -> parsing -> waiting -> downloading
            await self.send_download_update(req.id, {
                "status": "proxying",
                "progress": 0
            })
        else:
            # Local mode: parsing -> waiting -> downloading
            await self.send_download_update(req.id, {
                "status": "parsing",
                "progress": 0
            })

        # Run the actual 1fichier parsing logic
        try:
            # Proxy setup - exclude failed proxies and pick the next one
            proxies = None
            proxy_addr = None
            if req.use_proxy:
                try:
                    # Get proxies from the proxy manager
                    proxy_list = await proxy_manager.get_user_proxy_list(db)
                    if proxy_list:
                        # Pick an available proxy (excluding failed ones)
                        proxy_addr = await proxy_manager.get_next_available_proxy(db, req.id)
                        if proxy_addr:
                            proxies = _build_proxy_dict(proxy_addr)
                            print(f"[LOG] 프록시 사용: {proxy_addr}")
                        else:
                            print(f"[WARNING] 사용 가능한 프록시가 없음")
                    else:
                        print(f"[WARNING] 프록시 모드 설정되었지만 프록시 목록이 비어있음")
                except Exception as e:
                    print(f"[ERROR] 프록시 설정 실패: {e}")

            # Run 1fichier parsing (already an async function)
            # Use original_url only for 1fichier; plain downloads use the current url
            # For local 1fichier, parsing is needed even on restart to check the wait time
            is_1fichier = "1fichier.com" in (req.original_url or req.url)
            is_local_1fichier = is_1fichier and not req.use_proxy

            # Local 1fichier always needs parsing; proxy 1fichier can skip it when file info is present
            should_skip_preparse = skip_preparse

            if should_skip_preparse and "1fichier.com" in (req.original_url or req.url):
                print(f"[LOG] 파일 정보가 이미 있음, 전체 파싱 건너뛰고 바로 다운로드: {req.id} - {req.file_name} ({req.file_size})")

                # Skip parsing and start downloading immediately
                await self.send_download_update(req.id, {
                    "status": "downloading",
                    "progress": 0,
                    "message": "downloading_in_progress"
                })
                req.status = StatusEnum.downloading
                db.commit()

                # Use the existing download URL if present, otherwise the original URL
                download_url = req.original_url if req.original_url else req.url
                await self._perform_file_download_async(req, db, download_url, proxy_addr)
                return

            elif "1fichier.com" in (req.original_url or req.url) and not should_skip_preparse:
                parse_url = choose_1fichier_parse_url(req.url, req.original_url)
                if not parse_url:
                    raise Exception("원본 1fichier 파일 페이지 URL을 찾을 수 없음")
                print(f"[DEBUG] 1fichier 파싱 URL: {parse_url}")

                # Extract the file name/size via immediate preparsing
                print(f"[LOG] 사전파싱 시작: {req.id}")
                try:
                    loop = asyncio.get_event_loop()
                    preparse_info = await loop.run_in_executor(None, preparse_1fichier_standalone, parse_url)

                    if preparse_info:
                        if _should_replace_file_name(req.file_name, preparse_info.get('name')):
                            req.file_name = preparse_info['name']
                            print(f"[LOG] 사전파싱 파일명: {req.file_name}")

                        if preparse_info.get('size') and not req.file_size:
                            req.file_size = preparse_info['size']
                            print(f"[LOG] 사전파싱 파일크기: {req.file_size}")

                            # Convert the file_size string into a total_size integer
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

                        # Check the state after the DB commit
                        print(f"[DEBUG] DB 커밋 후 상태: req.id={req.id}, file_name='{req.file_name}', file_size='{req.file_size}', total_size={req.total_size}")

                        # Send the file info over SSE immediately
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

                # For plain downloads, also try to extract the file name from the URL
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

                        # Send the file info over SSE
                        await sse_manager.broadcast_message("filename_update", {
                            "id": req.id,
                            "filename": req.file_name,
                            "file_size": req.file_size
                        })
                except Exception as url_parse_error:
                    print(f"[WARNING] URL 파일명 추출 실패: {url_parse_error}")

            # Run the parsing logic for 1fichier only - retry while available proxies remain
            if "1fichier.com" in parse_url:
                parse_result = None
                retry_count = 0

                # If not in proxy mode, try only once over the regular network
                if not req.use_proxy:
                    print(f"[LOG] 일반 망으로 파싱 시도")

                    main_loop = asyncio.get_event_loop()
                    sse_callback = self._make_thread_safe_sse_callback(main_loop)
                    loop = main_loop

                    # If 1fichier account credentials exist, obtain logged-in session cookies
                    # (to work around insufficient guest slots / CGNAT / ad verification)
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
                            None,  # No proxy
                            None,  # No proxy address
                            req.id,
                            sse_callback,
                            account_cookies=account_cookies,
                        )
                    )
                else:
                    # In proxy mode, only attempt if a proxy is available
                    if not proxy_addr:
                        raise Exception("프록시 모드이지만 사용 가능한 프록시가 없음")

                    # Proxy connection done, transition to the parsing stage
                    await self.send_download_update(req.id, {
                        "status": "parsing",
                        "progress": 0
                    })

                    # Track the total proxy count and failure count
                    total_proxy_list = await proxy_manager.get_user_proxy_list(db)
                    total_proxies = len(total_proxy_list) if total_proxy_list else 0
                    failed_count = 0
                    MAX_PROXY_PARSE_RETRIES = min(MAX_PROXY_PARSE_RETRIES_CAP, total_proxies)

                    while parse_result is None and proxy_addr and retry_count < MAX_PROXY_PARSE_RETRIES:
                        # Check the download-stopped state
                        db.refresh(req)
                        if req.status == StatusEnum.stopped:
                            print(f"[LOG] 다운로드 정지됨, 프록시 파싱 중단: {req.id}")
                            return

                        try:
                            print(f"[LOG] 프록시 파싱 시도 {retry_count + 1}: {proxy_addr}")

                            # Starting a proxy attempt - change to the proxying state
                            await self.send_download_update(req.id, {
                                "status": "proxying",
                                "progress": 0
                            })

                            # Query the total failure count
                            total_failed_count = await proxy_manager.get_total_failed_count(db)

                            # Use the existing proxy_trying message system
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

                            # On success, exit the loop immediately (stop trying other proxies)
                            if parse_result:
                                print(f"[LOG] 프록시 파싱 성공: {proxy_addr} - 다른 프록시 시도 중단")

                                # On proxy parsing success, update the proxy status panel (change to waiting)
                                try:
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
                                # Record the failed proxy and increment the failure count
                                await proxy_manager.mark_proxy_failed(db, proxy_addr)
                                failed_count += 1

                                # Throttle SSE frequency (every 50, or every 10 seconds)
                                if self.should_send_sse(req.id, retry_count + 1):
                                    # Query the total failure count
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

                                # Get the next proxy
                                proxy_addr = await proxy_manager.get_next_available_proxy(db, req.id)
                                if proxy_addr:
                                    proxies = _build_proxy_dict(proxy_addr)
                                    print(f"[LOG] 다음 프록시로 재시도: {proxy_addr}")
                                    continue
                                else:
                                    print(f"[ERROR] 더 이상 사용 가능한 프록시가 없음")
                                    raise Exception("모든 프록시 시도 실패")
                            else:
                                raise proxy_parse_error

                        retry_count += 1

                        # Check the max retry count
                        if retry_count >= MAX_PROXY_PARSE_RETRIES:
                            print(f"[ERROR] 최대 프록시 파싱 재시도 횟수({MAX_PROXY_PARSE_RETRIES}) 초과")
                            break

                if not parse_result:
                    # On proxy parsing failure, reset the proxy status
                    if req.use_proxy:
                        try:
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
                # Plain downloads go straight to downloading without parsing
                parse_result = {
                    'download_link': parse_url,  # Use the original URL as the download link
                    'file_info': None,
                    'wait_time': None
                }

            # If 1fichier file info is present, save it immediately (preparsing)
            if parse_result and parse_result.get('file_info'):
                file_info = parse_result['file_info']
                if _should_replace_file_name(req.file_name, file_info.get('name')):
                    req.file_name = file_info['name']
                    print(f"[LOG] 파일명 저장: {req.file_name}")

                if file_info.get('size') and not req.file_size:
                    req.file_size = file_info['size']
                    print(f"[LOG] 파일크기 저장: {req.file_size}")

                db.commit()

                # Send the file info over SSE immediately
                print(f"[LOG] SSE로 파일 정보 전송 중: ID={req.id}, 파일명={req.file_name}, 크기={req.file_size}")
                await sse_manager.broadcast_message("filename_update", {
                    "id": req.id,
                    "filename": req.file_name,
                    "file_size": req.file_size
                })
                print(f"[LOG] SSE 파일 정보 전송 완료")

            if parse_result and parse_result.get('wait_time'):
                # The wait time was already handled in simple_parser
                wait_seconds = parse_result['wait_time']
                print(f"[LOG] 대기시간은 이미 파싱 중에 처리됨: {wait_seconds}초")

            # Check the download link
            print(f"[DEBUG] parse_result 전체: {parse_result}")
            if parse_result and parse_result.get('download_link'):
                download_url = parse_result['download_link']
                # Use the parsing session's cookies/headers for the download too (to keep the 1fichier session)
                # Merge the parser session cookies (Cloudflare bypass tokens, etc.) + the 1fichier account cookies.
                # This makes the aiohttp session use exactly the same auth/session context.
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

                # For 1fichier, preserve the original file page. The download server link
                # expires quickly, so saving it as original_url would cause a 404 on retry.
                if "1fichier.com" in parse_url and req.original_url != parse_url:
                    req.original_url = parse_url
                    db.commit()

                # Don't change the URL; only the download proceeds with the new link

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

            # Start the file download immediately
            req.status = StatusEnum.downloading
            db.commit()
            download_started = True  # Label subsequent failures as download-stage failures

            print(f"[DEBUG] 로컬 방식으로 직접 다운로드 시작: {req.id}")

            # Set the file save path
            if not req.save_path:
                filename_to_use = req.file_name or f"download_{req.id}"
                from utils.file_helpers import generate_file_path
                req.save_path = generate_file_path(filename_to_use, is_temporary=True)
                db.commit()

            # Set the download start time
            if not req.started_at:
                req.started_at = datetime.datetime.now()
                db.commit()

            # Download directly using the local method (passing the parser session's cookies/headers)
            await self._download_file_directly(
                req, db, download_url,
                cookies=session_cookies,
                user_agent=session_user_agent,
                referer=session_referer,
                parse_url=parse_url,  # Used for re-parsing on a 404/410 during download
            )
            print(f"[DEBUG] 직접 다운로드 완료: {req.id}")
            return True

        except Exception as e:
            print(f"[ERROR] 1fichier 처리 실패: {e}")
            print(f"[ERROR] 오류 상세:\n{traceback.format_exc()}")

            # Check the current status - keep the status if it is stopped
            db.refresh(req)
            if req.status == StatusEnum.stopped:
                print(f"[LOG] 다운로드 {req.id}가 이미 정지됨, 상태 유지")
                return False

            # Decide the stage label based on whether the download stage was entered
            # (an inner function may set status to failed and then re-raise, so we
            # must judge by our own flag rather than req.status)
            stage = "다운로드" if download_started else "파싱"
            verdict = apply_failure_to_request(req, stage, str(e))

            req.status = StatusEnum.failed
            req.finished_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "failed",
                "message": verdict.user_message,
                "stage": stage,
                "raw_error": str(e),
                "failure_kind": verdict.kind,
                "next_retry_at": verdict.next_retry_at.isoformat() if verdict.next_retry_at else None,
                "attempt_count": verdict.attempt_count,
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
        """After receiving a 200/206 response, read the body and run completion handling."""
        # Prefer the server-provided filename (Content-Disposition) when ours is
        # missing, a placeholder, or a bare file code without an extension. Only
        # when nothing has been written yet (initial_size == 0) so resume isn't broken.
        if initial_size == 0:
            disp_name = _filename_from_disposition(response.headers.get("Content-Disposition"))
            if disp_name and _name_needs_resolution(req.file_name):
                req.file_name = disp_name
                req.save_path = generate_file_path(disp_name, is_temporary=True)
                db.commit()
                print(f"[LOG] Content-Disposition 파일명 적용: {disp_name}")
                await sse_manager.broadcast_message("filename_update", {
                    "id": req.id,
                    "filename": req.file_name,
                })

        # If we still can't determine a real filename (no extension) after the
        # parser and Content-Disposition, the source gave us nothing usable — fail
        # rather than saving a file under a placeholder/code name.
        if initial_size == 0 and _name_needs_resolution(req.file_name):
            raise Exception("파일명(확장자)을 확인할 수 없어 다운로드를 중단했습니다")

        # Update Content-Length
        content_length = response.headers.get('Content-Length')
        if content_length and (not req.total_size or req.total_size == 0):
            req.total_size = int(content_length) + initial_size
            db.commit()
            print(f"[LOG] Content-Length로 total_size 설정: {req.total_size}")

        # Telegram download-start notification
        try:
            file_name = req.file_name or "Unknown File"
            file_size = req.file_size
            send_telegram_start_notification(file_name, download_mode, "ko", file_size)
            print(f"[LOG] 텔레그램 다운로드 시작 알림 전송: {file_name}")
        except Exception as telegram_error:
            print(f"[WARNING] 텔레그램 다운로드 시작 알림 실패: {telegram_error}")

        # Actual file download
        print(f"[DEBUG] 파일 다운로드 시작 - 초기크기: {initial_size}, 총크기: {req.total_size}")
        downloaded_size = await download_file_content(
            response, req.save_path, initial_size, req.total_size, req, db
        )
        print(f"[DEBUG] 파일 다운로드 완료 - 최종크기: {downloaded_size}")

        # Rename .part → final file name
        final_path = get_final_file_path(req.save_path)
        if req.save_path != final_path:
            try:
                shutil.move(req.save_path, final_path)
                print(f"[DEBUG] 파일 리네임: {req.save_path} -> {final_path}")
                req.save_path = final_path
                db.commit()
            except Exception as rename_error:
                print(f"[WARNING] 파일 리네임 실패: {rename_error}")

        # Completion handling
        print(f"[LOG] 다운로드 완료 처리 시작: {req.id}")
        req.status = StatusEnum.done
        req.downloaded_size = downloaded_size
        req.finished_at = datetime.datetime.now()
        _clear_failure_metadata(req)
        db.commit()

        await self.send_download_update(req.id, {
            "status": "done",
            "progress": 100,
            "message": "다운로드 완료"
        })

        # Telegram success notification
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

        # Cooldown to avoid back-to-back 1fichier requests
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
        """Re-parse when link expiry is detected during download (e.g. via 404/410).

        The return value has the same format as the result dict of
        ``parse_1fichier_simple_sync``. Returns ``None`` on failure.
        """
        parse_url = choose_1fichier_parse_url(parse_url)
        if not parse_url:
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
        """Direct download (same as the local method).

        cookies, user_agent, referer are arguments for passing through the
        session info that cloudscraper used during the parsing stage. The
        1fichier download server returns a 404 without the same cookies/UA as
        the parsing session, so they must be passed along.

        If ``parse_url`` is given, on receiving a 404/410 during download it
        automatically re-parses up to ``max_reparse`` times to obtain a new
        download_url/session and retry. (1fichier download links often expire
        soon after issuance or 404 due to session loss.)
        """
        try:
            print(f"[LOG] 직접 다운로드 시작: {download_url}")

            # Set the download start time (avoid duplicates)
            if not req.started_at:
                req.started_at = datetime.datetime.now()
                db.commit()

            timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=300)

            reparse_attempted = 0
            current_url = download_url
            current_cookies = cookies or {}
            current_ua = user_agent
            current_referer = referer
            reparse_url = choose_1fichier_parse_url(parse_url)
            flaresolverr_cookie_attempted = False

            while True:
                try:
                    async with aiohttp.ClientSession(timeout=timeout, cookies=current_cookies) as session:
                        headers = build_download_headers(user_agent=current_ua, referer=current_referer)
                        initial_size = 0

                        # Check for an existing file (resume support)
                        if os.path.exists(req.save_path):
                            initial_size = os.path.getsize(req.save_path)
                            headers['Range'] = f'bytes={initial_size}-'
                            print(f"[DEBUG] 이어받기: {initial_size} bytes")

                        async with session.get(current_url, headers=headers) as response:
                            if (
                                response.status == 403
                                and is_special_hoster_url(req.original_url or req.url)
                                and not flaresolverr_cookie_attempted
                            ):
                                flaresolverr_cookie_attempted = True
                                cf_context = await asyncio.get_event_loop().run_in_executor(
                                    None,
                                    lambda: get_flaresolverr_context_for_url(
                                        current_url,
                                        referer=current_referer or req.url,
                                    ),
                                )
                                cf_cookies = cf_context.get("cookies") or {}
                                if cf_cookies:
                                    current_cookies = {**current_cookies, **cf_cookies}
                                    current_ua = cf_context.get("user_agent") or current_ua
                                    print(f"[LOG] FlareSolverr 쿠키 확보, 호스팅 최종 링크 재시도: {list(cf_cookies.keys())}")
                                    continue
                            if response.status not in [200, 206]:
                                raise Exception(f"HTTP {response.status}: {response.reason}")
                            content_type = (response.headers.get("Content-Type") or "").lower()
                            if is_special_hoster_url(req.original_url or req.url) and "text/html" in content_type:
                                raise Exception(
                                    "호스팅 최종 링크가 파일 대신 HTML/보안 확인 페이지를 반환함"
                                )
                            # Continue handling the response at the same indentation level so we
                            # can reuse the code that lives outside the with-block below.
                            await self._consume_response_and_finish(
                                req, db, response, initial_size,
                                download_mode="proxy" if req.use_proxy else "local",
                            )
                            return  # Exit immediately on success
                except Exception as e:
                    err_text = str(e)
                    expired = ("HTTP 404" in err_text or "HTTP 410" in err_text
                               or "Not Found" in err_text or "Gone" in err_text)
                    can_reparse = (
                        reparse_url
                        and expired
                        and reparse_attempted < max_reparse
                    )
                    if not can_reparse:
                        raise

                    reparse_attempted += 1
                    print(f"[WARNING] 다운로드 링크 만료/세션손실 감지({err_text}), "
                          f"재파싱 시도 {reparse_attempted}/{max_reparse}")

                    new_result = await self._reparse_for_retry(
                        req, reparse_url, proxy_addr=None, proxies=None,
                    )
                    if not new_result or not new_result.get('download_link'):
                        raise Exception("재파싱 실패: 새 다운로드 링크를 얻지 못함")

                    current_url = new_result['download_link']
                    current_cookies = new_result.get('cookies') or current_cookies
                    current_ua = new_result.get('user_agent') or current_ua
                    current_referer = new_result.get('referer') or current_referer
                    print(f"[LOG] 재파싱으로 새 다운로드 링크 획득: {current_url}")
                    # Retry on the next loop iteration

        except Exception as e:
            print(f"[ERROR] 직접 다운로드 실패: {e}")
            verdict = apply_failure_to_request(req, "다운로드", str(e))
            user_message = verdict.user_message
            req.status = StatusEnum.failed
            req.finished_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "failed",
                "message": user_message,
                "stage": "다운로드",
                "raw_error": str(e),
                "failure_kind": verdict.kind,
                "next_retry_at": verdict.next_retry_at.isoformat() if verdict.next_retry_at else None,
                "attempt_count": verdict.attempt_count,
            })

            # Telegram failure notification
            try:
                # Compute the processing time (even on failure)
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
        """Pure local download async implementation (excluding 1fichier)"""
        print(f"[DEBUG] _download_local_async 시작: {req.id}")
        await self.send_download_log(req.id, "로컬 다운로드 시작")

        if is_mega_url(req.url):
            await self._download_mega_async(req, db)
            return

        if is_special_hoster_url(req.url):
            await self._download_special_hoster_async(req, db)
            return

        # Local download logic
        req.status = StatusEnum.downloading
        db.commit()

        await self.send_download_update(req.id, {
            "status": "downloading",
            "progress": 0,
            "message": "로컬 다운로드 중..."
        })

        # Actual local download implementation
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
        """Perform the actual file download (including the parsing session context)."""
        try:
            print(f"[DEBUG] 파일 다운로드 시작: {req.id}")

            # Build the file save path (including the .part extension)
            print(f"[LOG] 다운로드 파일명 확인: req.file_name={req.file_name}, save_path={req.save_path}")
            if not req.save_path:
                filename_to_use = req.file_name or f"download_{req.id}"
                print(f"[LOG] 파일명 결정: '{filename_to_use}'")
                req.save_path = generate_file_path(filename_to_use, is_temporary=True)
                print(f"[LOG] 생성된 저장 경로: '{req.save_path}'")
                db.commit()

            # Proxy download retry logic - retry while available proxies remain
            timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=300)
            download_success = False
            retry_count = 0
            proxy_addr = None

            # In proxy mode, track the total count and failure count
            total_proxies = 0
            failed_count = 0
            if req.use_proxy:
                total_proxy_list = await proxy_manager.get_user_proxy_list(db)
                total_proxies = len(total_proxy_list) if total_proxy_list else 0

            # Proxy download: as many as the proxy count; general download: 3 retries
            MAX_DOWNLOAD_RETRIES = (
                min(MAX_DOWNLOAD_RETRIES_PROXY_CAP, total_proxies)
                if req.use_proxy else MAX_DOWNLOAD_RETRIES_LOCAL
            )
            while not download_success and retry_count < MAX_DOWNLOAD_RETRIES:
                # Check the download-stopped state
                db.refresh(req)
                if req.status == StatusEnum.stopped:
                    print(f"[LOG] 다운로드 정지됨, 다운로드 중단: {req.id}")
                    return

                if req.use_proxy:
                    # On the first attempt, use the proxy that succeeded at parsing
                    if retry_count == 0 and success_proxy:
                        proxy_addr = success_proxy
                        print(f"[LOG] 파싱 성공 프록시 재사용: {proxy_addr}")
                    else:
                        proxy_addr = await proxy_manager.get_next_available_proxy(db, req.id)
                        if not proxy_addr:
                            print(f"[ERROR] 더 이상 사용 가능한 프록시가 없음")
                            raise Exception("모든 프록시 시도 실패")

                try:
                    # Proxy setup
                    connector = None
                    if req.use_proxy and proxy_addr:
                        print(f"[LOG] 다운로드 프록시 시도 {retry_count + 1}: {proxy_addr}")

                        # Throttle SSE frequency (every 50, or every 10 seconds)
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

                            # Check for an existing file (resume support)
                            if os.path.exists(req.save_path):
                                initial_size = os.path.getsize(req.save_path)
                                headers['Range'] = f'bytes={initial_size}-'
                                print(f"[DEBUG] 이어받기: {initial_size} bytes")

                            actual_url = download_url if download_url else req.url
                            async with session.get(actual_url, headers=headers, proxy=proxy_url) as response:
                                if response.status not in [200, 206]:
                                    raise Exception(f"HTTP {response.status}: {response.reason}")

                                # Get Content-Length (don't overwrite a total_size obtained during preparsing)
                                content_length = response.headers.get('Content-Length')
                                if content_length and (not req.total_size or req.total_size == 0):
                                    req.total_size = int(content_length) + initial_size
                                    db.commit()
                                    print(f"[LOG] Content-Length로 total_size 설정: {req.total_size}")

                                # Telegram download-start notification (after the HTTP connection succeeds)
                                try:
                                    file_name = req.file_name or "Unknown File"
                                    file_size = req.file_size
                                    download_mode = "proxy" if proxy_url else "local"
                                    send_telegram_start_notification(file_name, download_mode, "ko", file_size)
                                    print(f"[LOG] 텔레그램 다운로드 시작 알림 전송: {file_name}")
                                except Exception as telegram_error:
                                    print(f"[WARNING] 텔레그램 다운로드 시작 알림 실패: {telegram_error}")

                                # Actual file download
                                print(f"[DEBUG] 파일 다운로드 시작 - 초기크기: {initial_size}, 총크기: {req.total_size}")
                                downloaded_size = await download_file_content(
                                    response, req.save_path, initial_size, req.total_size, req, db
                                )
                                print(f"[DEBUG] 파일 다운로드 완료 - 최종크기: {downloaded_size}")

                                # Rename the .part file to the final file name
                                final_path = get_final_file_path(req.save_path)
                                if req.save_path != final_path:
                                    try:
                                        shutil.move(req.save_path, final_path)
                                        print(f"[DEBUG] 파일 리네임: {req.save_path} -> {final_path}")
                                        req.save_path = final_path
                                        db.commit()  # Commit the file path change immediately
                                    except Exception as rename_error:
                                        print(f"[WARNING] 파일 리네임 실패: {rename_error}")

                                # Completion handling
                                print(f"[LOG] 다운로드 완료 처리 시작: {req.id}")
                                req.status = StatusEnum.done
                                req.downloaded_size = downloaded_size
                                req.finished_at = datetime.datetime.now()
                                _clear_failure_metadata(req)
                                print(f"[LOG] 상태를 done으로 변경 완료")

                                db.commit()
                                download_success = True
                                break  # Exit the retry loop on success

                except Exception as download_error:
                    print(f"[ERROR] 다운로드 실패 ({retry_count + 1}): {download_error}")

                    # Both 404/410 signal link expiry or session loss - attempt re-parsing
                    err_text = str(download_error)
                    expired = (
                        "404" in err_text or "410" in err_text
                        or "Gone" in err_text or "Not Found" in err_text
                    )
                    if expired:
                        print(f"[WARNING] 다운로드 링크 만료/세션 손실 감지 - 재파싱 시도")
                        try:
                            # Re-parse
                            parse_url = choose_1fichier_parse_url(req.url, req.original_url)
                            if not parse_url:
                                raise Exception("원본 1fichier 파일 페이지 URL을 찾을 수 없음")

                            loop = asyncio.get_event_loop()
                            new_parse_result = await loop.run_in_executor(
                                None,
                                lambda: parse_1fichier_simple_sync(
                                    parse_url,
                                    req.password,
                                    _build_proxy_dict(proxy_addr),
                                    proxy_addr,
                                    req.id,
                                )
                            )

                            if new_parse_result and new_parse_result.get('download_link'):
                                download_url = new_parse_result['download_link']
                                # Refresh the session context obtained from re-parsing too
                                cookies = new_parse_result.get('cookies') or cookies
                                user_agent = new_parse_result.get('user_agent') or user_agent
                                referer = new_parse_result.get('referer') or referer
                                print(f"[LOG] 재파싱 성공, 새 다운로드 링크: {download_url}")
                                # continue to retry with the new link
                                continue
                            else:
                                print(f"[ERROR] 재파싱 실패")
                        except Exception as reparse_error:
                            print(f"[ERROR] 재파싱 오류: {reparse_error}")

                    if req.use_proxy and proxy_addr:
                        # Record the failed proxy and increment the failure count
                        await proxy_manager.mark_proxy_failed(db, proxy_addr)
                        failed_count += 1
                        retry_count += 1
                        print(f"[LOG] 다음 프록시로 재시도... ({retry_count}/{MAX_DOWNLOAD_RETRIES})")

                        # Throttle SSE frequency (every 50, or every 10 seconds)
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

                        # Check the max retry count
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

            # Telegram success notification
            print(f"[DEBUG] 텔레그램 성공 알림 전송 시작 (경로2): {req.file_name}")
            try:
                # Compute the processing time
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

            # Cooldown to avoid back-to-back 1fichier requests
            if "1fichier" in req.url.lower():
                print(f"[LOG] 1fichier 다운로드 완료 - 5초 쿨다운 시작")
                await asyncio.sleep(5)
                print(f"[LOG] 1fichier 쿨다운 완료")

        except Exception as e:
            print(f"[ERROR] 파일 다운로드 실패: {e}")
            verdict = apply_failure_to_request(req, "다운로드", str(e))
            user_message = verdict.user_message
            req.status = StatusEnum.failed
            req.finished_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "failed",
                "message": user_message,
                "stage": "다운로드",
                "raw_error": str(e),
                "failure_kind": verdict.kind,
                "next_retry_at": verdict.next_retry_at.isoformat() if verdict.next_retry_at else None,
                "attempt_count": verdict.attempt_count,
            })

            # Telegram failure notification
            try:
                # Compute the processing time (even on failure)
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
            # Force a status check and log
            try:
                db.refresh(req)
                print(f"[LOG] 최종 상태 확인: ID={req.id}, 상태={req.status}, 완료시간={req.finished_at}")
            except Exception as final_error:
                print(f"[ERROR] 최종 상태 확인 실패: {final_error}")

    async def _perform_local_download_async(self, req: DownloadRequest, db: Session):
        """Perform a local download"""
        try:
            print(f"[DEBUG] 로컬 다운로드 시작: {req.id}")

            # Extract the file name (if not yet extracted)
            if not req.file_name:
                await self._extract_filename_from_url(req, db)

            # Perform the actual file download
            await self._perform_file_download_async(req, db)

        except Exception as e:
            print(f"[ERROR] 로컬 다운로드 실패: {e}")
            verdict = apply_failure_to_request(req, "다운로드", str(e))
            req.status = StatusEnum.failed
            req.finished_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "failed",
                "message": verdict.user_message,
                "stage": "다운로드",
                "raw_error": str(e),
                "failure_kind": verdict.kind,
                "next_retry_at": verdict.next_retry_at.isoformat() if verdict.next_retry_at else None,
                "attempt_count": verdict.attempt_count,
            })
            raise Exception(f"로컬 다운로드 실패: {e}")

    async def _download_special_hoster_async(self, req: DownloadRequest, db: Session):
        """Resolve a file hosting page (MegaUp/DataNodes, etc.) to a final link, then download."""
        print(f"[DEBUG] 특수 호스팅 파싱 시작: {req.id} - {req.url}")
        await self.send_download_update(req.id, {
            "status": "parsing",
            "progress": 0,
            "message": "호스팅 페이지 파싱 중..."
        })
        req.status = StatusEnum.parsing
        db.commit()

        try:
            loop = asyncio.get_event_loop()
            if not req.use_proxy:
                try:
                    parse_result = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: parse_special_hoster_sync(req.url, req.password),
                        ),
                        timeout=SPECIAL_HOSTER_PARSE_TIMEOUT_SEC,
                    )
                except asyncio.TimeoutError:
                    # The executor thread may linger until its own bounded calls
                    # finish, but the task fails now so the semaphore slot is freed
                    # and the row leaves the "parsing" state instead of hanging.
                    minutes = SPECIAL_HOSTER_PARSE_TIMEOUT_SEC // 60
                    raise Exception(
                        f"호스팅 페이지 파싱 시간 초과 ({minutes}분). "
                        "FlareSolverr 미응답 또는 호스트 차단 가능."
                    )
            else:
                # Proxy mode: route the parse request through user proxies and
                # retry across proxies on failure (download step stays direct).
                total_proxy_list = await proxy_manager.get_user_proxy_list(db)
                total_proxies = len(total_proxy_list) if total_proxy_list else 0
                MAX_RETRIES = min(MAX_DOWNLOAD_RETRIES_PROXY_CAP, total_proxies)

                retry_count = 0
                parse_result = None
                while parse_result is None and retry_count < MAX_RETRIES:
                    # Check the download-stopped state
                    db.refresh(req)
                    if req.status == StatusEnum.stopped:
                        print(f"[LOG] 다운로드 정지됨, 파싱 중단: {req.id}")
                        return

                    proxy_addr = await proxy_manager.get_next_available_proxy(db, req.id)
                    if not proxy_addr:
                        raise Exception("모든 프록시 시도 실패")
                    proxies = _build_proxy_dict(proxy_addr)

                    # Throttle SSE frequency (every 50, or every 10 seconds)
                    if self.should_send_sse(req.id, retry_count + 1):
                        total_failed_count = await proxy_manager.get_total_failed_count(db)
                        await sse_manager.broadcast_message("proxy_trying", {
                            "id": req.id,
                            "proxy": proxy_addr,
                            "step": "파싱",
                            "current": retry_count + 1,
                            "total": total_proxies,
                            "failed": total_failed_count,
                        })
                        print(f"[LOG] SSE 파싱시도 전송: {retry_count + 1}/{total_proxies}")

                    try:
                        parse_result = await asyncio.wait_for(
                            loop.run_in_executor(
                                None,
                                lambda p=proxies: parse_special_hoster_sync(
                                    req.url, req.password, proxies=p
                                ),
                            ),
                            timeout=SPECIAL_HOSTER_PARSE_TIMEOUT_SEC,
                        )
                        if parse_result:
                            break
                    except asyncio.TimeoutError:
                        await proxy_manager.mark_proxy_failed(db, proxy_addr)
                        retry_count += 1
                        continue
                    except Exception as e:
                        print(f"[LOG] 프록시 파싱 실패 {proxy_addr}: {e}")
                        await proxy_manager.mark_proxy_failed(db, proxy_addr)
                        retry_count += 1
                        if retry_count >= MAX_RETRIES:
                            raise
                        continue

                if not parse_result:
                    raise Exception(
                        f"프록시 파싱 실패 - 최대 재시도({MAX_RETRIES}) 초과"
                    )

            file_info = parse_result.get("file_info") or {}
            if _should_replace_file_name(req.file_name, file_info.get("name")):
                req.file_name = file_info["name"]
                print(f"[LOG] 호스팅 파일명 저장: {req.file_name}")
            if file_info.get("size") and not req.file_size:
                req.file_size = file_info["size"]
                total_size = _size_text_to_bytes(req.file_size)
                if total_size and (not req.total_size or req.total_size == 0):
                    req.total_size = total_size
                print(f"[LOG] 호스팅 파일크기 저장: {req.file_size}")

            if req.original_url != req.url:
                req.original_url = req.url
            db.commit()

            await sse_manager.broadcast_message("filename_update", {
                "id": req.id,
                "filename": req.file_name,
                "file_size": req.file_size
            })

            download_url = parse_result.get("download_link")
            if not download_url:
                raise Exception("호스팅 파싱 결과에서 다운로드 링크를 찾을 수 없음")

            req.status = StatusEnum.downloading
            await self.send_download_update(req.id, {
                "status": "downloading",
                "progress": 0,
                "message": "다운로드 중..."
            })
            db.commit()

            if not req.save_path:
                filename_to_use = req.file_name or f"download_{req.id}"
                req.save_path = generate_file_path(filename_to_use, is_temporary=True)
                db.commit()

            await self._download_file_directly(
                req,
                db,
                download_url,
                cookies=parse_result.get("cookies") or {},
                user_agent=parse_result.get("user_agent"),
                referer=parse_result.get("referer") or req.url,
                parse_url=req.url,
                max_reparse=0,
            )
        except Exception as e:
            print(f"[ERROR] 특수 호스팅 처리 실패: {e}")
            verdict = apply_failure_to_request(req, "파싱", str(e))
            req.status = StatusEnum.failed
            req.finished_at = datetime.datetime.now()
            db.commit()
            await self.send_download_update(req.id, {
                "status": "failed",
                "message": verdict.user_message,
                "stage": "파싱",
                "raw_error": str(e),
                "failure_kind": verdict.kind,
                "next_retry_at": verdict.next_retry_at.isoformat() if verdict.next_retry_at else None,
                "attempt_count": verdict.attempt_count,
            })

    async def _download_mega_async(self, req: DownloadRequest, db: Session):
        """Resolve a MEGA public link and stream-decrypt it to disk.

        MEGA content is client-side encrypted, so it gets its own path: parse the
        link, fetch the temp URL/size/name from MEGA's API, then AES-CTR decrypt
        while streaming. The temp URL expires, so this always re-resolves (never
        skips parsing on restart).
        """
        print(f"[DEBUG] MEGA 다운로드 시작: {req.id} - {req.url}")
        await self.send_download_update(req.id, {
            "status": "parsing", "progress": 0, "message": "MEGA 링크 분석 중..."
        })
        req.status = StatusEnum.parsing
        db.commit()

        try:
            file_id, key = parse_mega_url(req.url)
            async with aiohttp.ClientSession() as session:
                info = await fetch_mega_file_info(session, file_id, key)

                # MEGA's decrypted attributes are the authoritative name — apply
                # unconditionally. (The URL alone only yields a host/id
                # placeholder, e.g. "mega.nz", which can carry a '.' and would
                # otherwise be mistaken for an already-resolved name.)
                req.file_name = info.name
                req.total_size = info.size
                req.file_size = _format_bytes(info.size)
                if req.original_url != req.url:
                    req.original_url = req.url
                if not req.save_path:
                    req.save_path = generate_file_path(
                        info.name or f"download_{req.id}", is_temporary=True
                    )
                if not req.started_at:
                    req.started_at = datetime.datetime.now()
                req.status = StatusEnum.downloading
                db.commit()

                await sse_manager.broadcast_message("filename_update", {
                    "id": req.id, "filename": req.file_name, "file_size": req.file_size
                })
                await self.send_download_update(req.id, {
                    "status": "downloading", "progress": 0, "message": "MEGA 다운로드 중..."
                })

                # Throttled progress: keep downloaded_size live, push SSE ~1/s.
                last_sse = [0.0]

                def progress_cb(downloaded: int, total: int):
                    req.downloaded_size = downloaded
                    now = time.time()
                    if now - last_sse[0] >= 1.0 or downloaded >= total:
                        last_sse[0] = now
                        pct = round(downloaded / total * 100, 1) if total else 0
                        asyncio.create_task(self.send_download_update(
                            req.id, {"status": "downloading", "progress": pct}
                        ))

                written = await download_mega_file(
                    session, info, req.save_path,
                    progress_cb=progress_cb,
                    is_cancelled=lambda: cancel_signal.is_cancelled(req.id),
                )

            # Rename .part → final name
            final_path = get_final_file_path(req.save_path)
            if req.save_path != final_path:
                try:
                    shutil.move(req.save_path, final_path)
                    req.save_path = final_path
                except Exception as rename_error:
                    print(f"[WARNING] MEGA 파일 리네임 실패: {rename_error}")

            req.status = StatusEnum.done
            req.downloaded_size = written
            req.finished_at = datetime.datetime.now()
            _clear_failure_metadata(req)
            db.commit()
            await self.send_download_update(req.id, {
                "status": "done", "progress": 100, "message": "다운로드 완료"
            })
            try:
                send_telegram_notification(
                    req.file_name, "success", language="ko",
                    file_size_str=req.file_size, save_path=req.save_path,
                    download_mode="local",
                )
            except Exception as telegram_error:
                print(f"[WARNING] 텔레그램 성공 알림 실패: {telegram_error}")

        except asyncio.CancelledError:
            # stop_download_async owns the 'stopped' status; just unwind.
            raise
        except Exception as e:
            print(f"[ERROR] MEGA 처리 실패: {e}")
            message = mega_error_message(e) if isinstance(e, MegaApiError) else str(e)
            verdict = apply_failure_to_request(req, "MEGA", message)
            req.status = StatusEnum.failed
            req.finished_at = datetime.datetime.now()
            db.commit()
            await self.send_download_update(req.id, {
                "status": "failed",
                "message": verdict.user_message,
                "stage": "MEGA",
                "raw_error": str(e),
                "failure_kind": verdict.kind,
                "next_retry_at": verdict.next_retry_at.isoformat() if verdict.next_retry_at else None,
                "attempt_count": verdict.attempt_count,
            })

    async def stop_download_async(self, req_id: int, db: Session) -> bool:
        """Stop an async download"""
        try:
            print(f"[DEBUG] 다운로드 중지 시작 - ID: {req_id}")

            # 0. Set the cancel signal immediately — the 1fichier countdown/wait
            #    loop wakes up without DB polling.
            cancel_signal.signal_cancel(req_id)

            # 1. Cancel the running task immediately
            task_cancelled = False
            if req_id in self.download_tasks:
                try:
                    task = self.download_tasks[req_id]
                    task.cancel()
                    print(f"[DEBUG] 태스크 취소 요청 완료: {req_id}")

                    # Fast cancellation with a short timeout
                    try:
                        await asyncio.wait_for(task, timeout=TASK_CANCEL_TIMEOUT_SEC)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass

                    # Remove the task immediately
                    del self.download_tasks[req_id]
                    task_cancelled = True
                    print(f"[DEBUG] 태스크 정리 완료: {req_id}")
                except Exception as e:
                    print(f"[ERROR] 태스크 취소 실패: {e}")

            # 2. Update the status in the DB
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

            # 3. Send the SSE update
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
            traceback.print_exc()
            return False

    async def _extract_filename_from_url(self, req: DownloadRequest, db: Session):
        """Extract the file name from the URL"""
        try:
            print(f"[LOG] URL에서 파일명 추출 시도: {req.url}")

            from urllib.parse import urlparse, unquote

            parsed_url = urlparse(req.url)
            path = unquote(parsed_url.path)

            # Opendrive special handling
            if "opendrive.com" in req.url.lower():
                # URL pattern: https://www.opendrive.com/d/ODlfMzkzMTYwMTlf/Hollow%20Knight%20Silksong_U%201.0.28497%20%28Kor%29.nsp
                # The file name is included in the URL path
                path_parts = path.split('/')
                if len(path_parts) >= 3:
                    filename = unquote(path_parts[-1])  # The last part is the file name
                    if filename and '.' in filename:
                        req.file_name = filename
                        print(f"[LOG] Opendrive 파일명 추출: {filename}")
                        db.commit()

                        # Reset the save path with the new file name
                        req.save_path = generate_file_path(req.file_name, is_temporary=True)
                        print(f"[LOG] Opendrive 저장경로 재설정: {req.save_path}")
                        db.commit()

                        # Send the file name update over SSE
                        await sse_manager.broadcast_message("filename_update", {
                            "id": req.id,
                            "filename": req.file_name,
                            "file_size": req.file_size
                        })
                        return

            # Extract the file name from a typical URL
            if path and '/' in path:
                filename = path.split('/')[-1]
                if filename and '.' in filename:
                    req.file_name = filename
                    print(f"[LOG] 일반 URL 파일명 추출: {filename}")

                    # Reset the save path with the new file name
                    req.save_path = generate_file_path(req.file_name, is_temporary=True)
                    print(f"[LOG] 일반 URL 저장경로 재설정: {req.save_path}")
                    db.commit()

                    # Send the file name update over SSE
                    await sse_manager.broadcast_message("filename_update", {
                        "id": req.id,
                        "filename": req.file_name,
                        "file_size": req.file_size
                    })
                    return

            # Try extracting the file name from the Content-Disposition header
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

                                        # Reset the save path with the new file name
                                        req.save_path = generate_file_path(req.file_name, is_temporary=True)
                                        print(f"[LOG] Content-Disposition 저장경로 재설정: {req.save_path}")
                                        db.commit()

                                        # Send the file name update over SSE
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
        """Task cleanup"""
        # Clear the cancel signal too, to prevent in-memory leaks.
        cancel_signal.clear(req_id)

        if req_id in self.download_tasks:
            del self.download_tasks[req_id]
            print(f"[LOG] 다운로드 태스크 정리: {req_id}")

            # Check whether the download was stopped before deciding to auto-start
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

            # After a download completes, auto-start a pending download (with a slight delay to let the semaphore release)
            asyncio.create_task(self._delayed_start_next_pending())

    async def _delayed_start_next_pending(self):
        """Start a pending download after a delay for the semaphore to release"""
        try:
            # Wait briefly for the semaphore to release (waiting for the async with block to exit)
            await asyncio.sleep(0.5)
            print(f"[DEBUG] 세마포어 해제 대기 완료, 자동 시작 체크")

            # Log the current semaphore state
            print(f"[DEBUG] 현재 세마포어 상태 - 1fichier: {self.fichier_local_semaphore._value}, 전체: {self.total_download_semaphore._value}")

            await self._start_next_pending_download()
        except Exception as e:
            print(f"[ERROR] 지연된 자동 시작 실패: {e}")

    async def _start_next_pending_download(self):
        """(Re)launch pending downloads that have no live task.

        Each download task queues itself on the correct semaphore (per-site or
        the shared general/1fichier one), so a freed slot is picked up by an
        already-parked task automatically. This sweep only needs to relaunch
        pendings that lost their task (e.g. after a server restart); ones still
        parked on a semaphore are skipped to avoid duplicate tasks. We therefore
        do NOT gate on semaphore values here — that old check used the wrong
        (general) semaphore for per-site hosts and left pendings unstarted."""
        try:
            db = SessionLocal()

            # Query all pending downloads (sorted by request time ascending)
            pending_downloads = db.query(DownloadRequest).filter(
                DownloadRequest.status == StatusEnum.pending
            ).order_by(DownloadRequest.requested_at.asc()).all()

            if not pending_downloads:
                print("[LOG] 대기중인 다운로드 없음")
                return

            started_count = 0
            for req in pending_downloads:
                # Skip ones already parked on a semaphore (live task present).
                existing = self.download_tasks.get(req.id)
                if existing is not None and not existing.done():
                    continue
                success = await self.start_download_async(req, db)
                if success:
                    started_count += 1
                    print(f"[LOG] 대기 다운로드 자동 시작: {req.id}")

            if started_count > 0:
                print(f"[LOG] 총 {started_count}개 다운로드 자동 시작됨")

        except Exception as e:
            print(f"[ERROR] 자동 다운로드 시작 실패: {e}")
        finally:
            db.close()

    async def auto_start_pending_downloads(self):
        """Auto-start pending downloads (public method)"""
        await self._start_next_pending_download()

    async def get_download_status(self, req_id: int) -> Dict[str, Any]:
        """Query download status"""
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
        """Clean up all download tasks"""
        for req_id, task in list(self.download_tasks.items()):
            try:
                task.cancel()
                await asyncio.wait_for(task, timeout=TASK_CANCEL_TIMEOUT_SEC)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            finally:
                if req_id in self.download_tasks:
                    del self.download_tasks[req_id]

        print(f"[LOG] 모든 다운로드 태스크 정리 완료")


# Global instance
download_core = DownloadCore()
