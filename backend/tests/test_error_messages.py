# -*- coding: utf-8 -*-
"""``core.error_messages.classify_error`` 테스트.

UI 에서 사용자가 어떤 단계에서 무엇이 잘못됐고 어떻게 조치해야 하는지를
즉시 알 수 있도록, 알려진 에러 패턴이 정확한 요약/조치 메시지로 매핑되어야
한다.
"""

import pytest

from core.error_messages import (
    classify_error,
    format_error,
    classify_failure_text,
    is_terminal_failure,
    is_auth_required_failure,
    KIND_DEAD,
    KIND_AUTH_REQUIRED,
    KIND_TRANSIENT,
    KIND_BLOCKED,
    KIND_UNKNOWN,
)


class TestClassify:
    @pytest.mark.parametrize(
        "raw,expected_kw_in_summary",
        [
            ("HTTP 404: Not Found", "만료"),
            ("HTTP 410: Gone", "만료"),
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
        assert result.action  # 조치 문구가 비어있지 않아야 함

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
        assert "만료" in formatted
        assert "HTTP 404: Not Found" in formatted
        assert "조치:" in formatted

    def test_format_error_with_none_raw(self):
        formatted = format_error("파싱", None)
        assert "[파싱 실패]" in formatted
        # 빈 문자열도 매칭되지 않으므로 fallback 분기 사용
        assert "재시도" in formatted

    def test_classify_includes_raw_message(self):
        result = classify_error("파싱", "HTTP 410: Gone")
        assert result.raw == "HTTP 410: Gone"
        assert result.stage == "파싱"


class TestKindClassification:
    """``kind`` 분류와 그에 기반한 헬퍼들이 일괄/단건 재시도 시 의미 없는 호출을
    어떻게 차단하는지 검증한다.
    """

    @pytest.mark.parametrize("raw", [
        "[파싱 실패] 다운로드 링크가 만료되었거나 파일이 삭제되었습니다 (페이지 로드 실패: HTTP 404)",
        "HTTP 410: Gone",
        "1fichier 차단: 파일 삭제됨 ...",
        "1fichier 차단: 파일이 신고되어 차단됨 ...",
        "1fichier 차단: 파일 없음",
    ])
    def test_dead_failures_are_terminal(self, raw):
        assert classify_failure_text(raw) == KIND_DEAD
        assert is_terminal_failure(raw) is True
        assert is_auth_required_failure(raw) is False

    def test_auth_required_classification(self):
        msg = "[다운로드 실패] 게스트 슬롯이 가득 (free guest slots full)"
        assert classify_failure_text(msg) == KIND_AUTH_REQUIRED
        assert is_auth_required_failure(msg) is True
        assert is_terminal_failure(msg) is False

    @pytest.mark.parametrize("raw,kind", [
        ("HTTP 503: Service Unavailable", KIND_TRANSIENT),
        ("Read timeout occurred", KIND_TRANSIENT),
        ("HTTP 429: Too Many Requests", KIND_BLOCKED),
        ("1fichier 차단: cloudflare 챌린지 실패", KIND_BLOCKED),
    ])
    def test_transient_and_blocked_are_not_terminal(self, raw, kind):
        assert classify_failure_text(raw) == kind
        assert is_terminal_failure(raw) is False
        assert is_auth_required_failure(raw) is False

    def test_empty_error_text_is_unknown(self):
        assert classify_failure_text("") == KIND_UNKNOWN
        assert classify_failure_text(None) == KIND_UNKNOWN
        assert is_terminal_failure(None) is False
