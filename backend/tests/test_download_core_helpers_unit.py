# -*- coding: utf-8 -*-
"""Unit tests for the module-level helpers in ``download_core``."""

from core.download_core import _build_proxy_dict


class TestBuildProxyDict:
    def test_none_input_returns_none(self):
        assert _build_proxy_dict(None) is None

    def test_empty_string_returns_none(self):
        assert _build_proxy_dict("") is None

    def test_ip_port_input_yields_http_dict(self):
        result = _build_proxy_dict("1.2.3.4:8080")
        assert result == {
            "http": "http://1.2.3.4:8080",
            "https": "http://1.2.3.4:8080",
        }

    def test_https_uses_http_scheme_for_connect_tunnel(self):
        """HTTPS traffic also CONNECT-tunnels through an HTTP proxy, so the scheme is http."""
        result = _build_proxy_dict("proxy.example.com:3128")
        assert result["https"].startswith("http://")
