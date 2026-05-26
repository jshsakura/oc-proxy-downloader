# -*- coding: utf-8 -*-
"""Translate download/parse failure causes into user-friendly messages + classify them.

The raw exception message alone (e.g. ``HTTP 404: Not Found``) does not tell an
ordinary user what went wrong or what to do, so known error patterns are
classified and normalized into the following format::

    [<stage>] <cause summary> (<raw message>)
    Action: <what the user can do>

In addition, each failure is tagged with a ``kind`` label so that pointless
batch/single retries can be skipped and a different cooldown can be applied per
kind.

Classification (kind) values:

- ``dead``: a definitive failure where 1fichier states in the body that the file
  was deleted/reported/does not exist. Retrying yields the same result. Can be
  pinned permanently from a single observation.
- ``auth_required``: cannot pass without logging into a 1fichier account.
- ``rate_limited``: explicit wait requirement (429, "you must wait", free-quota
  exceeded notice). If ``retry_after_seconds`` is set, it auto-retries after that
  time.
- ``cloudflare``: failed to bypass the Cloudflare challenge. Recoverable by
  waiting / switching network.
- ``proxy_blocked``: VPS/VPN/Professional infrastructure block. May pass on a
  different proxy or a residential line.
- ``blocked``: classified but matches none of the above two — a temporary block.
  Short cooldown.
- ``transient``: network/timeout/5xx/one-off 404·410 cases. Exponential backoff.
- ``unknown``: classification failed. Quarantined after accumulated attempts.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import random
import re
from typing import List, Optional, Tuple


# kind constants
KIND_DEAD = "dead"
KIND_AUTH_REQUIRED = "auth_required"
KIND_RATE_LIMITED = "rate_limited"
KIND_CLOUDFLARE = "cloudflare"
KIND_PROXY_BLOCKED = "proxy_blocked"
KIND_BLOCKED = "blocked"
KIND_TRANSIENT = "transient"
KIND_UNKNOWN = "unknown"

# Retry policy — referenced by `_compute_next_retry_at`.
# (Simple constants for dict comparison: KIND → backoff seconds)
_TRANSIENT_BACKOFF = (30, 120, 480, 1800, 1800, 1800)  # 30s→2m→8m→30m capped
_UNKNOWN_MAX_ATTEMPTS = 3  # beyond this many accumulated attempts, quarantine as 'unknown_terminal'
_TRANSIENT_MAX_ATTEMPTS = len(_TRANSIENT_BACKOFF)
_ATTEMPTS_RING_SIZE = 5  # attempts_json ring-buffer length


@dataclass(frozen=True)
class ClassifiedError:
    stage: str  # "파싱" (parse) | "다운로드" (download)
    summary: str  # Korean cause summary
    action: str  # action for the user to take
    raw: str  # raw message
    kind: str = KIND_UNKNOWN
    # True if the failure is confirmed by a body marker — can be pinned
    # permanently from a single observation.
    # HTTP-code-based inference is False (a single observation is insufficient).
    definitive: bool = False
    # Explicitly known wait time (seconds). Populated only when 1fichier returns
    # "you must wait N seconds" in the body. None otherwise.
    retry_after_seconds: Optional[int] = None

    def to_user_message(self) -> str:
        return f"[{self.stage} 실패] {self.summary} ({self.raw})\n조치: {self.action}"


# Classification rules — the first matching entry from the top is used. Keywords
# are matched as lowercase substrings.
# Format: (keyword, summary, action, kind, definitive)
#
# Ordering principles:
#   1. Definitive body-marker reasons (definitive=True) come first — so the exact
#      reason is caught even if it happens to co-occur in an HTTP-code string.
#   2. Then 1fichier's own block messages (the Korean prefix the parser raises).
#   3. Finally, generic HTTP/network patterns.
_RULES: Tuple[Tuple[str, str, str, str, bool], ...] = (
    # --- definitive dead: 1fichier body marker ---
    ("1fichier 차단: 파일 삭제됨", "1fichier 측에서 파일이 삭제되었습니다",
     "다른 다운로드 링크를 사용하세요. (재시도해도 같은 결과)",
     KIND_DEAD, True),
    ("1fichier 차단: 파일이 신고되어 차단됨",
     "1fichier 가 신고로 인해 파일을 차단했습니다",
     "다른 다운로드 링크를 사용하세요. (재시도해도 같은 결과)",
     KIND_DEAD, True),
    ("1fichier 차단: 파일 없음", "1fichier 에 해당 파일이 존재하지 않습니다",
     "URL 의 파일 ID 가 정확한지 확인하세요.",
     KIND_DEAD, True),
    ("file not found", "파일이 1fichier 에 존재하지 않습니다",
     "URL 의 파일 ID 가 정확한지 확인하세요.",
     KIND_DEAD, True),
    ("file has been deleted", "1fichier 측에서 파일이 삭제되었습니다",
     "다른 다운로드 링크를 사용하세요.",
     KIND_DEAD, True),
    ("file has been reported", "1fichier 가 신고로 인해 파일을 차단했습니다",
     "다른 다운로드 링크를 사용하세요.",
     KIND_DEAD, True),
    ("megaup 파일 없음", "MegaUp 측에서 파일이 삭제되었거나 존재하지 않습니다",
     "다른 다운로드 링크를 사용하세요. (재시도해도 같은 결과)",
     KIND_DEAD, True),
    ("datanodes 파일 없음", "DataNodes 측에서 파일이 삭제되었거나 존재하지 않습니다",
     "다른 다운로드 링크를 사용하세요. (재시도해도 같은 결과)",
     KIND_DEAD, True),
    ("gofile 파일 없음", "Gofile 측에서 파일이 삭제되었거나 존재하지 않습니다",
     "다른 다운로드 링크를 사용하세요. (재시도해도 같은 결과)",
     KIND_DEAD, True),
    ("mega 파일 없음", "MEGA 측에서 파일이 삭제되었거나 존재하지 않습니다",
     "다른 다운로드 링크를 사용하세요. (재시도해도 같은 결과)",
     KIND_DEAD, True),
    ("파일명(확장자)을 확인할 수 없",
     "서버가 파일명을 제공하지 않아 다운로드를 중단했습니다",
     "이 링크는 파일명/확장자를 알 수 없습니다. 다른 미러를 사용하세요.",
     KIND_DEAD, True),

    # --- auth_required: guest slots / registered-user only ---
    ("rapidgator 무료 모드는 500 mb 초과",
     "Rapidgator 무료 모드 제한으로 이 파일을 받을 수 없습니다",
     "Rapidgator 프리미엄 계정/쿠키 지원이 추가되기 전에는 다른 미러를 사용하세요.",
     KIND_AUTH_REQUIRED, True),
    ("gofile은 콘텐츠 권한",
     "Gofile 콘텐츠 권한 또는 프리미엄 정책에 막혔습니다",
     "공개 권한이 있는 링크인지 확인하거나 다른 미러를 사용하세요.",
     KIND_AUTH_REQUIRED, True),
    ("gofile 목록 조회 차단",
     "Gofile 이 이 서버(데이터센터) IP 의 목록 조회를 차단했습니다",
     "가정용 IP(NAS 등)에서 실행하거나 residential 프록시를 사용하면 통과합니다. (다운로드 자체는 IP 무관)",
     KIND_PROXY_BLOCKED, True),
    ("게스트 슬롯이 가득",
     "1fichier 가 무료 게스트 슬롯 부족으로 다운로드를 거부했습니다",
     "설정에서 1fichier 무료 계정으로 로그인하면 즉시 다운로드 가능합니다. "
     "(계정이 없으면 https://1fichier.com/register.pl 에서 무료 가입 후 사용하세요.)",
     KIND_AUTH_REQUIRED, True),

    # --- proxy_blocked: VPS/VPN body marker ---
    ("1fichier 차단: vps/vpn",
     "이 서버 IP 가 1fichier 의 VPS/VPN 차단 목록에 있어 접근이 거부됩니다",
     "주거용 인터넷에서 직접 시도하거나, 설정에서 다른 프록시를 켜고 다시 시도하세요.",
     KIND_PROXY_BLOCKED, True),
    ("professional infrastructure detected",
     "VPS/VPN IP 가 1fichier 에 의해 차단되었습니다",
     "주거용 회선 또는 다른 프록시로 시도하세요.",
     KIND_PROXY_BLOCKED, True),

    # --- rate_limited: explicit wait/quota messages ---
    ("mega 대역폭 한도", "MEGA 대역폭 한도(IP당)에 걸렸습니다",
     "잠시 후 다시 시도하세요. (대용량/연속 다운로드 시 IP 단위로 제한됩니다)",
     KIND_RATE_LIMITED, True),
    ("mega 일시 오류", "MEGA 가 일시적으로 응답하지 않습니다",
     "잠시 후 자동으로 다시 시도합니다.",
     KIND_TRANSIENT, False),
    ("1fichier 차단: 무료 다운로드 한도 초과",
     "1fichier 무료 다운로드 한도에 걸렸습니다",
     "프록시 모드를 켜거나 한도가 풀릴 때까지 기다리세요.",
     KIND_RATE_LIMITED, True),
    ("limite", "1fichier 무료 다운로드 한도에 걸렸습니다",
     "프록시 모드를 켜거나 한도가 풀릴 때까지 기다리세요.",
     KIND_RATE_LIMITED, True),
    ("limited to 1 download",
     "1fichier 무료 다운로드 한도에 걸렸습니다",
     "프록시 모드를 켜거나 한도가 풀릴 때까지 기다리세요.",
     KIND_RATE_LIMITED, True),
    ("limit", "1fichier 무료 다운로드 한도에 걸렸습니다",
     "프록시 모드를 켜거나 한도가 풀릴 때까지 기다리세요.",
     KIND_RATE_LIMITED, False),
    ("http 429", "요청 한도 초과 (1fichier 무료 다운로드 제한)",
     "최소 5~10 분 기다린 뒤 다시 시도하거나 프록시 모드를 켜세요.",
     KIND_RATE_LIMITED, True),
    ("you must wait", "1fichier 가 명시적으로 대기를 요구했습니다",
     "잠시 후 다시 시도하세요.",
     KIND_RATE_LIMITED, True),
    ("대기시간이 너무",
     "1fichier 대기시간이 비정상적으로 길어 중단했습니다 (무료 다운로드 한도 가능성)",
     "잠시 후 다시 시도하거나 설정에서 1fichier 계정으로 로그인하세요.",
     KIND_RATE_LIMITED, True),

    # --- cloudflare ---
    ("1fichier 차단: cloudflare", "Cloudflare 챌린지 우회에 실패했습니다",
     "잠시 후 다시 시도하거나 다른 네트워크/프록시로 시도하세요.",
     KIND_CLOUDFLARE, True),
    ("send.now는 cloudflare", "Send.now Cloudflare 챌린지에 막혔습니다",
     "브라우저 세션/쿠키 지원이 추가되기 전에는 다른 미러를 사용하세요.",
     KIND_CLOUDFLARE, True),
    ("send.now turnstile", "Send.now 사이트 내부 Turnstile 검증이 필요합니다",
     "FlareSolverr 로 Cloudflare 는 통과했지만 내부 캡차는 자동 처리할 수 없습니다. 다른 미러를 사용하세요.",
     KIND_CLOUDFLARE, True),
    ("cloudflare", "Cloudflare 챌린지 또는 보안 검사에 막혔습니다",
     "잠시 후 다시 시도하거나 다른 네트워크/프록시로 시도하세요.",
     KIND_CLOUDFLARE, False),

    # --- blocked: other blocks ---
    ("1fichier 폼 제출 거부",
     "1fichier 가 폼 제출을 거부하고 홈페이지를 반환했습니다",
     "통신사 CGNAT/공유 IP 가 비주거용으로 분류된 경우가 많습니다. "
     "프록시 모드를 켜거나 1fichier 계정 로그인으로 시도하세요.",
     KIND_BLOCKED, False),
    ("다운로드 폼", "1fichier 페이지 구조 변경 또는 캡차 발생",
     "잠시 후 다시 시도하세요. 반복되면 issue 를 등록해주세요.",
     KIND_BLOCKED, False),
    ("다운로드 링크를 찾을 수 없음", "1fichier 응답에서 다운로드 링크를 추출하지 못했습니다",
     "잠시 후 다시 시도하거나 프록시 모드를 켜세요.",
     KIND_BLOCKED, False),
    # A page-load failure that carries an explicit HTTP status must defer to the
    # status code: 404/410 are link-expiry/session-loss (transient), NOT a dead
    # URL. These specific rules precede the generic "페이지 로드 실패" catch below
    # so a 404 isn't mislabeled as "check the URL / blocked".
    ("페이지 로드 실패: http 404",
     "1fichier 페이지가 404 를 반환했습니다 (링크 만료 / 일시 세션 손실 / 파일 삭제 가능성)",
     "다시 시도해주세요. 반복되면 '전체 링크 검수' 로 진짜 죽었는지 확인하세요.",
     KIND_TRANSIENT, False),
    ("페이지 로드 실패: http 410",
     "1fichier 페이지가 410 (Gone) 을 반환했습니다 (링크 만료 / 일시 세션 손실 가능성)",
     "다시 시도해주세요. 반복되면 '전체 링크 검수' 로 확인하세요.",
     KIND_TRANSIENT, False),
    ("페이지 로드 실패: http 503",
     "1fichier 서버가 일시적으로 점검 중입니다 (페이지 로드 503)",
     "잠시 후 다시 시도하세요.",
     KIND_TRANSIENT, False),
    ("페이지 로드 실패", "1fichier 페이지를 가져오지 못했습니다",
     "URL 이 올바른지, 파일이 살아있는지 확인하세요.",
     KIND_BLOCKED, False),
    ("모든 프록시 시도 실패", "사용 가능한 프록시가 모두 실패했습니다",
     "프록시 목록을 새로고침하거나 로컬 모드로 시도하세요.",
     KIND_BLOCKED, False),
    ("호스팅 최종 링크가 파일 대신 html",
     "호스팅 사이트가 파일 대신 HTML/보안 확인 페이지를 반환했습니다",
     "브라우저 확인 또는 Cloudflare 챌린지가 걸린 상태입니다. 다른 미러를 사용하거나 브라우저 세션 지원이 필요합니다.",
     KIND_CLOUDFLARE, False),
    ("http 403", "호스팅 서버가 접근을 거부했습니다 (Cloudflare 차단 가능)",
     "잠시 후 다시 시도하거나 다른 네트워크/프록시로 시도하세요.",
     KIND_BLOCKED, False),

    # --- transient: one-off HTTP/network (a lone observation cannot confirm dead) ---
    # Key change: HTTP 404/410 / Not Found / Gone are transient. A true dead is
    # caught only by the body-marker rules above.
    ("http 404", "응답이 404 였습니다 (링크 만료 / 일시 세션 손실 / 파일 삭제 가능성)",
     "다시 시도해주세요. 반복되면 '전체 링크 검수' 로 진짜 죽었는지 확인.",
     KIND_TRANSIENT, False),
    ("not found", "응답이 404 였습니다",
     "다시 시도해주세요. 반복되면 '전체 링크 검수' 로 확인.",
     KIND_TRANSIENT, False),
    ("http 410", "응답이 410 (Gone) 이었습니다",
     "다시 시도해주세요. 반복되면 '전체 링크 검수' 로 확인.",
     KIND_TRANSIENT, False),
    ("gone", "응답이 410 (Gone) 이었습니다",
     "다시 시도해주세요. 반복되면 '전체 링크 검수' 로 확인.",
     KIND_TRANSIENT, False),
    ("http 502", "1fichier 서버가 일시적으로 응답하지 않습니다",
     "잠시 후 다시 시도하세요.",
     KIND_TRANSIENT, False),
    ("http 503", "1fichier 서버가 일시적으로 점검 중입니다",
     "잠시 후 다시 시도하세요.",
     KIND_TRANSIENT, False),
    ("http 504", "게이트웨이 타임아웃이 발생했습니다",
     "네트워크가 불안정한 경우입니다. 잠시 후 다시 시도하세요.",
     KIND_TRANSIENT, False),
    ("timeout", "응답 대기 시간이 초과되었습니다",
     "네트워크 상태를 확인하거나 프록시를 변경해 다시 시도하세요.",
     KIND_TRANSIENT, False),
    ("connection reset", "연결이 강제로 끊겼습니다",
     "네트워크 상태를 확인하고 다시 시도하세요.",
     KIND_TRANSIENT, False),
    ("connection refused", "1fichier 서버가 연결을 거부했습니다",
     "잠시 후 다시 시도하거나 프록시를 변경하세요.",
     KIND_TRANSIENT, False),
    ("name or service not known", "DNS 조회에 실패했습니다",
     "인터넷 연결 또는 DNS 설정을 확인하세요.",
     KIND_TRANSIENT, False),
    ("ssl", "SSL/TLS 핸드셰이크에 실패했습니다",
     "시스템 시간과 인증서 설정을 확인하세요.",
     KIND_TRANSIENT, False),
)


# Extract retry_after in seconds from bodies like "you must wait N seconds" / "wait N min".
_WAIT_PATTERNS = (
    re.compile(r"you must wait\s+(\d+)\s*minute", re.IGNORECASE),
    re.compile(r"wait\s+(\d+)\s*minute", re.IGNORECASE),
    re.compile(r"(\d+)\s*분\s*(?:후|뒤|기다)", re.IGNORECASE),
)


def _extract_retry_after(text: str) -> Optional[int]:
    """Extract the explicit wait time (seconds) from the body. None if absent."""
    if not text:
        return None
    lowered = text.lower()
    for pat in _WAIT_PATTERNS:
        m = pat.search(lowered)
        if m:
            try:
                return int(m.group(1)) * 60
            except ValueError:
                continue
    # cases like "you must wait 30 seconds"
    m = re.search(r"you must wait\s+(\d+)\s*second", lowered)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def classify_error(stage: str, raw_message: str) -> ClassifiedError:
    """Classify a raw error message into a user-friendly form."""
    text = (raw_message or "").lower()
    retry_after = _extract_retry_after(raw_message or "")
    for keyword, summary, action, kind, definitive in _RULES:
        if keyword in text:
            return ClassifiedError(
                stage=stage, summary=summary, action=action,
                raw=raw_message, kind=kind, definitive=definitive,
                retry_after_seconds=retry_after,
            )

    return ClassifiedError(
        stage=stage,
        summary="원인을 자동으로 분류하지 못했습니다",
        action="다시 받기 버튼으로 재시도하세요. 반복되면 로그를 확인해 주세요.",
        raw=raw_message,
        kind=KIND_UNKNOWN,
        definitive=False,
        retry_after_seconds=retry_after,
    )


def format_error(stage: str, raw_message: Optional[str]) -> str:
    """Shortcut that calls ``classify_error`` then ``to_user_message`` in one step."""
    return classify_error(stage, raw_message or "").to_user_message()


def classify_failure_text(error_text: Optional[str]) -> str:
    """Extract only the kind from the ``error`` body stored in the DB.

    Used as a fallback for pre-migration records whose ``failure_kind`` column is
    NULL. New code should reference the column first.
    """
    if not error_text:
        return KIND_UNKNOWN
    return classify_error("", error_text).kind


def is_terminal_failure(error_text: Optional[str]) -> bool:
    """Decide whether the failure won't change on retry (text-based fallback)."""
    return classify_failure_text(error_text) == KIND_DEAD


