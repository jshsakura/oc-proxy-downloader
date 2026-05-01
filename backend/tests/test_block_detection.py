# -*- coding: utf-8 -*-
"""1fichier 의 VPS/VPN/파일삭제 등 명시적 차단 응답 감지 테스트.

1fichier 는 status 200 으로 응답하면서도 본문에서 차단을 알리는
경우가 많아, 폼 누락만 보고 ``다운로드 폼을 찾을 수 없음`` 으로
끝나면 사용자가 진짜 원인을 알 수 없다.
"""

from unittest.mock import MagicMock

import pytest

from core import simple_parser as sp
from core.error_messages import classify_error


VPN_BLOCK_HTML = """
<html><body>
IP Address 1.2.3.4 : Accès restreint – professional infrastructure detected.
This IP address has been identified as belonging to a server, proxy, VPN, relay network, or associated with abusive activity.
</body></html>
"""

DELETED_HTML = """<html><body>The file has been deleted.</body></html>"""

REPORTED_HTML = """<html><body>This file has been reported and removed.</body></html>"""

CLOUDFLARE_HTML = """<html><head><title>Attention Required! | Cloudflare</title></head><body>...</body></html>"""

NORMAL_HTML = """
<html><body>
<form id="f1"><input type="hidden" name="adz" value="x"></form>
<script>var ct = 60;</script>
</body></html>
"""


class TestDetectBlockReason:
    def test_vpn_block(self):
        assert "VPS/VPN" in sp.detect_block_reason(VPN_BLOCK_HTML)

    def test_french_vpn_block_phrase(self):
        # "Accès restreint" 자체로도 잡혀야 함
        html = "<html><body>Accès restreint pour cette IP.</body></html>"
        assert "VPS/VPN" in sp.detect_block_reason(html)

    def test_deleted_file(self):
        assert "삭제" in sp.detect_block_reason(DELETED_HTML)

    def test_reported_file(self):
        assert "신고" in sp.detect_block_reason(REPORTED_HTML)

    def test_cloudflare_challenge(self):
        assert "Cloudflare" in sp.detect_block_reason(CLOUDFLARE_HTML)

    def test_wait_message_is_not_block(self):
        # "you must wait" 는 정상 흐름이므로 차단으로 잡으면 안 된다.
        html = "<html><body>You must wait 5 minutes before download.</body></html>"
        # 매칭 결과가 None 이거나 None-시그널이어야 함 (파일 없음 등 다른 키워드 매칭 X)
        assert sp.detect_block_reason(html) is None

    def test_normal_page_returns_none(self):
        assert sp.detect_block_reason(NORMAL_HTML) is None

    def test_empty_input(self):
        assert sp.detect_block_reason("") is None
        assert sp.detect_block_reason(None) is None


class TestParseRaisesOnBlock:
    def test_parse_simple_sync_raises_on_vpn_block(self, monkeypatch):
        """200 응답이지만 본문에 VPN 차단 메시지가 있으면 명확한 예외로 빠진다."""
        response = MagicMock()
        response.status_code = 200
        response.text = VPN_BLOCK_HTML
        response.headers = {}

        scraper = MagicMock()
        scraper.cookies = []
        scraper.get.return_value = response

        monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)

        with pytest.raises(Exception) as excinfo:
            sp.parse_1fichier_simple_sync("https://1fichier.com/?abc")

        assert "1fichier 차단" in str(excinfo.value)
        assert "VPS/VPN" in str(excinfo.value)

    def test_preparse_returns_none_on_block(self, monkeypatch):
        response = MagicMock()
        response.status_code = 200
        response.text = VPN_BLOCK_HTML
        response.headers = {}

        scraper = MagicMock()
        scraper.cookies = []
        scraper.get.return_value = response
        monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)

        # preparse 는 raise 하지 않고 None 반환 (본 파싱에서 raise 됨)
        assert sp.preparse_1fichier_standalone("https://1fichier.com/?abc") is None


class TestErrorMessageClassification:
    def test_vpn_block_classified_with_concrete_action(self):
        c = classify_error("파싱", "1fichier 차단: VPS/VPN IP 차단")
        assert "VPS/VPN" in c.summary
        assert "주거용" in c.action or "프록시" in c.action

    def test_deleted_file_classified(self):
        c = classify_error("파싱", "1fichier 차단: 파일 삭제됨")
        assert "삭제" in c.summary
        # 재시도해도 의미가 없음을 알려야 함
        assert "다른 다운로드 링크" in c.action

    def test_cloudflare_block_classified(self):
        c = classify_error("파싱", "1fichier 차단: Cloudflare 챌린지(우회 실패)")
        assert "Cloudflare" in c.summary
