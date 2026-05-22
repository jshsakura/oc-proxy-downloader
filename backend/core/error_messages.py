# -*- coding: utf-8 -*-
"""다운로드/파싱 실패 원인을 사용자가 알기 쉬운 메시지로 변환 + 분류.

원본 예외 메시지(``HTTP 404: Not Found`` 등) 만으로는 일반 사용자가 무엇을
어떻게 해야 할지 알 수 없으므로, 알려진 에러 패턴을 분류해서 다음 형식의
메시지로 통일한다::

    [<단계>] <원인 요약> (<원본 메시지>)
    조치: <사용자가 할 수 있는 행동>

추가로 각 실패에 ``kind`` 라벨을 붙여 일괄/단건 재시도가 의미 없는 호출을
건너뛰고, 종류별로 다른 cooldown 을 적용할 수 있게 한다.

분류(kind) 값:

- ``dead``: 1fichier 가 본문에서 파일 삭제/신고/존재없음을 명시한 결정적
  실패. 재시도해도 결과 같음. 단일 관측만으로도 박제 가능.
- ``auth_required``: 1fichier 계정 로그인 없으면 통과 못 함.
- ``rate_limited``: 명시적 대기 요구(429, "you must wait", 무료 한도 초과
  안내). ``retry_after_seconds`` 가 있으면 그 시간 이후에 자동 재시도.
- ``cloudflare``: Cloudflare 챌린지 우회 실패. 시간/네트워크 교체로 회수.
- ``proxy_blocked``: VPS/VPN/Professional infrastructure 차단. 다른 프록시나
  주거용 회선에서 시도하면 통과 가능.
- ``blocked``: 분류는 됐지만 위 둘 어디에도 안 맞는 일시 차단. 짧은 cooldown.
- ``transient``: 네트워크/타임아웃/5xx/단발 404·410 류. 지수 backoff.
- ``unknown``: 분류 실패. 누적 시도 후 격리.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import random
import re
from typing import List, Optional, Tuple


# kind 상수
KIND_DEAD = "dead"
KIND_AUTH_REQUIRED = "auth_required"
KIND_RATE_LIMITED = "rate_limited"
KIND_CLOUDFLARE = "cloudflare"
KIND_PROXY_BLOCKED = "proxy_blocked"
KIND_BLOCKED = "blocked"
KIND_TRANSIENT = "transient"
KIND_UNKNOWN = "unknown"

# 재시도 정책 — `_compute_next_retry_at` 가 참조.
# (단순한 dict 비교용 상수: KIND → backoff seconds)
_TRANSIENT_BACKOFF = (30, 120, 480, 1800, 1800, 1800)  # 30s→2m→8m→30m capped
_UNKNOWN_MAX_ATTEMPTS = 3  # 그 이상 누적되면 'unknown_terminal' 로 격리
_TRANSIENT_MAX_ATTEMPTS = len(_TRANSIENT_BACKOFF)
_ATTEMPTS_RING_SIZE = 5  # attempts_json 링버퍼 길이


@dataclass(frozen=True)
class ClassifiedError:
    stage: str  # "파싱" | "다운로드"
    summary: str  # 한국어 원인 요약
    action: str  # 사용자가 취할 행동
    raw: str  # 원본 메시지
    kind: str = KIND_UNKNOWN
    # 본문 마커로 확신된 실패면 True — 단일 관측만으로도 영구 박제 가능.
    # HTTP 코드 기반 추정은 False (단일 관측 불충분).
    definitive: bool = False
    # 명시적으로 알려진 대기 시간 (초). 1fichier 가 본문에서 "you must wait
    # N seconds" 를 줬을 때만 채워짐. 없으면 None.
    retry_after_seconds: Optional[int] = None

    def to_user_message(self) -> str:
        return f"[{self.stage} 실패] {self.summary} ({self.raw})\n조치: {self.action}"


# 분류 규칙 — 위에서부터 매칭되는 첫 항목 사용. 키워드는 소문자 substring 매칭.
# 형식: (keyword, summary, action, kind, definitive)
#
# 정렬 원칙:
#   1. 본문 마커 기반 결정적 사유 (definitive=True) 가 가장 먼저 — HTTP 코드
#      문자열에 우연히 같이 박혀도 정확한 사유로 잡히도록.
#   2. 그 다음 1fichier 자체 차단 메시지(parser 가 던지는 한국어 prefix).
#   3. 마지막에 일반 HTTP/네트워크 패턴.
_RULES: Tuple[Tuple[str, str, str, str, bool], ...] = (
    # --- definitive dead: 1fichier 본문 마커 ---
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

    # --- auth_required: 게스트 슬롯/등록자 한정 ---
    ("rapidgator 무료 모드는 500 mb 초과",
     "Rapidgator 무료 모드 제한으로 이 파일을 받을 수 없습니다",
     "Rapidgator 프리미엄 계정/쿠키 지원이 추가되기 전에는 다른 미러를 사용하세요.",
     KIND_AUTH_REQUIRED, True),
    ("gofile은 콘텐츠 권한",
     "Gofile 콘텐츠 권한 또는 프리미엄 정책에 막혔습니다",
     "공개 권한이 있는 링크인지 확인하거나 다른 미러를 사용하세요.",
     KIND_AUTH_REQUIRED, True),
    ("게스트 슬롯이 가득",
     "1fichier 가 무료 게스트 슬롯 부족으로 다운로드를 거부했습니다",
     "설정에서 1fichier 무료 계정으로 로그인하면 즉시 다운로드 가능합니다. "
     "(계정이 없으면 https://1fichier.com/register.pl 에서 무료 가입 후 사용하세요.)",
     KIND_AUTH_REQUIRED, True),

    # --- proxy_blocked: VPS/VPN 본문 마커 ---
    ("1fichier 차단: vps/vpn",
     "이 서버 IP 가 1fichier 의 VPS/VPN 차단 목록에 있어 접근이 거부됩니다",
     "주거용 인터넷에서 직접 시도하거나, 설정에서 다른 프록시를 켜고 다시 시도하세요.",
     KIND_PROXY_BLOCKED, True),
    ("professional infrastructure detected",
     "VPS/VPN IP 가 1fichier 에 의해 차단되었습니다",
     "주거용 회선 또는 다른 프록시로 시도하세요.",
     KIND_PROXY_BLOCKED, True),

    # --- rate_limited: 명시적 대기/한도 메시지 ---
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

    # --- blocked: 그 외 차단 ---
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

    # --- transient: 단발 HTTP/네트워크 (단독 관측은 dead 확정 못 함) ---
    # 핵심 변경: HTTP 404/410 / Not Found / Gone 은 transient. 진짜 dead 는
    # 위쪽 본문 마커 규칙에서만 잡힌다.
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


# "you must wait N seconds" / "wait N min" 류 본문에서 retry_after 초 단위 추출.
_WAIT_PATTERNS = (
    re.compile(r"you must wait\s+(\d+)\s*minute", re.IGNORECASE),
    re.compile(r"wait\s+(\d+)\s*minute", re.IGNORECASE),
    re.compile(r"(\d+)\s*분\s*(?:후|뒤|기다)", re.IGNORECASE),
)


def _extract_retry_after(text: str) -> Optional[int]:
    """본문에서 명시적 대기시간(초)을 추출. 없으면 None."""
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
    # "you must wait 30 seconds" 류
    m = re.search(r"you must wait\s+(\d+)\s*second", lowered)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return None
    return None


def classify_error(stage: str, raw_message: str) -> ClassifiedError:
    """원본 에러 메시지를 사용자 친화적인 형태로 분류."""
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
    """``classify_error`` 의 ``to_user_message`` 를 한 번에 호출하는 단축 함수."""
    return classify_error(stage, raw_message or "").to_user_message()


def classify_failure_text(error_text: Optional[str]) -> str:
    """DB 에 저장된 ``error`` 본문에서 kind 만 추출.

    ``failure_kind`` 컬럼이 NULL 인 마이그레이션 이전 레코드에 fallback 으로
    쓰인다. 새 코드는 컬럼을 우선 참조해야 한다.
    """
    if not error_text:
        return KIND_UNKNOWN
    return classify_error("", error_text).kind


def is_terminal_failure(error_text: Optional[str]) -> bool:
    """재시도해도 결과가 바뀌지 않는 실패인지 판정 (텍스트 기반 폴백)."""
    return classify_failure_text(error_text) == KIND_DEAD


def is_auth_required_failure(error_text: Optional[str]) -> bool:
    """1fichier 계정 로그인이 있어야만 통과 가능한 실패 (텍스트 기반 폴백)."""
    return classify_failure_text(error_text) == KIND_AUTH_REQUIRED


# ---------------------------------------------------------------------------
# 실패 적용 헬퍼
# ---------------------------------------------------------------------------

# kind 가 영구 박제(재시도 차단) 인지 — `next_retry_at` 가 None 이라는 사실
# 자체가 시그널이지만, 명시적 헬퍼가 호출처에서 읽기 좋다.
TERMINAL_KINDS = frozenset({KIND_DEAD, KIND_AUTH_REQUIRED, "unknown_terminal"})


def _compute_next_retry_at(kind: str, attempt_count: int,
                           retry_after_seconds: Optional[int]) -> Optional[datetime]:
    """``kind`` + 과거 시도 횟수로 다음 재시도 가능 시각 계산.

    None 이면 자동 재시도 안 함 (수동 또는 외부 트리거 필요).
    """
    now = datetime.now()
    if kind in TERMINAL_KINDS:
        return None

    if kind == KIND_RATE_LIMITED:
        # 1fichier 가 명시한 대기 시간이 있으면 그것 + 60s 여유.
        # 없으면 600s (10분).
        wait = (retry_after_seconds or 600) + 60
        return now + timedelta(seconds=wait)

    if kind == KIND_CLOUDFLARE:
        # 5분 + 0~60s jitter
        return now + timedelta(seconds=300 + random.randint(0, 60))

    if kind == KIND_PROXY_BLOCKED:
        # 같은 프록시 풀이 또 같은 IP 를 줄 수 있으니 짧게.
        return now + timedelta(seconds=30)

    if kind == KIND_BLOCKED:
        return now + timedelta(seconds=120)

    if kind == KIND_TRANSIENT:
        idx = min(max(attempt_count - 1, 0), _TRANSIENT_MAX_ATTEMPTS - 1)
        return now + timedelta(seconds=_TRANSIENT_BACKOFF[idx])

    if kind == KIND_UNKNOWN:
        if attempt_count >= _UNKNOWN_MAX_ATTEMPTS:
            return None  # 격리 (호출자가 kind 를 'unknown_terminal' 로 승급)
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
    """``apply_failure_to_request`` 의 결과 — 호출자가 SSE 등에 그대로 노출."""
    user_message: str
    kind: str
    next_retry_at: Optional[datetime]
    attempt_count: int
    definitive: bool


_DUPLICATE_APPLY_WINDOW_SEC = 10  # 같은 raw 가 10초 내 재유입되면 중복 호출로 간주


def apply_failure_to_request(
    req,
    stage: str,
    raw_error: str,
    proxy_addr: Optional[str] = None,
) -> FailureVerdict:
    """실패 1건의 모든 후속 처리(분류·attempts 링버퍼·next_retry_at·error 텍스트)를
    한 번에 수행하고 ``req`` 의 관련 컬럼을 수정한다. ``db.commit()`` 은 호출자
    책임.

    Dead 승급 정책:
    - 이번 분류가 ``definitive=True`` 인 DEAD/AUTH_REQUIRED 면 즉시 박제.
    - 그렇지 않으면 누적된 시도 중 last 2 회가 모두 동일한 non-transient
      kind 이고 그 중 한 번이라도 ``definitive=True`` 면 그 kind 로 박제.
    - 평소엔 분류 결과 그대로.

    중복 호출 가드:
    - 핸들러 체인(``_download_file_directly`` 가 raise 후 ``_download_with_proxy_async``
      가 잡는 케이스 등)에서 같은 ``raw_error`` 가 10초 내 두 번 들어오면 마지막
      attempts 엔트리 정보로 verdict 만 재구성해서 반환 — 컬럼/링버퍼 변경 없음.
    """
    classified = classify_error(stage, raw_error or "")
    now = datetime.now()
    raw_truncated = (raw_error or "")[:500]

    # 중복 호출 가드 — 직전 attempt 가 같은 raw 이고 시간 차가 짧으면 skip.
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

    # attempts_json 링버퍼 갱신
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

    # Dead 승급 결정
    kind = classified.kind
    if not classified.definitive and kind not in (KIND_DEAD, KIND_AUTH_REQUIRED):
        # 단발 관측만으로 박제 금지 — 직전 시도(들) 의 일관성 확인.
        recent = attempts[-2:]
        if len(recent) == 2 and recent[0]["kind"] == recent[1]["kind"]:
            agreed_kind = recent[0]["kind"]
            had_definitive = any(a.get("definitive") for a in recent)
            if had_definitive and agreed_kind in (KIND_DEAD, KIND_AUTH_REQUIRED):
                kind = agreed_kind

    # unknown 누적 격리
    if kind == KIND_UNKNOWN and attempt_count >= _UNKNOWN_MAX_ATTEMPTS:
        kind = "unknown_terminal"

    next_retry_at = _compute_next_retry_at(
        kind, attempt_count, classified.retry_after_seconds
    )

    user_message = classified.to_user_message()

    # 컬럼 반영 (호환: 새 컬럼이 모델에 없는 환경에서도 setattr 안전하게)
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
    """배치/단건 재시도 시 ``req`` 를 건너뛸 사유 — 없으면 None.

    우선 영구 컬럼(``failure_kind`` / ``next_retry_at``) 을 보고, 없으면 텍스트
    기반 폴백. 반환값:
      - "dead": 영구 실패. 항상 차단.
      - "auth_required": 계정 미설정.
      - "cooldown": 다음 재시도 시각 미도래.
      - None: 재시도 가능.
    """
    kind = getattr(req, "failure_kind", None)
    next_retry = getattr(req, "next_retry_at", None)

    if not kind:
        # 마이그레이션 이전 레코드 — 텍스트로 폴백
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
