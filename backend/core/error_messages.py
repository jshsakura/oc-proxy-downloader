# -*- coding: utf-8 -*-
"""다운로드/파싱 실패 원인을 사용자가 알기 쉬운 메시지로 변환.

원본 예외 메시지(``HTTP 404: Not Found`` 등) 만으로는 일반 사용자가 무엇을
어떻게 해야 할지 알 수 없으므로, 알려진 에러 패턴을 분류해서 다음 형식의
메시지로 통일한다::

    [<단계>] <원인 요약> (<원본 메시지>)
    조치: <사용자가 할 수 있는 행동>

- ``stage`` 는 ``"파싱"`` 또는 ``"다운로드"``.
- ``원인 요약`` 은 한국어 키워드.
- ``조치`` 는 한 줄짜리 권장 행동.
- ``kind`` 는 자동 분류 카테고리. 일괄/단건 재시도가 이걸 보고 의미 없는
  재요청을 건너뛴다.

분류(kind) 값:

- ``dead``: 원본이 사라졌거나 1fichier 가 영구 차단. 재시도해도 결과 같음.
- ``auth_required``: 1fichier 계정 로그인 없으면 통과 못 함. 자격증명이
  없으면 다운로드를 시도조차 하지 않는다.
- ``blocked``: 일시 차단(Cloudflare, VPN/VPS, 무료 한도 등). 시간/네트워크
  교체로 회수 가능.
- ``transient``: 네트워크/타임아웃 류. 즉시 재시도가 의미 있음.
- ``unknown``: 분류 실패. 기본은 재시도 허용.
"""

from dataclasses import dataclass
from typing import Optional


# kind 상수 — 백엔드 내부에서만 비교하므로 단순 문자열로 통일.
KIND_DEAD = "dead"
KIND_AUTH_REQUIRED = "auth_required"
KIND_BLOCKED = "blocked"
KIND_TRANSIENT = "transient"
KIND_UNKNOWN = "unknown"


@dataclass(frozen=True)
class ClassifiedError:
    stage: str  # "파싱" | "다운로드"
    summary: str  # 한국어 원인 요약
    action: str  # 사용자가 취할 행동
    raw: str  # 원본 메시지
    kind: str = KIND_UNKNOWN

    def to_user_message(self) -> str:
        return f"[{self.stage} 실패] {self.summary} ({self.raw})\n조치: {self.action}"


