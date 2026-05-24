# -*- coding: utf-8 -*-
"""Lightweight status check (probe) for 1fichier links.

While ``error_messages`` classifies errors received from an actual download
attempt, this module GETs the page once **without attempting a download** to
gather independent evidence of *why* it is failing. It never goes through the
captcha/wait/POST flow, so it is fast and puts little load on 1fichier.

Uses:
- The single-item action behind the user's "audit all links" button.
- Re-confirming that a pinned ``failure_kind=dead`` is actually dead.
- Pre-filtering dead links right before a batch retry.

This function has a built-in global token-bucket throttle (1 req / 3s, concurrency 1).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import re
from dataclasses import dataclass
from typing import List, Optional

import httpx

from core.parser import fichier_parser
from core.simple_parser import detect_block_reason
from core.error_messages import (
    KIND_DEAD,
    KIND_AUTH_REQUIRED,
    KIND_RATE_LIMITED,
    KIND_CLOUDFLARE,
    KIND_PROXY_BLOCKED,
    KIND_BLOCKED,
    KIND_TRANSIENT,
    _compute_next_retry_at,
)


# In the same namespace as error_messages' KIND_*, but these are probe-only
# result codes. 'alive' = link confirmed alive, 'unreachable' = not 1fichier or
# the network itself is down.
KIND_ALIVE = "alive"
KIND_UNREACHABLE = "unreachable"


_THROTTLE_MIN_INTERVAL_SEC = 3.0  # global minimum interval
_PROBE_TIMEOUT_SEC = 20.0
_PROBE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_ATTEMPTS_RING_SIZE = 5  # same as error_messages


@dataclass(frozen=True)
class ProbeResult:
    """Single probe result.

    ``kind`` is one of ``error_messages.KIND_*`` or ``"alive"`` / ``"unreachable"``.
    """
    kind: str
    summary: str
    raw_status: Optional[int]
    body_marker: Optional[str]
    retry_after_seconds: Optional[int]
    definitive: bool

    def to_user_message(self) -> str:
        if self.kind == KIND_ALIVE:
            return f"[검수] 살아있는 링크 ({self.summary})"
        return f"[검수] {self.summary}"


class _Throttle:
    """Simple global throttle — only lets calls through at a minimum N-second interval."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_at: float = 0.0

    async def wait(self):
        async with self._lock:
            now = asyncio.get_event_loop().time()
            wait = self._last_at + self.min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_at = asyncio.get_event_loop().time()


_throttle = _Throttle(_THROTTLE_MIN_INTERVAL_SEC)


_WAIT_PAT_BODY = (
    re.compile(r"you must wait\s+(\d+)\s*minute", re.IGNORECASE),
    re.compile(r"wait\s+(\d+)\s*minute", re.IGNORECASE),
)


