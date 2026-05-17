# -*- coding: utf-8 -*-
"""1fichier 링크 가벼운 상태 검사 (probe).

이미 ``error_messages`` 가 실제 다운로드 시도에서 받은 에러를 분류한다면,
이 모듈은 **다운로드 시도 없이** 페이지를 한 번 GET 해서 *왜* 실패하고 있는지
독립적인 증거를 모은다. captcha/대기/POST 흐름을 일절 타지 않아 빠르고,
1fichier 에 가하는 부하도 적다.

용도:
- 사용자가 누른 "전체 링크 검수" 의 단건 동작.
- 박제된 ``failure_kind=dead`` 가 실제로도 dead 인지 재확인.
- 일괄 재시도 직전에 죽은 링크 미리 솎아내기.

본 함수는 글로벌 토큰 버킷 throttle 을 내장한다 (1 req / 3s, 동시 1).
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


# error_messages 의 KIND_* 와 같은 네임스페이스에 속하지만, probe 만의 결과 코드.
# 'alive' = 살아있는 링크 확인됨, 'unreachable' = 1fichier 가 아니거나 네트워크 자체 불통.
KIND_ALIVE = "alive"
KIND_UNREACHABLE = "unreachable"


_THROTTLE_MIN_INTERVAL_SEC = 3.0  # 글로벌 최소 간격
_PROBE_TIMEOUT_SEC = 20.0
_PROBE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_ATTEMPTS_RING_SIZE = 5  # error_messages 와 동일


@dataclass(frozen=True)
class ProbeResult:
    """단건 probe 결과.

    ``kind`` 는 ``error_messages.KIND_*`` 또는 ``"alive"`` / ``"unreachable"``.
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
    """단순 글로벌 throttle — 최소 N초 간격으로만 통과시킴."""

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
    """detect_block_reason 의 한국어 마커를 KIND_* 로 매핑."""
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
    """1fichier URL 을 가볍게 GET 해서 상태 분류.

    captcha/대기/POST 안 함 — 본문 마커와 HTTP 코드만 본다.
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

    # HTTP-코드 단독으로 dead 박지 않음 — 본문 마커가 우선
    block = detect_block_reason(body)
    if block:
        kind = _kind_from_marker(block)
        return ProbeResult(
            kind=kind, summary=f"1fichier 본문 마커: {block}",
            raw_status=status, body_marker=block,
            retry_after_seconds=_extract_retry_after_from_body(body),
            # 본문 마커는 결정적이지만 dead 만 single-shot 박제 허용 —
            # apply_probe_to_request 에서 그렇게 처리.
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
        # 단발 관측 — transient. 같은 결과가 누적되면 audit 누적 룰에서 dead 로 승급.
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

    # 200 + 차단 마커 없음 — 파일 정보 추출되면 살아있다고 판정.
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

    # 200 이지만 파일 정보도 없고 알려진 차단 마커도 없음 — UI 변경/캡차 가능
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
    """probe 결과를 ``req`` 의 분류 컬럼에 반영.

    - ``last_probed_at`` 항상 갱신.
    - ``attempts_json`` 링버퍼에 stage="검수" 로 한 줄 추가.
    - ``kind == alive``: ``failure_kind`` / ``next_retry_at`` 초기화 — 다음 일괄
      재시도에서 정상 픽업.
    - ``kind == dead`` 또는 ``auth_required`` (definitive): 즉시 박제.
    - 그 외 (cloudflare/rate_limited/blocked/transient/unreachable/unknown):
      기존 backoff 가 있으면 유지, 없으면 보수적 cooldown 부여. ``failure_kind``
      가 비어있던 항목엔 채워준다.
    """
    now = datetime.datetime.now()

    # attempts_json 추가
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
        # 살아있는 링크 — 박제 해제, cooldown 도 해제. attempt_count 는 의미 있어서 유지.
        if hasattr(req, "failure_kind"):
            req.failure_kind = None
        if hasattr(req, "next_retry_at"):
            req.next_retry_at = None
        # 사용자가 UI 에서 보기 좋게 안내. status 는 변경 안 함 (그건 retry 가 할 일).
        req.error = "[검수] 링크 살아있음 — 재시도 가능"
        return

    if probe.kind == KIND_UNREACHABLE:
        # 1fichier 가 아니거나 네트워크 자체 불통 — 분류 변경 X, 메시지만 갱신
        req.error = probe.to_user_message()
        return

    # 본문 마커 기반 결정적 dead/auth_required → 즉시 박제
    if probe.definitive and probe.kind in (KIND_DEAD, KIND_AUTH_REQUIRED):
        if hasattr(req, "failure_kind"):
            req.failure_kind = probe.kind
        if hasattr(req, "next_retry_at"):
            req.next_retry_at = None
        req.error = probe.to_user_message()
        return

    # 그 외: cooldown 갱신 (기존 backoff 유지 우선)
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
