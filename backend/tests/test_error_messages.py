# -*- coding: utf-8 -*-
"""``core.error_messages`` 테스트.

핵심 계약:
- HTTP 404/410 단독은 더 이상 dead 가 아니라 transient — 본문 마커(파일 삭제/
  신고/없음, file not found 등) 만 dead 로 박제.
- ``apply_failure_to_request`` 가 요청 객체에 분류·attempts·next_retry_at 까지
  한 번에 박는다.
- ``is_retry_blocked_now`` 는 신규 컬럼 우선, 컬럼이 비어있으면 텍스트 폴백.
"""

import datetime
import json

import pytest

from core.error_messages import (
    classify_error,
    format_error,
    classify_failure_text,
    is_terminal_failure,
    is_auth_required_failure,
    is_retry_blocked_now,
    apply_failure_to_request,
    KIND_DEAD,
    KIND_AUTH_REQUIRED,
    KIND_RATE_LIMITED,
    KIND_CLOUDFLARE,
    KIND_PROXY_BLOCKED,
    KIND_BLOCKED,
    KIND_TRANSIENT,
    KIND_UNKNOWN,
)


class _FakeReq:
    """DownloadRequest 의 setattr 인터페이스만 흉내내는 가짜 객체."""

    def __init__(self, **kwargs):
        self.error = None
        self.failure_kind = None
        self.attempt_count = 0
        self.next_retry_at = None
        self.attempts_json = None
        self.last_probed_at = None
        for k, v in kwargs.items():
            setattr(self, k, v)


# ---------------------------------------------------------------------------
# classify_error / format_error — 단계·요약·조치 메시지
# ---------------------------------------------------------------------------

class TestClassify:
    @pytest.mark.parametrize(
        "raw,expected_kw_in_summary",
        [
            ("HTTP 404: Not Found", "404"),
            ("HTTP 410: Gone", "410"),
            ("HTTP 403: Forbidden", "거부"),
            ("HTTP 429: Too Many Requests", "한도"),
            ("HTTP 503: Service Unavailable", "점검"),
            ("HTTP 502: Bad Gateway", "응답"),
            ("HTTP 504: Gateway Timeout", "타임아웃"),
            ("Connection reset by peer", "끊겼"),
            ("Connection refused", "거부"),
            ("Read timeout occurred", "초과"),
            ("Name or service not known", "DNS"),
            ("SSL handshake failed", "SSL"),
            ("다운로드 폼을 찾을 수 없음", "구조"),
            ("다운로드 링크를 찾을 수 없음", "추출"),
            ("페이지 로드 실패: HTTP 500", "가져오지"),
            ("모든 프록시 시도 실패", "프록시"),
            ("응답에 limite 단어 포함", "한도"),
        ],
    )
    def test_known_patterns(self, raw, expected_kw_in_summary):
        result = classify_error("다운로드", raw)
        assert expected_kw_in_summary in result.summary
        assert result.action

    def test_form_rejection_pattern_classified_with_cgnat_hint(self):
        c = classify_error("파싱", "1fichier 폼 제출 거부: 다운로드 페이지 대신 홈페이지가 반환됨 (POST status=200, a_tags=21)")
        assert "거부" in c.summary
        assert "CGNAT" in c.action or "프록시" in c.action

    def test_unknown_pattern_falls_back_with_generic_action(self):
        result = classify_error("다운로드", "weird_unmatched_error_blob")
        assert result.summary == "원인을 자동으로 분류하지 못했습니다"
        assert "재시도" in result.action

    def test_format_error_includes_stage_summary_action_and_raw(self):
        formatted = format_error("다운로드", "HTTP 404: Not Found")
        assert "[다운로드 실패]" in formatted
        assert "HTTP 404" in formatted
        assert "조치:" in formatted

    def test_format_error_with_none_raw(self):
        formatted = format_error("파싱", None)
        assert "[파싱 실패]" in formatted
        assert "재시도" in formatted

    def test_classify_includes_raw_message(self):
        result = classify_error("파싱", "HTTP 410: Gone")
        assert result.raw == "HTTP 410: Gone"
        assert result.stage == "파싱"


# ---------------------------------------------------------------------------
# kind 분류 — dead 박제는 본문 마커만, HTTP 코드는 transient
# ---------------------------------------------------------------------------

