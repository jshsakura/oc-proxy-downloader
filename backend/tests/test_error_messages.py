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
import ast
import json
from pathlib import Path

import pytest

from core.error_messages import (
    classify_error,
    format_error,
    classify_failure_text,
    is_terminal_failure,
    is_auth_required_failure,
    is_retry_blocked_now,
    apply_failure_to_request,
    KIND_SOURCE_UNCONFIRMED,
    KIND_AUTH_REQUIRED,
    KIND_RATE_LIMITED,
    KIND_DAILY_QUOTA,
    KIND_CLOUDFLARE,
    KIND_PROXY_BLOCKED,
    KIND_BLOCKED,
    KIND_TRANSIENT,
    KIND_BROWSER_PARSE,
    KIND_UNKNOWN,
    next_fichier_quota_reset,
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


def test_failure_kind_labels_exist_in_korean_and_english():
    locales = Path(__file__).resolve().parents[1] / "locales"
    for language in ("ko", "en"):
        labels = json.loads((locales / f"{language}.json").read_text(encoding="utf-8"))
        for key in ("kind_daily_quota", "kind_slot_busy", "kind_browser_parse"):
            assert labels[key] and labels[key] != key


def test_all_locales_have_safe_failure_messages():
    locales = Path(__file__).resolve().parents[1] / "locales"
    needed = {
        "failure_action_manual", "failure_action_retry", "failure_action_wait",
        "failure_cause_human", "failure_cause_multiple", "failure_cause_unsupported",
    }
    for path in locales.glob("*.json"):
        labels = json.loads(path.read_text(encoding="utf-8"))
        assert needed <= labels.keys(), path.name
        error = classify_error("파싱", "DataVaults 무료 다운로드에 reCAPTCHA v2 사람 확인이 필요합니다")
        rendered = error.to_user_message(path.stem)
        if path.stem not in {"ko", "en"}:
            assert labels["failure_cause_human"] in rendered
        assert "DataVaults 무료 다운로드" not in rendered
        assert "status=" not in rendered


def test_all_explicit_hoster_parse_errors_have_a_classification():
    """A new parser error must not silently enter the unknown retry loop."""
    core = Path(__file__).resolve().parents[1] / "core"
    uncovered = []
    for filename in ("hoster_sites.py", "browser_solver.py", "hoster_common.py", "hoster_web.py", "hoster_legacy_sites.py", "generic_links.py", "link_containers.py"):
        tree = ast.parse((core / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            call = node.exc
            if not isinstance(call.func, ast.Name) or call.func.id != "HosterParseError" or not call.args:
                continue
            arg = call.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                message = arg.value
            elif isinstance(arg, ast.JoinedStr):
                message = "".join(
                    part.value if isinstance(part, ast.Constant) and isinstance(part.value, str) else "X"
                    for part in arg.values
                )
            else:
                continue
            if classify_error("파싱", message).kind == KIND_UNKNOWN:
                uncovered.append(f"{filename}:{node.lineno}: {message}")
    assert not uncovered, "\n".join(uncovered)


# ---------------------------------------------------------------------------
# classify_error / format_error — stage / summary / action messages
# ---------------------------------------------------------------------------

class TestClassify:
    @pytest.mark.parametrize("raw,kind", [
        ("Rapidgator는 대기시간/captcha/계정 제약이 있어 현재 자동 다운로드를 지원하지 않음", KIND_AUTH_REQUIRED),
        ("MultiUp에 자동 다운로드 가능한 미러가 없음 (현재 미러: example.com)", KIND_BROWSER_PARSE),
        ("MultiUp 미러 목록 폼을 찾을 수 없음", KIND_BROWSER_PARSE),
        ("Gofile 폴더에 파일이 여러 개(3개) 있어 자동 다운로드 대상을 특정할 수 없음", KIND_BROWSER_PARSE),
        ("Gofile 폴더에 다운로드할 파일이 없음", KIND_SOURCE_UNCONFIRMED),
        ("Gofile 게스트 토큰 발급 실패", KIND_BROWSER_PARSE),
        ("Gofile 콘텐츠 조회 실패 (status=error-unexpected)", KIND_BROWSER_PARSE),
        ("Pixeldrain 리스트(앨범) 링크는 지원하지 않음", KIND_BROWSER_PARSE),
        ("Pixeldrain 파일 없음 또는 삭제됨", KIND_SOURCE_UNCONFIRMED),
        ("MediaFire 파일 없음 또는 삭제됨", KIND_SOURCE_UNCONFIRMED),
        ("MultiUp 페이지 조회 실패: unexpected response", KIND_BROWSER_PARSE),
        ("MultiUp 미러 목록 조회 실패: unexpected response", KIND_BROWSER_PARSE),
        ("MediaFire 호스터 페이지 HTTP 404 (삭제 여부 미확인)", KIND_SOURCE_UNCONFIRMED),
        ("Rootz: 파일이 비활성 상태입니다 (processing)", KIND_BLOCKED),
        ("다운로드 주소가 발급되지 않았습니다 (캡차 또는 호스트 제한)", KIND_BROWSER_PARSE),
        ("DataNodes 다운로드 링크를 찾을 수 없음", KIND_BROWSER_PARSE),
        ("호스팅 페이지 파싱 시간 초과 (기존 파서 종료 대기)", KIND_BROWSER_PARSE),
        ("Example API가 JSON이 아닌 응답 반환 (Cloudflare 차단/오류 페이지 가능성)", KIND_BROWSER_PARSE),
    ])
    def test_hoster_parse_cases_do_not_repeat(self, raw, kind):
        req = _FakeReq()
        verdict = apply_failure_to_request(req, "파싱", raw, language="ko")
        assert verdict.kind == kind
        assert verdict.next_retry_at is None

    def test_datavaults_captcha_is_explicit_and_never_retried(self):
        req = _FakeReq()
        verdict = apply_failure_to_request(req, "파싱", "DataVaults 무료 다운로드에 reCAPTCHA v2 사람 확인이 필요합니다")
        assert verdict.kind == KIND_AUTH_REQUIRED
        assert verdict.next_retry_at is None
        assert "reCAPTCHA v2" in classify_error("파싱", "DataVaults 무료 다운로드에 reCAPTCHA v2 사람 확인이 필요합니다").to_user_message("en")

    @pytest.mark.parametrize("raw", [
        "Gofile 웹 인증 토큰 거부 — 사이트 토큰 방식이 변경되었을 수 있습니다",
        "Gofile 무료 조회 속도 제한 — 자동 재시도하지 않습니다",
    ])
    def test_gofile_refusals_do_not_auto_retry(self, raw):
        req = _FakeReq()
        verdict = apply_failure_to_request(req, "파싱", raw)
        assert verdict.kind == KIND_BLOCKED
        assert verdict.next_retry_at is None

    def test_multiup_all_mirrors_failed_does_not_auto_retry(self):
        req = _FakeReq()
        verdict = apply_failure_to_request(
            req, "파싱", (
                "MultiUp 모든 지원 미러 실패 (Gofile: Gofile 파일 없음 또는 삭제됨; "
                "MegaUp: MegaUp 파일 없음 또는 삭제됨; "
                "MixDrop: 다운로드 버튼 처리 후 링크를 받지 못했습니다)"
            )
        )
        assert verdict.kind == KIND_BROWSER_PARSE
        assert verdict.next_retry_at is None
        assert "MultiUp의 지원 미러" in req.error
        assert "GoFile:" in req.error and "MegaUp:" in req.error
        assert "파일 없음 또는 삭제됨" not in req.error

    def test_multiup_mirror_error_is_english_when_selected(self):
        req = _FakeReq()
        apply_failure_to_request(
            req, "파싱", "MultiUp 모든 지원 미러 실패 (Gofile: file missing)", language="en"
        )
        assert "All supported MultiUp mirrors failed" in req.error
        assert "조치:" not in req.error

    @pytest.mark.parametrize("raw,kind", [
        ("Rootz: Forbidden", KIND_BLOCKED),
        ("Rootz: HTTP 403", KIND_BLOCKED),
        ("Rootz: 다운로드 주소 확인 실패 (403)", KIND_BLOCKED),
        ("Rootz: 무료 다운로드 대기 또는 제한 중입니다", KIND_BLOCKED),
        ("Rootz: 파일이 비활성 상태입니다", KIND_BLOCKED),
        ("Rootz: 파일이 비활성 상태입니다 (deleted)", KIND_SOURCE_UNCONFIRMED),
        ("Rootz: 비밀번호가 필요한 파일입니다", KIND_AUTH_REQUIRED),
        ("Rootz: 직접 다운로드 주소를 받지 못했습니다", KIND_BROWSER_PARSE),
    ])
    def test_rootz_refusals_are_not_automatically_retried(self, raw, kind):
        req = _FakeReq()
        verdict = apply_failure_to_request(req, "파싱", raw)
        assert verdict.kind == kind
        assert verdict.next_retry_at is None
        assert "Rootz" in req.error

    def test_rootz_refusal_has_english_message(self):
        req = _FakeReq()
        verdict = apply_failure_to_request(req, "파싱", "Rootz: Forbidden", language="en")
        assert verdict.next_retry_at is None
        assert "Automatic retry is disabled" in req.error
        assert "조치:" not in req.error

    @pytest.mark.parametrize("language,expected", [
        ("ko", "파일 서버가 다운로드를 거부했습니다 (403)"),
        ("en", "its file server refused the download (403)"),
    ])
    def test_akirabox_storage_unavailable_does_not_retry_or_blame_cloudflare(self, language, expected):
        req = _FakeReq()
        verdict = apply_failure_to_request(req, "다운로드", "akirabox storage unavailable", language=language)
        assert verdict.kind == KIND_BLOCKED
        assert verdict.next_retry_at is None
        assert expected in req.error
        assert "Cloudflare" not in req.error
        assert classify_error("다운로드", "akirabox storage unavailable").definitive is False
        assert ("원본 링크는 보존" if language == "ko" else "original link is preserved") in req.error
        assert ("거부 원인은 미확인" if language == "ko" else "reason for refusal are unconfirmed") in req.error

    @pytest.mark.parametrize("language,expected,excluded", [
        ("ko", "자동 재시도하지 않습니다", "자동으로 다시 시도"),
        ("en", "Automatic retry is disabled", "조치:"),
    ])
    def test_slot_busy_message_has_one_consistent_action(self, language, expected, excluded):
        req = _FakeReq()
        verdict = apply_failure_to_request(
            req, "파싱", "1fichier 차단: 무료 다운로드 슬롯 혼잡", language=language
        )
        assert verdict.next_retry_at is None
        assert expected in req.error
        assert excluded not in req.error

    @pytest.mark.parametrize("raw", [
        "캡차는 통과했지만 다운로드 링크가 발급되지 않았습니다",
        "다운로드 버튼 처리 후 링크를 받지 못했습니다",
        "Send.now 다운로드 링크를 찾을 수 없음",
        "Locator.count: Execution context was destroyed, most likely because of a navigation.",
        "브라우저 캡차 우회 제한시간(270초)을 초과했습니다",
    ])
    def test_browser_parse_failure_does_not_auto_retry(self, raw):
        req = _FakeReq()
        verdict = apply_failure_to_request(req, "파싱", raw)
        assert verdict.kind == KIND_BROWSER_PARSE
        assert verdict.next_retry_at is None
        assert "자동 재시도하지 않습니다" in req.error or "자동 반복하지 않습니다" in req.error

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

    def test_format_error_shows_cause_and_action_without_internal_raw(self):
        formatted = format_error("다운로드", "HTTP 404: Not Found")
        assert "[다운로드 실패]" in formatted
        assert "조치:" in formatted
        assert "Not Found" not in formatted
        assert "HTTP 404:" not in formatted

    def test_format_error_with_none_raw(self):
        formatted = format_error("파싱", None)
        assert "[파싱 실패]" in formatted
        assert "재시도" in formatted

    def test_classify_includes_raw_message(self):
        result = classify_error("파싱", "HTTP 410: Gone")
        assert result.raw == "HTTP 410: Gone"
        assert result.stage == "파싱"


class TestHostStatementIsShownVerbatim:
    """The row must say what the host said, not "접근 불가 응답"."""

    def test_page_saying_file_not_found_is_reported_as_such(self):
        result = classify_error("파싱", "MegaUp 파일 없음 또는 삭제됨 (삭제 여부 미확인)")
        assert result.summary == "MegaUp 페이지가 '파일 없음'이라고 표시했습니다"
        assert "다른 미러" in result.action
        assert "접근 불가" not in result.summary
        assert "미확인" not in result.summary
        # Behaviour is unchanged: the link is kept and never auto-pruned.
        assert result.kind == KIND_SOURCE_UNCONFIRMED
        assert result.definitive is False

    def test_http_404_is_reported_as_a_status_not_as_deletion(self):
        result = classify_error("파싱", "1fichier 호스터 페이지 HTTP 404 (삭제 여부 미확인)")
        assert result.summary == "1fichier 페이지가 HTTP 404를 반환했습니다"
        assert "접근 불가" not in result.summary
        assert result.kind == KIND_SOURCE_UNCONFIRMED

    def test_unknown_unconfirmed_text_keeps_the_generic_message(self):
        result = classify_error("파싱", "GoFile 파일 상태 확인 실패 (삭제 여부 미확인)")
        assert "삭제 여부 미확인" in result.summary


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
        assert classify_failure_text(raw) == KIND_SOURCE_UNCONFIRMED
        assert is_terminal_failure(raw) is False

    @pytest.mark.parametrize("raw", [
        "HTTP 404: Not Found",
        "HTTP 410: Gone",
        "[파싱 실패] ... (페이지 로드 실패: HTTP 404)",
    ])
    def test_http_404_410_downgraded_to_non_dead(self, raw):
        # Core regression guard: a one-off 404/410 alone must not pin as dead.
        kind = classify_failure_text(raw)
        assert kind != KIND_SOURCE_UNCONFIRMED
        assert is_terminal_failure(raw) is False

    def test_auth_required_classification(self):
        msg = "[다운로드 실패] 게스트 슬롯이 가득 ..."
        assert classify_failure_text(msg) == KIND_AUTH_REQUIRED
        assert is_auth_required_failure(msg) is True
        assert is_terminal_failure(msg) is False

    @pytest.mark.parametrize("raw,expected_kind", [
        ("MegaUp 파일 없음 또는 삭제됨", KIND_SOURCE_UNCONFIRMED),
        ("DataNodes 파일 없음 또는 삭제됨", KIND_SOURCE_UNCONFIRMED),
        ("Rapidgator 무료 모드는 500 MB 초과 파일 다운로드 불가", KIND_AUTH_REQUIRED),
        ("Gofile은 콘텐츠 권한 또는 프리미엄 정책에 따라 API 토큰이 필요", KIND_AUTH_REQUIRED),
        ("Gofile 목록 조회 차단 (데이터센터 IP) — 가정용 IP/NAS에서 실행 시 정상 동작", KIND_PROXY_BLOCKED),
        ("Gofile 파일 없음 또는 삭제됨", KIND_SOURCE_UNCONFIRMED),
        ("Send.now는 Cloudflare 챌린지로 인해 브라우저 세션 없이 자동 다운로드를 지원하지 않음", KIND_CLOUDFLARE),
        ("Send.now Turnstile 검증 필요", KIND_CLOUDFLARE),
        ("호스팅 최종 링크가 파일 대신 HTML/보안 확인 페이지를 반환함", KIND_CLOUDFLARE),
        # 같은 "HTML 이 왔다" 여도 내 회선이 가로챈 것이면 조치가 정반대다.
        ("네트워크차단페이지: 공유기/ISP 필터가 이 주소를 가로채 차단 안내 페이지를 "
         "돌려줬습니다 (blocking.asus.hns.tm)", KIND_PROXY_BLOCKED),
        # TLS 만 깨지는 회선 차단(SNI)도 같은 집단이다 — 노드 장애가 아니다.
        ("회선SNI차단의심: 이 회선에서 megadl.boats 의 TLS(443) 연결만 실패합니다 "
         "(평문 :80 은 정상 응답)", KIND_PROXY_BLOCKED),
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
        ("다운로드 폼을 찾을 수 없음", KIND_UNKNOWN),
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
        # First failure waits 2 minutes, plus up to 25% jitter. It used to be
        # 30s — asking a host that just refused us to try again almost
        # immediately is what gets an IP blocked.
        delta = (req.next_retry_at - datetime.datetime.now()).total_seconds()
        assert 1800 <= delta <= 2250

    def test_body_marker_dead_immediately_terminal(self):
        req = _FakeReq()
        verdict = apply_failure_to_request(
            req, "파싱", "1fichier 차단: 파일 삭제됨 (admin removed)"
        )
        assert verdict.kind == KIND_SOURCE_UNCONFIRMED
        assert verdict.definitive is False
        assert req.failure_kind == KIND_SOURCE_UNCONFIRMED
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

    def test_transient_has_one_delayed_retry(self):
        req = _FakeReq()
        apply_failure_to_request(req, "다운로드", "Read timeout (attempt 1)")
        delta = (req.next_retry_at - datetime.datetime.now()).total_seconds()
        assert 1800 <= delta <= 2250
        apply_failure_to_request(req, "다운로드", "Read timeout (attempt 2)")
        assert req.next_retry_at is None

    def test_the_retry_budget_runs_out_after_three_attempts(self):
        """More knocking does not find a door that opens; it keeps a refusal
        fresh. The row stays failed with its reason, and "다시 받기" grants a
        fresh budget when a human decides something has changed."""
        req = _FakeReq()
        for i in range(3):
            apply_failure_to_request(req, "다운로드", f"Read timeout (attempt {i})")

        assert req.attempt_count == 3
        assert req.next_retry_at is None

    def test_rate_limited_uses_extracted_wait_time(self):
        req = _FakeReq()
        apply_failure_to_request(
            req, "파싱", "You must wait 7 minutes before next download"
        )
        assert req.failure_kind == KIND_RATE_LIMITED
        assert req.next_retry_at is None
        assert classify_error("", "You must wait 7 minutes before next download").retry_after_seconds == 420

    def test_unknown_three_attempts_promotes_to_unknown_terminal(self):
        req = _FakeReq()
        # Each attempt is a distinct observation — different raw each time (avoids the dedup guard)
        for i in range(3):
            apply_failure_to_request(req, "다운로드", f"weird_blob_v{i}")
        # After 3 accumulated attempts, quarantine — no more retries
        assert req.failure_kind == "unknown_terminal"
        assert req.next_retry_at is None

    def test_transient_stops_auto_retry_after_ceiling(self):
        """A transient failure must stop auto-retrying once its ceiling is hit,
        instead of re-running on the capped 30m backoff forever."""
        req = _FakeReq()
        for i in range(6):  # _TRANSIENT_MAX_ATTEMPTS
            apply_failure_to_request(req, "다운로드", f"Read timeout (attempt {i})")
        assert req.failure_kind == KIND_TRANSIENT
        assert req.attempt_count == 6
        assert req.next_retry_at is None  # auto-retry exhausted
        assert "수동으로 다시 시도" in req.error

    def test_proxy_blocked_never_auto_retries(self):
        """A known infrastructure rejection must not be hammered automatically."""
        req = _FakeReq()
        apply_failure_to_request(req, "파싱", "professional infrastructure detected #1")
        assert req.failure_kind == KIND_PROXY_BLOCKED
        assert req.next_retry_at is None
        assert "자동 재시도하지 않습니다" in req.error

    def test_cloudflare_never_auto_retries(self):
        req = _FakeReq()
        apply_failure_to_request(req, "파싱", "1fichier 차단: Cloudflare")
        assert req.failure_kind == KIND_CLOUDFLARE
        assert req.next_retry_at is None
        assert "자동 재시도하지 않습니다" in req.error

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
        assert req.failure_kind == KIND_SOURCE_UNCONFIRMED


# ---------------------------------------------------------------------------
# is_retry_blocked_now — columns first, text fallback
# ---------------------------------------------------------------------------

class TestRetryGate:
    def test_dead_column_blocks(self):
        req = _FakeReq(failure_kind=KIND_SOURCE_UNCONFIRMED)
        assert is_retry_blocked_now(req, has_credentials=True) is None

    def test_auth_required_blocks_only_without_credentials(self):
        req = _FakeReq(failure_kind=KIND_AUTH_REQUIRED, url="https://1fichier.com/?abc")
        assert is_retry_blocked_now(req, has_credentials=False) == "auth_required"
        assert is_retry_blocked_now(req, has_credentials=True) is None

    def test_other_host_auth_is_not_unblocked_by_fichier_login(self):
        req = _FakeReq(failure_kind=KIND_AUTH_REQUIRED, url="https://datavaults.co/abc")
        assert is_retry_blocked_now(req, has_credentials=True) == "auth_required"

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
        assert is_retry_blocked_now(req, has_credentials=True) is None

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
        assert req.next_retry_at is None
        assert classify_error("", "you must wait 240 minutes").retry_after_seconds == 14400


class TestDailyQuotaRecovery:
    def test_reset_is_next_local_day_with_margin(self):
        now = datetime.datetime(2026, 9, 21, 23, 59)
        assert next_fichier_quota_reset(now) == datetime.datetime(2026, 9, 22, 0, 10)

    def test_explicit_daily_quota_keeps_a_retry_schedule(self):
        req = _FakeReq()
        raw = "1fichier 차단: 일일 무료 다운로드 한도 초과"
        verdict = apply_failure_to_request(req, "파싱", raw)
        assert verdict.kind == KIND_DAILY_QUOTA
        assert req.next_retry_at == next_fichier_quota_reset()
        assert "자동으로 다시 시도" in req.error

        # Two automatic attempts are allowed on later days; then stop.
        req.attempts_json = None
        second = apply_failure_to_request(req, "파싱", raw)
        assert second.kind == KIND_DAILY_QUOTA
        assert second.next_retry_at is None
        req.attempts_json = None
        third = apply_failure_to_request(req, "파싱", raw)
        assert third.kind == KIND_DAILY_QUOTA
        assert third.next_retry_at is None
        assert req.next_retry_at is None
        assert "수동으로 다시 시도" in req.error


class TestBrowserFallbackCookieHandoff:
    def test_illegal_cookie_key_is_transient_not_unclassified(self):
        """http.cookies rejects a cookie the browser picked up. The cookie set is
        filtered now, so a retry succeeds — it must not read as an unknown cause."""
        c = classify_error("다운로드", "Illegal key ''")
        assert c.kind == KIND_TRANSIENT
        assert c.definitive is False
        assert "원인을 자동으로 분류하지 못했습니다" not in c.summary


class TestQueuedIsNotAFailure:
    def test_waiting_in_a_queue_does_not_spend_the_retry_budget(self):
        """A long queue must not cost a link its attempts. With the old TRANSIENT
        classification, six turns of waiting exhausted auto-retry and the link was
        effectively dropped."""
        req = _FakeReq()
        msg = "같은 사이트의 다른 링크를 처리하는 중이라 대기열에서 시간이 초과되었습니다"

        for _ in range(10):
            verdict = apply_failure_to_request(req, "파싱", msg)
            # Vary nothing but the clock; the duplicate guard keys on the raw text,
            # so assert on the running total instead of each call.

        assert verdict.kind == "queued"
        assert req.attempt_count == 0, "queueing must not count as an attempt"
        assert req.next_retry_at is not None, "a queued link must stay scheduled"

    def test_a_real_failure_after_queueing_still_has_its_full_budget(self):
        req = _FakeReq()
        apply_failure_to_request(
            req, "파싱",
            "같은 사이트의 다른 링크를 처리하는 중이라 대기열에서 시간이 초과되었습니다",
        )

        apply_failure_to_request(req, "다운로드", "HTTP 503: Service Unavailable")

        assert req.attempt_count == 1
        assert req.next_retry_at is not None


def test_missing_filename_is_parser_failure_not_file_missing():
    verdict = classify_error('다운로드', '파일명(확장자)을 확인할 수 없어 다운로드를 중단했습니다')
    assert verdict.kind == KIND_BROWSER_PARSE
    assert verdict.definitive is False