def is_auth_required_failure(error_text: Optional[str]) -> bool:
    """A failure that can only pass with a 1fichier account login (text-based fallback)."""
    return classify_failure_text(error_text) == KIND_AUTH_REQUIRED


# ---------------------------------------------------------------------------
# Failure-application helpers
# ---------------------------------------------------------------------------

# Whether a kind is permanently pinned (retry-blocked) — the fact that
# `next_retry_at` is None is itself a signal, but an explicit helper reads
# better at the call site.
TERMINAL_KINDS = frozenset({KIND_DEAD, KIND_AUTH_REQUIRED, "unknown_terminal"})


def _compute_next_retry_at(kind: str, attempt_count: int,
                           retry_after_seconds: Optional[int]) -> Optional[datetime]:
    """Compute the next retry-allowed time from ``kind`` + past attempt count.

    None means no automatic retry (a manual or external trigger is required).
    """
    now = datetime.now()
    if kind in TERMINAL_KINDS:
        return None

    if kind == KIND_RATE_LIMITED:
        # If 1fichier specified a wait time, use it + a 60s margin.
        # Otherwise 600s (10 minutes).
        wait = (retry_after_seconds or 600) + 60
        return now + timedelta(seconds=wait)

    if kind == KIND_CLOUDFLARE:
        # 5 minutes + 0-60s jitter
        return now + timedelta(seconds=300 + random.randint(0, 60))

    if kind == KIND_PROXY_BLOCKED:
        # Keep it short since the same proxy pool may hand out the same IP again.
        return now + timedelta(seconds=30)

    if kind == KIND_BLOCKED:
        return now + timedelta(seconds=120)

    if kind == KIND_TRANSIENT:
        idx = min(max(attempt_count - 1, 0), _TRANSIENT_MAX_ATTEMPTS - 1)
        return now + timedelta(seconds=_TRANSIENT_BACKOFF[idx])

    if kind == KIND_UNKNOWN:
        if attempt_count >= _UNKNOWN_MAX_ATTEMPTS:
            return None  # quarantine (caller promotes kind to 'unknown_terminal')
        return now + timedelta(seconds=60 * attempt_count)

    return None


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