class TestKindClassification:
    @pytest.mark.parametrize("raw", [
        "1fichier 차단: 파일 삭제됨 ...",
        "1fichier 차단: 파일이 신고되어 차단됨 ...",
        "1fichier 차단: 파일 없음",
        "the file has been deleted",
        "File not found on server",
    ])
    def test_body_marker_dead_kept(self, raw):
        assert classify_failure_text(raw) == KIND_DEAD
        assert is_terminal_failure(raw) is True

    @pytest.mark.parametrize("raw", [
        "HTTP 404: Not Found",
        "HTTP 410: Gone",
        "[파싱 실패] ... (페이지 로드 실패: HTTP 404)",
    ])
    def test_http_404_410_downgraded_to_non_dead(self, raw):
        # 핵심 회귀 방지: 단발 404/410 만으로 dead 박제 금지.
        kind = classify_failure_text(raw)
        assert kind != KIND_DEAD
        assert is_terminal_failure(raw) is False

    def test_auth_required_classification(self):
        msg = "[다운로드 실패] 게스트 슬롯이 가득 ..."
        assert classify_failure_text(msg) == KIND_AUTH_REQUIRED
        assert is_auth_required_failure(msg) is True
        assert is_terminal_failure(msg) is False

    @pytest.mark.parametrize("raw,expected_kind", [
        ("HTTP 503: Service Unavailable", KIND_TRANSIENT),
        ("Read timeout occurred", KIND_TRANSIENT),
        ("HTTP 429: Too Many Requests", KIND_RATE_LIMITED),
        ("limite atteinte", KIND_RATE_LIMITED),
        ("Cloudflare 챌린지 통과 못함", KIND_CLOUDFLARE),
        ("Professional infrastructure detected", KIND_PROXY_BLOCKED),
        ("다운로드 폼을 찾을 수 없음", KIND_BLOCKED),
    ])
    def test_kind_routing(self, raw, expected_kind):
        assert classify_failure_text(raw) == expected_kind
        assert is_terminal_failure(raw) is False
        assert is_auth_required_failure(raw) is False

    def test_empty_error_text_is_unknown(self):
        assert classify_failure_text("") == KIND_UNKNOWN
        assert classify_failure_text(None) == KIND_UNKNOWN
        assert is_terminal_failure(None) is False


# ---------------------------------------------------------------------------
# apply_failure_to_request — attempts_json / next_retry_at 박는 흐름
# ---------------------------------------------------------------------------

