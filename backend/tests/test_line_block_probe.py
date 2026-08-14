# -*- coding: utf-8 -*-
"""A filter answering plaintext on :443 must be named, not guessed at.

Measured on 2026-08-14 against megaup's storage node ``e7.megaupdownup.org``:

    :443  → TLS handshake fails, ``[SSL: WRONG_VERSION_NUMBER]``
    :80   → 200, ``<meta http-equiv="REFRESH" ... blocking.asus.hns.tm ...>``

The router's web filter (ASUS AiProtection) was intercepting the domain and
answering plaintext HTTP on the TLS port, which is exactly what
WRONG_VERSION_NUMBER means. The app saw only the TLS error and reported "노드
일시 장애 또는 비표준 포트 차단 가능" — close enough to sound like the hoster's
fault, so the user retries against their own router forever.

The block page only exists on :80. Nobody can see it from the failing request,
so the failure has to go and look.
"""

import pytest

from core.download_core import (
    _network_block_notice,
    looks_like_plaintext_on_tls_port,
)


class TestPlaintextOnTlsPort:
    """The one TLS error that means 'something answered, but not in TLS'."""

    def test_the_real_error_from_the_blocked_node(self):
        assert looks_like_plaintext_on_tls_port(
            "Cannot connect to host e7.megaupdownup.org:443 ssl:default "
            "[[SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:1016)]"
        ) is True

    def test_case_does_not_matter(self):
        assert looks_like_plaintext_on_tls_port("[ssl: wrong_version_number]") is True

    @pytest.mark.parametrize("err", [
        "Cannot connect to host stor03.datanodes.to:8443 [Connect call failed]",
        "Connection reset by peer",
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
        "Server disconnected",
        "",
    ])
    def test_other_failures_are_not_this(self, err):
        # A plain unreachable node, a bad certificate and a reset all have their
        # own causes. Probing :80 for those would just add a request per failure.
        assert looks_like_plaintext_on_tls_port(err) is False


class TestBlockPageRecognition:
    def test_the_asus_filter_page(self):
        # Byte-for-byte the body the node returned on :80.
        page = (
            b'<html>\r\n<head>\r\n<meta HTTP-EQUIV="REFRESH" content="0; '
            b'url=http://blocking.asus.hns.tm/?cat_id=75&mac=2CF05DE238AC'
            b'&domain=e7.megaupdownup.org">\r\n</head>\r\n<body></body>\r\n</html>'
        )
        notice = _network_block_notice(page)
        assert "blocking.asus.hns.tm" in notice
        assert "공유기" in notice

    def test_a_real_hoster_page_is_not_a_block(self):
        assert _network_block_notice(b"<html><title>MegaUp</title></html>") == ""