@dataclass(frozen=True)
class FailureVerdict:
    """Result of ``apply_failure_to_request`` — the caller exposes it directly via SSE etc."""
    user_message: str
    kind: str
    next_retry_at: Optional[datetime]
    attempt_count: int
    definitive: bool


_DUPLICATE_APPLY_WINDOW_SEC = 10  # treat the same raw re-arriving within 10s as a duplicate call


def apply_failure_to_request(
    req,
    stage: str,
    raw_error: str,
    proxy_addr: Optional[str] = None,
) -> FailureVerdict:
    """Perform all follow-up handling for a single failure (classification,
    attempts ring buffer, next_retry_at, error text) at once and update the
    relevant columns on ``req``. ``db.commit()`` is the caller's responsibility.

    Dead promotion policy:
    - If this classification is a DEAD/AUTH_REQUIRED with ``definitive=True``, pin
      it immediately.
    - Otherwise, if the last 2 of the accumulated attempts are all the same
      non-transient kind and at least one of them was ``definitive=True``, pin
      that kind.
    - Normally, keep the classification result as-is.

    Duplicate-call guard:
    - In a handler chain (e.g. ``_download_file_directly`` raises and
      ``_download_with_proxy_async`` catches it), if the same ``raw_error``
      arrives twice within 10s, only the verdict is reconstructed from the last
      attempts entry and returned — no column/ring-buffer change.
    """
    classified = classify_error(stage, raw_error or "")
    now = datetime.now()
    raw_truncated = (raw_error or "")[:500]

    # Duplicate-call guard — skip if the previous attempt has the same raw and the time gap is short.
    prior_attempts = _load_attempts(getattr(req, "attempts_json", None))
    if prior_attempts:
        last = prior_attempts[-1]
        try:
            last_ts = datetime.fromisoformat(last.get("ts", ""))
        except (ValueError, TypeError):
            last_ts = None
        if (
            last_ts is not None
            and last.get("raw") == raw_truncated
            and (now - last_ts).total_seconds() < _DUPLICATE_APPLY_WINDOW_SEC
        ):
            return FailureVerdict(
                user_message=req.error or classified.to_user_message(),
                kind=getattr(req, "failure_kind", None) or classified.kind,
                next_retry_at=getattr(req, "next_retry_at", None),
                attempt_count=getattr(req, "attempt_count", 0) or 0,
                definitive=classified.definitive,
            )

    # Update the attempts_json ring buffer
    attempts = list(prior_attempts)
    attempts.append({
        "ts": now.isoformat(),
        "stage": stage,
        "kind": classified.kind,
        "definitive": classified.definitive,
        "raw": raw_truncated,
        "proxy": proxy_addr,
    })
    attempts = attempts[-_ATTEMPTS_RING_SIZE:]

    attempt_count = (getattr(req, "attempt_count", 0) or 0) + 1

    # Decide on Dead promotion
    kind = classified.kind
    if not classified.definitive and kind not in (KIND_DEAD, KIND_AUTH_REQUIRED):
        # Do not pin from a single observation — check consistency of the previous attempt(s).
        recent = attempts[-2:]
        if len(recent) == 2 and recent[0]["kind"] == recent[1]["kind"]:
            agreed_kind = recent[0]["kind"]
            had_definitive = any(a.get("definitive") for a in recent)
            if had_definitive and agreed_kind in (KIND_DEAD, KIND_AUTH_REQUIRED):
                kind = agreed_kind

    # Quarantine accumulated unknowns
    if kind == KIND_UNKNOWN and attempt_count >= _UNKNOWN_MAX_ATTEMPTS:
        kind = "unknown_terminal"

    next_retry_at = _compute_next_retry_at(
        kind, attempt_count, classified.retry_after_seconds
    )

    user_message = classified.to_user_message()

    # Reflect to columns (compat: setattr stays safe even where new columns are absent from the model)
    req.error = user_message
    if hasattr(req, "failure_kind"):
        req.failure_kind = kind
    if hasattr(req, "attempt_count"):
        req.attempt_count = attempt_count
    if hasattr(req, "next_retry_at"):
        req.next_retry_at = next_retry_at
    if hasattr(req, "attempts_json"):
        req.attempts_json = _dump_attempts(attempts)

    return FailureVerdict(
        user_message=user_message,
        kind=kind,
        next_retry_at=next_retry_at,
        attempt_count=attempt_count,
        definitive=classified.definitive,
    )


def is_retry_blocked_now(req, has_credentials: bool) -> Optional[str]:
    """Reason to skip ``req`` on a batch/single retry — None if there is none.

    Looks at the persistent columns (``failure_kind`` / ``next_retry_at``) first,
    and falls back to text-based detection if absent. Return values:
      - "dead": permanent failure. Always blocked.
      - "auth_required": account not configured.
      - "cooldown": the next retry time has not arrived yet.
      - None: retry is possible.
    """
    kind = getattr(req, "failure_kind", None)
    next_retry = getattr(req, "next_retry_at", None)

    if not kind:
        # Pre-migration record — fall back to text
        err = req.error or ""
        text_kind = classify_failure_text(err)
        if text_kind == KIND_DEAD:
            return "dead"
        if text_kind == KIND_AUTH_REQUIRED and not has_credentials:
            return "auth_required"
        return None

    if kind == KIND_DEAD or kind == "unknown_terminal":
        return "dead"
    if kind == KIND_AUTH_REQUIRED and not has_credentials:
        return "auth_required"
    if next_retry and next_retry > datetime.now():
        return "cooldown"
    return None
