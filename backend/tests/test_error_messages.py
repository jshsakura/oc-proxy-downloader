# -*- coding: utf-8 -*-
"""``core.error_messages`` tests.

Core contracts:
- HTTP 404/410 alone is no longer dead but transient — only body markers
  (file deleted/reported/missing, file not found, etc.) are pinned as dead.
- ``apply_failure_to_request`` stamps the classification, attempts, and
  next_retry_at onto the request object in one pass.
- ``is_retry_blocked_now`` prefers the new columns, falling back to text when
  the columns are empty.
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
    """A fake object that mimics only the setattr interface of DownloadRequest."""

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
# classify_error / format_error — stage / summary / action messages
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
# kind classification — dead pinning only on body markers, HTTP codes are transient
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
        # Core regression guard: a one-off 404/410 alone must not pin as dead.
        kind = classify_failure_text(raw)
        assert kind != KIND_DEAD
        assert is_terminal_failure(raw) is False

    def test_auth_required_classification(self):
        msg = "[다운로드 실패] 게스트 슬롯이 가득 ..."
        assert classify_failure_text(msg) == KIND_AUTH_REQUIRED
        assert is_auth_required_failure(msg) is True
        assert is_terminal_failure(msg) is False

    @pytest.mark.parametrize("raw,expected_kind", [
        ("MegaUp 파일 없음 또는 삭제됨", KIND_DEAD),
        ("DataNodes 파일 없음 또는 삭제됨", KIND_DEAD),
        ("Rapidgator 무료 모드는 500 MB 초과 파일 다운로드 불가", KIND_AUTH_REQUIRED),
        ("Gofile은 콘텐츠 권한 또는 프리미엄 정책에 따라 API 토큰이 필요", KIND_AUTH_REQUIRED),
        ("Gofile 목록 조회 차단 (데이터센터 IP) — 가정용 IP/NAS에서 실행 시 정상 동작", KIND_PROXY_BLOCKED),
        ("Gofile 파일 없음 또는 삭제됨", KIND_DEAD),
        ("Send.now는 Cloudflare 챌린지로 인해 브라우저 세션 없이 자동 다운로드를 지원하지 않음", KIND_CLOUDFLARE),
        ("Send.now Turnstile 검증 필요", KIND_CLOUDFLARE),
        ("호스팅 최종 링크가 파일 대신 HTML/보안 확인 페이지를 반환함", KIND_CLOUDFLARE),
    ])
    def test_other_hoster_constraints_are_classified(self, raw, expected_kind):
        assert classify_failure_text(raw) == expected_kind

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
# apply_failure_to_request — the flow that stamps attempts_json / next_retry_at
# ---------------------------------------------------------------------------

class TestApplyFailure:
    def test_single_404_observation_is_transient_with_cooldown(self):
        req = _FakeReq()
        verdict = apply_failure_to_request(req, "파싱", "HTTP 404: Not Found")

        assert verdict.kind == KIND_TRANSIENT
        assert req.failure_kind == KIND_TRANSIENT
        assert req.attempt_count == 1
        assert req.next_retry_at is not None
        # The first failure has a 30-second cooldown
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
        assert req.next_retry_at is None  # permanently pinned

    def test_attempts_ringbuffer_truncates_to_5(self):
        req = _FakeReq()
        # Each attempt is a distinct observation — different raw each time (avoids the dedup guard)
        for i in range(7):
            apply_failure_to_request(req, "다운로드", f"Read timeout #{i}")
        parsed = json.loads(req.attempts_json)
        assert len(parsed) == 5
        assert req.attempt_count == 7
        # The most recent attempt is last
        assert "#6" in parsed[-1]["raw"]

    def test_transient_backoff_grows_with_attempts(self):
        req = _FakeReq()
        deltas = []
        # Vary raw slightly so each attempt is a distinct observation — avoids colliding with the dedup guard.
        for i in range(4):
            apply_failure_to_request(req, "다운로드", f"Read timeout (attempt {i})")
            deltas.append(
                (req.next_retry_at - datetime.datetime.now()).total_seconds()
            )
        # 30s → 120s → 480s → 1800s (noise tolerated)
        assert deltas[0] < deltas[1] < deltas[2] <= deltas[3]
        assert deltas[3] >= 1500

    def test_rate_limited_uses_extracted_wait_time(self):
        req = _FakeReq()
        apply_failure_to_request(
            req, "파싱", "You must wait 7 minutes before next download"
        )
        assert req.failure_kind == KIND_RATE_LIMITED
        delta = (req.next_retry_at - datetime.datetime.now()).total_seconds()
        # 420s + 60s margin
        assert 460 <= delta <= 490

    def test_unknown_three_attempts_promotes_to_unknown_terminal(self):
        req = _FakeReq()
        # Each attempt is a distinct observation — different raw each time (avoids the dedup guard)
        for i in range(3):
            apply_failure_to_request(req, "다운로드", f"weird_blob_v{i}")
        # After 3 accumulated attempts, quarantine — no more retries
        assert req.failure_kind == "unknown_terminal"
        assert req.next_retry_at is None

    def test_duplicate_apply_within_window_is_a_noop(self):
        """Even if the handler chain calls twice in a row with the same raw, the
        attempt_count/ring buffer must increase only once. (Guards against operational defect #1.)"""
        req = _FakeReq()
        verdict1 = apply_failure_to_request(req, "다운로드", "Read timeout occurred")
        # Immediately again with the same raw — the handler-chain re-raise scenario.
        verdict2 = apply_failure_to_request(req, "다운로드", "Read timeout occurred")

        assert req.attempt_count == 1  # should have incremented by +1 only
        parsed = json.loads(req.attempts_json)
        assert len(parsed) == 1
        # The verdict itself is returned consistently with the same classification/cooldown
        assert verdict1.kind == verdict2.kind == KIND_TRANSIENT
        assert verdict2.attempt_count == 1

    def test_distinct_raw_within_window_still_increments(self):
        """Even at the same time, a different raw accumulates as a separate attempt."""
        req = _FakeReq()
        apply_failure_to_request(req, "다운로드", "Read timeout occurred")
        apply_failure_to_request(req, "다운로드", "Connection reset by peer")
        assert req.attempt_count == 2
        parsed = json.loads(req.attempts_json)
        assert len(parsed) == 2

    def test_duplicate_does_not_false_promote_to_dead(self):
        """The most dangerous scenario — a single observation pushed twice via a
        duplicate call makes ``recent[-2:]`` equal and triggers a wrong dead pin (regression)."""
        req = _FakeReq()
        # A case with a body marker — definitive=True, so one call pins as dead immediately (correct).
        # The next call is a noop via dedup — not a false promotion.
        apply_failure_to_request(req, "파싱", "1fichier 차단: 파일 삭제됨")
        apply_failure_to_request(req, "파싱", "1fichier 차단: 파일 삭제됨")
        assert req.attempt_count == 1
        assert req.failure_kind == KIND_DEAD


# ---------------------------------------------------------------------------
# is_retry_blocked_now — columns first, text fallback
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
        # Pre-migration record — failure_kind is empty. Fall back to the error text.
        req = _FakeReq(error="1fichier 차단: 파일 삭제됨")
        assert is_retry_blocked_now(req, has_credentials=True) == "dead"

    def test_legacy_text_fallback_no_404_dead(self):
        # Core regression: a pre-migration record's one-off 404 message must no
        # longer be interpreted as a dead pin. User scenario: a previously pinned
        # item is released after a system update.
        req = _FakeReq(error="[파싱 실패] ... (페이지 로드 실패: HTTP 404)")
        assert is_retry_blocked_now(req, has_credentials=True) is None


class TestRateLimitRealWait:
    """The 1fichier '대기시간이 너무 깁니다' failure must carry the *real* wait
    time so next_retry_at reflects when the quota actually unlocks (not a flat
    10-min default). Regression for the 'don't know when it clears' issue."""

    def test_long_wait_message_yields_rate_limited_with_real_retry_after(self):
        msg = "1fichier 대기시간이 너무 깁니다 — 무료 다운로드 한도 (you must wait 240 minutes)"
        c = classify_error("파싱", msg)
        assert c.kind == KIND_RATE_LIMITED
        assert c.retry_after_seconds == 240 * 60

    def test_next_retry_at_matches_stated_wait(self):
        future = datetime.datetime.now() + datetime.timedelta(minutes=240)
        req = _FakeReq()
        verdict = apply_failure_to_request(
            req, "파싱",
            "1fichier 대기시간이 너무 깁니다 — 무료 다운로드 한도 (you must wait 240 minutes)",
        )
        assert verdict.kind == KIND_RATE_LIMITED
        # next_retry_at ~ now + 240min (+60s margin), well beyond the old 10-min default
        assert req.next_retry_at is not None
        delta = (req.next_retry_at - datetime.datetime.now()).total_seconds()
        assert 240 * 60 <= delta <= 240 * 60 + 120
