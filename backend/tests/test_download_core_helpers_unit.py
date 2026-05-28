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


import asyncio
import datetime

from core.download_core import DownloadCore, FICHIER_HOST_BACKOFF_SECONDS


class TestFichierHostBackoff:
    def test_block_streak_lengthens_cooldown_and_caps(self):
        dc = DownloadCore()
        assert dc._fichier_cooldown_until is None

        for i, expected in enumerate(FICHIER_HOST_BACKOFF_SECONDS, start=1):
            before = datetime.datetime.now()
            dc._register_fichier_block()
            assert dc._fichier_block_streak == i
            delta = (dc._fichier_cooldown_until - before).total_seconds()
            # cooldown is roughly the scheduled backoff for this streak position
            assert abs(delta - expected) < 5

        # Beyond the schedule length, it stays capped at the last value.
        dc._register_fichier_block()
        before = datetime.datetime.now()
        dc._register_fichier_block()
        delta = (dc._fichier_cooldown_until - before).total_seconds()
        assert abs(delta - FICHIER_HOST_BACKOFF_SECONDS[-1]) < 5

    def test_success_resets_backoff(self):
        dc = DownloadCore()
        dc._register_fichier_block()
        dc._register_fichier_block()
        assert dc._fichier_block_streak == 2
        assert dc._fichier_cooldown_until is not None

        dc._register_fichier_success()
        assert dc._fichier_block_streak == 0
        assert dc._fichier_cooldown_until is None

    def test_await_cooldown_returns_immediately_when_inactive(self):
        dc = DownloadCore()

        class _Req:
            id = 1
            status = None

        # No cooldown set → must not block or touch the DB.
        asyncio.run(dc._await_fichier_cooldown(_Req(), db=None))