# (키워드, 요약, 권장조치, kind) 튜플 — 위에서부터 매칭되는 첫 항목 사용.
# 키워드는 소문자 substring 매칭.
_RULES = (
    # 1fichier 가 본문에서 명시적으로 차단을 알리는 패턴들 (parse 단계에서 raise)
    ("1fichier 차단: vps/vpn",
     "이 서버 IP 가 1fichier 의 VPS/VPN 차단 목록에 있어 접근이 거부됩니다",
     "주거용 인터넷에서 직접 시도하거나, 설정에서 다른 프록시를 켜고 다시 시도하세요.",
     KIND_BLOCKED),
    ("1fichier 차단: 파일 삭제됨", "1fichier 측에서 파일이 삭제되었습니다",
     "다른 다운로드 링크를 사용하세요. (재시도해도 같은 결과)",
     KIND_DEAD),
    ("1fichier 차단: 파일이 신고되어 차단됨",
     "1fichier 가 신고로 인해 파일을 차단했습니다",
     "다른 다운로드 링크를 사용하세요. (재시도해도 같은 결과)",
     KIND_DEAD),
    ("1fichier 차단: 파일 없음", "1fichier 에 해당 파일이 존재하지 않습니다",
     "URL 의 파일 ID 가 정확한지 확인하세요.",
     KIND_DEAD),
    ("1fichier 차단: cloudflare", "Cloudflare 챌린지 우회에 실패했습니다",
     "잠시 후 다시 시도하거나 다른 네트워크/프록시로 시도하세요.",
     KIND_BLOCKED),
    ("1fichier 차단: 무료 다운로드 한도 초과",
     "1fichier 무료 다운로드 한도에 걸렸습니다",
     "프록시 모드를 켜거나 한도가 풀릴 때까지 기다리세요.",
     KIND_BLOCKED),
    ("1fichier 폼 제출 거부",
     "1fichier 가 폼 제출을 거부하고 홈페이지를 반환했습니다",
     "통신사 CGNAT/공유 IP 가 비주거용으로 분류된 경우가 많습니다. "
     "프록시 모드를 켜거나 1fichier 계정 로그인(추후 지원)으로 시도하세요.",
     KIND_BLOCKED),
    ("게스트 슬롯이 가득",
     "1fichier 가 무료 게스트 슬롯 부족으로 다운로드를 거부했습니다",
     "설정에서 1fichier 무료 계정으로 로그인하면 즉시 다운로드 가능합니다. "
     "(계정이 없으면 https://1fichier.com/register.pl 에서 무료 가입 후 사용하세요.)",
     KIND_AUTH_REQUIRED),
    ("http 404", "다운로드 링크가 만료되었거나 파일이 삭제되었습니다",
     "다시 받기 버튼을 눌러 재파싱하거나 원본 1fichier 페이지에서 파일이 살아있는지 확인하세요.",
     KIND_DEAD),
    ("not found", "다운로드 링크가 만료되었거나 파일이 삭제되었습니다",
     "다시 받기 버튼을 눌러 재파싱하세요.",
     KIND_DEAD),
    ("http 410", "다운로드 링크가 만료되었습니다",
     "다시 받기 버튼을 눌러 새 링크를 받으세요.",
     KIND_DEAD),
    ("gone", "다운로드 링크가 만료되었습니다",
     "다시 받기 버튼을 눌러 새 링크를 받으세요.",
     KIND_DEAD),
    ("http 403", "1fichier 가 접근을 거부했습니다 (Cloudflare 차단 가능)",
     "잠시 후 다시 시도하거나 프록시 모드를 사용해 보세요.",
     KIND_BLOCKED),
    ("http 429", "요청 한도 초과 (1fichier 무료 다운로드 제한)",
     "최소 5~10 분 기다린 뒤 다시 시도하거나 프록시 모드를 켜세요.",
     KIND_BLOCKED),
    ("limite", "1fichier 무료 다운로드 한도에 걸렸습니다",
     "프록시 모드를 켜거나 한도가 풀릴 때까지 기다리세요.",
     KIND_BLOCKED),
    ("limit", "1fichier 무료 다운로드 한도에 걸렸습니다",
     "프록시 모드를 켜거나 한도가 풀릴 때까지 기다리세요.",
     KIND_BLOCKED),
    ("http 502", "1fichier 서버가 일시적으로 응답하지 않습니다",
     "잠시 후 다시 시도하세요.",
     KIND_TRANSIENT),
    ("http 503", "1fichier 서버가 일시적으로 점검 중입니다",
     "잠시 후 다시 시도하세요.",
     KIND_TRANSIENT),
    ("http 504", "게이트웨이 타임아웃이 발생했습니다",
     "네트워크가 불안정한 경우입니다. 잠시 후 다시 시도하세요.",
     KIND_TRANSIENT),
    ("timeout", "응답 대기 시간이 초과되었습니다",
     "네트워크 상태를 확인하거나 프록시를 변경해 다시 시도하세요.",
     KIND_TRANSIENT),
    ("connection reset", "연결이 강제로 끊겼습니다",
     "네트워크 상태를 확인하고 다시 시도하세요.",
     KIND_TRANSIENT),
    ("connection refused", "1fichier 서버가 연결을 거부했습니다",
     "잠시 후 다시 시도하거나 프록시를 변경하세요.",
     KIND_TRANSIENT),
    ("name or service not known", "DNS 조회에 실패했습니다",
     "인터넷 연결 또는 DNS 설정을 확인하세요.",
     KIND_TRANSIENT),
    ("ssl", "SSL/TLS 핸드셰이크에 실패했습니다",
     "시스템 시간과 인증서 설정을 확인하세요.",
     KIND_TRANSIENT),
    ("다운로드 폼", "1fichier 페이지 구조 변경 또는 캡차 발생",
     "잠시 후 다시 시도하세요. 반복되면 issue 를 등록해주세요.",
     KIND_BLOCKED),
    ("다운로드 링크를 찾을 수 없음", "1fichier 응답에서 다운로드 링크를 추출하지 못했습니다",
     "잠시 후 다시 시도하거나 프록시 모드를 켜세요.",
     KIND_BLOCKED),
    ("페이지 로드 실패", "1fichier 페이지를 가져오지 못했습니다",
     "URL 이 올바른지, 파일이 살아있는지 확인하세요.",
     KIND_BLOCKED),
    ("모든 프록시 시도 실패", "사용 가능한 프록시가 모두 실패했습니다",
     "프록시 목록을 새로고침하거나 로컬 모드로 시도하세요.",
     KIND_TRANSIENT),
)


def classify_error(stage: str, raw_message: str) -> ClassifiedError:
    """원본 에러 메시지를 사용자 친화적인 형태로 분류.

    매칭되는 규칙이 없으면 원본 메시지를 그대로 보여주되, 단계 정보는 붙인다.
    """
    text = (raw_message or "").lower()
    for keyword, summary, action, kind in _RULES:
        if keyword in text:
            return ClassifiedError(
                stage=stage, summary=summary, action=action, raw=raw_message, kind=kind
            )

    return ClassifiedError(
        stage=stage,
        summary="원인을 자동으로 분류하지 못했습니다",
        action="다시 받기 버튼으로 재시도하세요. 반복되면 로그를 확인해 주세요.",
        raw=raw_message,
        kind=KIND_UNKNOWN,
    )


def format_error(stage: str, raw_message: Optional[str]) -> str:
    """``classify_error`` 의 ``to_user_message`` 를 한 번에 호출하는 단축 함수."""
    return classify_error(stage, raw_message or "").to_user_message()


def classify_failure_text(error_text: Optional[str]) -> str:
    """DB 에 저장된 ``error`` 본문(이미 ``[stage 실패] ...`` 형태 또는 원본)에서
    kind 만 추출. 비어 있으면 ``KIND_UNKNOWN``.

    저장된 메시지는 사람이 읽기 좋은 형태로 가공돼 있지만, 키워드 매칭은
    여전히 그 안의 원문/요약 토큰으로 동작하므로 그대로 통과시키면 된다.
    """
    if not error_text:
        return KIND_UNKNOWN
    return classify_error("", error_text).kind


def is_terminal_failure(error_text: Optional[str]) -> bool:
    """재시도해도 결과가 바뀌지 않는 실패인지 판정.

    True 면 일괄 재시작 / 단건 재시도 시 건너뛴다.
    """
    return classify_failure_text(error_text) == KIND_DEAD


def is_auth_required_failure(error_text: Optional[str]) -> bool:
    """1fichier 계정 로그인이 있어야만 통과 가능한 실패."""
    return classify_failure_text(error_text) == KIND_AUTH_REQUIRED
