# -*- coding: utf-8 -*-
"""``download_core`` 의 모듈 레벨 헬퍼 단위 테스트."""

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
        """HTTPS 트래픽도 HTTP 프록시 통해 CONNECT 터널링하므로 스킴은 http."""
        result = _build_proxy_dict("proxy.example.com:3128")
        assert result["https"].startswith("http://")