class TestApplyFailure:
    def test_single_404_observation_is_transient_with_cooldown(self):
        req = _FakeReq()
        verdict = apply_failure_to_request(req, "파싱", "HTTP 404: Not Found")

        assert verdict.kind == KIND_TRANSIENT
        assert req.failure_kind == KIND_TRANSIENT
        assert req.attempt_count == 1
        assert req.next_retry_at is not None
        # 첫 실패는 30초 cooldown
        delta = (req.next_retry_at - datetime.datetime.now()).total_seconds()
        assert 25 <= delta <= 35

    def test_body_marker_dead_immediately_terminal(self):
        req = _FakeReq()
        verdict = apply_failure_to_request(
            req, "파싱", "1fichier 차단: 파일 삭제됨 (admin removed)"
        )
        assert verdict.kind == KIND_DEAD
        assert verdict.definitive is True
        assert req.failure_kind == KIND_DEAD
        assert req.next_retry_at is None  # 영구 박제

    def test_attempts_ringbuffer_truncates_to_5(self):
        req = _FakeReq()
        # 각 시도가 별개 관측 — 각기 다른 raw (dedup 가드 회피)
        for i in range(7):
            apply_failure_to_request(req, "다운로드", f"Read timeout #{i}")
        parsed = json.loads(req.attempts_json)
        assert len(parsed) == 5
        assert req.attempt_count == 7
        # 가장 최근 시도가 마지막
        assert "#6" in parsed[-1]["raw"]

    def test_transient_backoff_grows_with_attempts(self):
        req = _FakeReq()
        deltas = []
        # 각 시도가 별개 관측이도록 raw 를 살짝 다르게 — dedup 가드와 충돌 회피.
        for i in range(4):
            apply_failure_to_request(req, "다운로드", f"Read timeout (attempt {i})")
            deltas.append(
                (req.next_retry_at - datetime.datetime.now()).total_seconds()
            )
        # 30s → 120s → 480s → 1800s (잡음 허용)
        assert deltas[0] < deltas[1] < deltas[2] <= deltas[3]
        assert deltas[3] >= 1500

    def test_rate_limited_uses_extracted_wait_time(self):
        req = _FakeReq()
        apply_failure_to_request(
            req, "파싱", "You must wait 7 minutes before next download"
        )
        assert req.failure_kind == KIND_RATE_LIMITED
        delta = (req.next_retry_at - datetime.datetime.now()).total_seconds()
        # 420s + 60s 여유
        assert 460 <= delta <= 490

    def test_unknown_three_attempts_promotes_to_unknown_terminal(self):
        req = _FakeReq()
        # 각 시도가 별개 관측 — 각기 다른 raw (dedup 가드 회피)
        for i in range(3):
            apply_failure_to_request(req, "다운로드", f"weird_blob_v{i}")
        # 3회 누적되면 격리 — 더 이상 재시도 안 함
        assert req.failure_kind == "unknown_terminal"
        assert req.next_retry_at is None

    def test_duplicate_apply_within_window_is_a_noop(self):
        """핸들러 체인이 같은 raw 로 연속 두 번 호출해도 attempt_count/링버퍼
        한 번만 증가해야 한다. (운영 결함 #1 회귀 방지)"""
        req = _FakeReq()
        verdict1 = apply_failure_to_request(req, "다운로드", "Read timeout occurred")
        # 즉시 같은 raw 로 한 번 더 — 핸들러 chain re-raise 시나리오.
        verdict2 = apply_failure_to_request(req, "다운로드", "Read timeout occurred")

        assert req.attempt_count == 1  # +1 만 됐어야 함
        parsed = json.loads(req.attempts_json)
        assert len(parsed) == 1
        # verdict 자체는 같은 분류/같은 cooldown 으로 일관되게 반환
        assert verdict1.kind == verdict2.kind == KIND_TRANSIENT
        assert verdict2.attempt_count == 1

    def test_distinct_raw_within_window_still_increments(self):
        """같은 시간이라도 다른 raw 면 별개 시도로 누적."""
        req = _FakeReq()
        apply_failure_to_request(req, "다운로드", "Read timeout occurred")
        apply_failure_to_request(req, "다운로드", "Connection reset by peer")
        assert req.attempt_count == 2
        parsed = json.loads(req.attempts_json)
        assert len(parsed) == 2

    def test_duplicate_does_not_false_promote_to_dead(self):
        """가장 위험한 시나리오 — 단일 관측이 중복 호출로 두 번 push 되어
        ``recent[-2:]`` 가 같아지고 잘못된 dead 박제가 트리거되는 회귀."""
        req = _FakeReq()
        # 본문 마커가 들어간 케이스 — definitive=True 라 한 번이면 즉시 dead 박제 (정상).
        # 다음 호출은 dedup 으로 noop — false promotion 아님.
        apply_failure_to_request(req, "파싱", "1fichier 차단: 파일 삭제됨")
        apply_failure_to_request(req, "파싱", "1fichier 차단: 파일 삭제됨")
        assert req.attempt_count == 1
        assert req.failure_kind == KIND_DEAD


# ---------------------------------------------------------------------------
# is_retry_blocked_now — 컬럼 우선, 텍스트 폴백
# ---------------------------------------------------------------------------

class TestRetryGate:
    def test_dead_column_blocks(self):
        req = _FakeReq(failure_kind=KIND_DEAD)
        assert is_retry_blocked_now(req, has_credentials=True) == "dead"

    def test_auth_required_blocks_only_without_credentials(self):
        req = _FakeReq(failure_kind=KIND_AUTH_REQUIRED)
        assert is_retry_blocked_now(req, has_credentials=False) == "auth_required"
        assert is_retry_blocked_now(req, has_credentials=True) is None

    def test_cooldown_blocks_until_time(self):
        future = datetime.datetime.now() + datetime.timedelta(seconds=120)
        req = _FakeReq(failure_kind=KIND_TRANSIENT, next_retry_at=future)
        assert is_retry_blocked_now(req, has_credentials=True) == "cooldown"

    def test_past_cooldown_does_not_block(self):
        past = datetime.datetime.now() - datetime.timedelta(seconds=10)
        req = _FakeReq(failure_kind=KIND_TRANSIENT, next_retry_at=past)
        assert is_retry_blocked_now(req, has_credentials=True) is None

    def test_legacy_text_fallback_when_column_null(self):
        # 마이그레이션 이전 레코드 — failure_kind 비어있음. error 텍스트로 폴백.
        req = _FakeReq(error="1fichier 차단: 파일 삭제됨")
        assert is_retry_blocked_now(req, has_credentials=True) == "dead"

    def test_legacy_text_fallback_no_404_dead(self):
        # 핵심 회귀: 마이그레이션 이전 레코드의 단발 404 메시지가 더 이상 dead
        # 박제로 해석되면 안 된다. 사용자 시나리오: 박제됐던 항목이 시스템 업
        # 데이트 후 풀린다.
        req = _FakeReq(error="[파싱 실패] ... (페이지 로드 실패: HTTP 404)")
        assert is_retry_blocked_now(req, has_credentials=True) is None
