# -*- coding: utf-8 -*-
"""``core.error_messages.classify_error`` 테스트.

UI 에서 사용자가 어떤 단계에서 무엇이 잘못됐고 어떻게 조치해야 하는지를
즉시 알 수 있도록, 알려진 에러 패턴이 정확한 요약/조치 메시지로 매핑되어야
한다.
"""

import pytest

from core.error_messages import classify_error, format_error


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
