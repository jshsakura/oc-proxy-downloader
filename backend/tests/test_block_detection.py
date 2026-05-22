# -*- coding: utf-8 -*-
"""Tests for detecting 1fichier's explicit block responses (VPS/VPN/file deletion, etc.).

1fichier often responds with status 200 while announcing a block in the body,
so if we only see the missing form and end with ``다운로드 폼을 찾을 수 없음``,
the user cannot tell the real cause.
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
        # "Accès restreint" alone should also be detected
        html = "<html><body>Accès restreint pour cette IP.</body></html>"
        assert "VPS/VPN" in sp.detect_block_reason(html)

    def test_deleted_file(self):
        assert "삭제" in sp.detect_block_reason(DELETED_HTML)

    def test_reported_file(self):
        assert "신고" in sp.detect_block_reason(REPORTED_HTML)

    def test_cloudflare_challenge(self):
        assert "Cloudflare" in sp.detect_block_reason(CLOUDFLARE_HTML)

    def test_wait_message_is_not_block(self):
        # "you must wait" is a normal flow, so it must not be detected as a block.
        html = "<html><body>You must wait 5 minutes before download.</body></html>"
        # The match result must be None or a None-signal (no other keyword like "file not found" matching)
        assert sp.detect_block_reason(html) is None

    def test_normal_page_returns_none(self):
        assert sp.detect_block_reason(NORMAL_HTML) is None

    def test_empty_input(self):
        assert sp.detect_block_reason("") is None
        assert sp.detect_block_reason(None) is None


class TestParseRaisesOnBlock:
    def test_parse_simple_sync_raises_on_vpn_block(self, monkeypatch):
        """A 200 response with a VPN block message in the body raises a clear exception."""
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

        # preparse returns None instead of raising (the main parse raises)
        assert sp.preparse_1fichier_standalone("https://1fichier.com/?abc") is None


class TestErrorMessageClassification:
    def test_vpn_block_classified_with_concrete_action(self):
        c = classify_error("파싱", "1fichier 차단: VPS/VPN IP 차단")
        assert "VPS/VPN" in c.summary
        assert "주거용" in c.action or "프록시" in c.action

    def test_deleted_file_classified(self):
        c = classify_error("파싱", "1fichier 차단: 파일 삭제됨")
        assert "삭제" in c.summary
        # Should indicate that retrying is pointless
        assert "다른 다운로드 링크" in c.action

    def test_cloudflare_block_classified(self):
        c = classify_error("파싱", "1fichier 차단: Cloudflare 챌린지(우회 실패)")
        assert "Cloudflare" in c.summary