def _extract_retry_after_from_body(text: str) -> Optional[int]:
    if not text:
        return None
    for pat in _WAIT_PAT_BODY:
        m = pat.search(text)
        if m:
            try:
                return int(m.group(1)) * 60
            except ValueError:
                continue
    m = re.search(r"you must wait\s+(\d+)\s*second", text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def _kind_from_marker(marker: str) -> str:
    """Map detect_block_reason's Korean markers to KIND_*."""
    m = marker.lower()
    if "파일" in marker and ("삭제" in marker or "신고" in marker or "없" in marker):
        return KIND_DEAD
    if "file not found" in m or "deleted" in m or "reported" in m:
        return KIND_DEAD
    if "vps" in m or "vpn" in m:
        return KIND_PROXY_BLOCKED
    if "게스트 슬롯" in marker or "guest slot" in m:
        return KIND_AUTH_REQUIRED
    if "한도" in marker or "limit" in m:
        return KIND_RATE_LIMITED
    if "cloudflare" in m:
        return KIND_CLOUDFLARE
    return KIND_BLOCKED


async def probe_1fichier_url(url: str) -> ProbeResult:
    """Lightly GET a 1fichier URL and classify its status.

    No captcha/wait/POST — only looks at body markers and the HTTP code.
    """
    if "1fichier.com" not in (url or ""):
        return ProbeResult(
            kind=KIND_UNREACHABLE, summary="1fichier URL 이 아님",
            raw_status=None, body_marker=None,
            retry_after_seconds=None, definitive=True,
        )

    await _throttle.wait()

    headers = {
        "User-Agent": _PROBE_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }

    try:
        async with httpx.AsyncClient(
            timeout=_PROBE_TIMEOUT_SEC, headers=headers, follow_redirects=True,
        ) as client:
            response = await client.get(url)
    except httpx.TimeoutException:
        return ProbeResult(
            kind=KIND_TRANSIENT, summary="probe 타임아웃",
            raw_status=None, body_marker=None,
            retry_after_seconds=None, definitive=False,
        )
    except (httpx.ConnectError, httpx.ReadError, httpx.NetworkError) as e:
        return ProbeResult(
            kind=KIND_UNREACHABLE, summary=f"probe 네트워크 오류: {type(e).__name__}",
            raw_status=None, body_marker=None,
            retry_after_seconds=None, definitive=False,
        )

    status = response.status_code
    body = response.text or ""

    # Don't pin dead on the HTTP code alone — the body marker takes priority
    block = detect_block_reason(body)
    if block:
        kind = _kind_from_marker(block)
        return ProbeResult(
            kind=kind, summary=f"1fichier 본문 마커: {block}",
            raw_status=status, body_marker=block,
            retry_after_seconds=_extract_retry_after_from_body(body),
            # Body markers are definitive, but only dead is allowed to be
            # pinned single-shot — handled that way in apply_probe_to_request.
            definitive=True,
        )

    if status == 429:
        return ProbeResult(
            kind=KIND_RATE_LIMITED, summary="1fichier 가 429 (Too Many Requests)",
            raw_status=status, body_marker=None,
            retry_after_seconds=_extract_retry_after_from_body(body) or 600,
            definitive=True,
        )

    if status in (404, 410):
        # One-off observation — transient. If the same result accumulates, the
        # audit accumulation rule promotes it to dead.
        return ProbeResult(
            kind=KIND_TRANSIENT, summary=f"probe 응답이 {status} (단발)",
            raw_status=status, body_marker=None,
            retry_after_seconds=None, definitive=False,
        )

    if status >= 500:
        return ProbeResult(
            kind=KIND_TRANSIENT, summary=f"1fichier 서버 {status}",
            raw_status=status, body_marker=None,
            retry_after_seconds=None, definitive=False,
        )

    if status != 200:
        return ProbeResult(
            kind=KIND_TRANSIENT, summary=f"probe 응답이 {status}",
            raw_status=status, body_marker=None,
            retry_after_seconds=None, definitive=False,
        )

    # 200 + no block marker — judged alive if file info can be extracted.
    try:
        file_info = fichier_parser.extract_file_info(body)
    except Exception:
        file_info = {}
    has_file = bool((file_info or {}).get("name"))

    if has_file:
        return ProbeResult(
            kind=KIND_ALIVE,
            summary=f"파일 페이지 확인: {file_info.get('name')}",
            raw_status=status, body_marker=None,
            retry_after_seconds=None, definitive=True,
        )

    # 200 but no file info and no known block marker — possible UI change/captcha
    return ProbeResult(
        kind="blocked",
        summary="probe 가 파일 정보를 찾지 못함 (페이지 변경 가능성)",
        raw_status=status, body_marker=None,
        retry_after_seconds=None, definitive=False,
    )


def _load_attempts(attempts_json: Optional[str]) -> List[dict]:
    if not attempts_json:
        return []
    try:
        parsed = json.loads(attempts_json)
        if isinstance(parsed, list):
            return parsed
    except (ValueError, TypeError):
        pass
    return []


def _dump_attempts(attempts: List[dict]) -> str:
    return json.dumps(attempts[-_ATTEMPTS_RING_SIZE:], ensure_ascii=False)


def apply_probe_to_request(req, probe: ProbeResult) -> None:
    """Apply the probe result to ``req``'s classification columns.

    - ``last_probed_at`` is always updated.
    - Appends one line to the ``attempts_json`` ring buffer with stage="검수".
    - ``kind == alive``: clears ``failure_kind`` / ``next_retry_at`` — picked up
      normally by the next batch retry.
    - ``kind == dead`` or ``auth_required`` (definitive): pinned immediately.
    - Otherwise (cloudflare/rate_limited/blocked/transient/unreachable/unknown):
      keep the existing backoff if any, otherwise assign a conservative
      cooldown. Fills in ``failure_kind`` for items where it was empty.
    """
    now = datetime.datetime.now()

    # Append to attempts_json
    attempts = _load_attempts(getattr(req, "attempts_json", None))
    attempts.append({
        "ts": now.isoformat(),
        "stage": "검수",
        "kind": probe.kind,
        "definitive": probe.definitive,
        "raw": probe.summary[:500],
        "marker": probe.body_marker,
        "status": probe.raw_status,
    })
    if hasattr(req, "attempts_json"):
        req.attempts_json = _dump_attempts(attempts)
    if hasattr(req, "last_probed_at"):
        req.last_probed_at = now

    if probe.kind == KIND_ALIVE:
        # Alive link — unpin and clear the cooldown. Keep attempt_count since it's meaningful.
        if hasattr(req, "failure_kind"):
            req.failure_kind = None
        if hasattr(req, "next_retry_at"):
            req.next_retry_at = None
        # A nice message for the user in the UI. Don't change status (that's retry's job).
        req.error = "[검수] 링크 살아있음 — 재시도 가능"
        return

    if probe.kind == KIND_UNREACHABLE:
        # Not 1fichier or the network itself is down — don't change the classification, just update the message
        req.error = probe.to_user_message()
        return

    # Definitive dead/auth_required based on body markers → pin immediately
    if probe.definitive and probe.kind in (KIND_DEAD, KIND_AUTH_REQUIRED):
        if hasattr(req, "failure_kind"):
            req.failure_kind = probe.kind
        if hasattr(req, "next_retry_at"):
            req.next_retry_at = None
        req.error = probe.to_user_message()
        return

    # Otherwise: update the cooldown (prefer keeping the existing backoff)
    current_next = getattr(req, "next_retry_at", None)
    suggested = _compute_next_retry_at(
        probe.kind,
        (getattr(req, "attempt_count", 0) or 0) or 1,
        probe.retry_after_seconds,
    )
    if hasattr(req, "next_retry_at"):
        if not current_next or (suggested and suggested > current_next):
            req.next_retry_at = suggested
    if hasattr(req, "failure_kind") and not getattr(req, "failure_kind", None):
        req.failure_kind = probe.kind
    req.error = probe.to_user_message()
