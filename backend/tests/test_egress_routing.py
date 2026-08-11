"""Routing must learn which egress a host refuses.

1fichier answers a datacentre IP with "professional infrastructure detected" —
classified as proxy_blocked. Retrying that egress can only fail again, so the
router has to stop choosing it instead of burning the queue on it.
"""
import datetime

import pytest

from core.download_core import (
    DownloadCore,
    EGRESS_DIRECT,
    EGRESS_VPN,
    EGRESS_BLOCK_TTL,
)


class TestEgressBlockMemory:
    def test_a_refused_egress_is_remembered(self):
        dc = DownloadCore()
        assert not dc._egress_blocked_for("1fichier.com", EGRESS_VPN)

        dc._register_egress_block("1fichier.com", EGRESS_VPN)

        assert dc._egress_blocked_for("1fichier.com", EGRESS_VPN)
        # Only that pairing — the same host over the direct line is untouched,
        # and other hosts may well accept the proxy.
        assert not dc._egress_blocked_for("1fichier.com", EGRESS_DIRECT)
        assert not dc._egress_blocked_for("datanodes.to", EGRESS_VPN)

    def test_the_block_expires_so_a_new_exit_ip_gets_a_chance(self):
        dc = DownloadCore()
        dc._register_egress_block("1fichier.com", EGRESS_VPN)
        assert dc._egress_blocked_for("1fichier.com", EGRESS_VPN)

        # The reason is the IP, and a proxy's exit address changes.
        dc._egress_blocked["1fichier.com@" + EGRESS_VPN] = (
            datetime.datetime.now() - datetime.timedelta(seconds=1)
        )

        assert not dc._egress_blocked_for("1fichier.com", EGRESS_VPN)

    def test_ttl_is_hours_not_seconds(self):
        # A short TTL would send the whole queue back into the block repeatedly.
        assert EGRESS_BLOCK_TTL >= datetime.timedelta(hours=1)


class TestProxyFailureIsNotSwallowed:
    """The retry wrapper must not replace a classified failure with a count.

    1fichier's answer to a datacentre IP classifies as proxy_blocked, which is
    the signal routing needs. Wrapping it in "retries exceeded" made every such
    failure land as `unknown`, so the router kept picking the refused egress.
    """

    def test_the_vpn_block_text_still_classifies_as_proxy_blocked(self):
        from core.error_messages import classify_error, KIND_PROXY_BLOCKED

        verdict = classify_error("파싱", "1fichier 차단: VPS/VPN IP 차단")
        assert verdict.kind == KIND_PROXY_BLOCKED

    def test_a_bare_retry_count_does_not(self):
        from core.error_messages import classify_error, KIND_PROXY_BLOCKED

        verdict = classify_error("파싱", "프록시 파싱 실패 - 최대 재시도 횟수(1) 초과")
        assert verdict.kind != KIND_PROXY_BLOCKED


class TestLearningSurvivesTheRetrySweep:
    """The auto-retry sweep clears failure_kind before restarting a download, so
    routing cannot read it there. attempts_json is what survives."""

    def test_kind_is_read_from_the_attempt_log(self):
        import json as _json
        from core.download_core import DownloadCore
        from core.error_messages import KIND_PROXY_BLOCKED

        class Req:
            failure_kind = None  # the sweep just cleared it
            attempts_json = _json.dumps([
                {"kind": "transient"},
                {"kind": KIND_PROXY_BLOCKED},
            ])

        assert DownloadCore._last_attempt_kind(Req()) == KIND_PROXY_BLOCKED

    def test_missing_or_broken_log_is_not_an_error(self):
        from core.download_core import DownloadCore

        class NoLog:
            attempts_json = None

        class Broken:
            attempts_json = "{not json"

        assert DownloadCore._last_attempt_kind(NoLog()) is None
        assert DownloadCore._last_attempt_kind(Broken()) is None


class TestRouteSemantics:
    """"direct only" has to actually force direct, and the default must not."""

    def test_manual_is_the_default(self):
        from core.download_core import DEFAULT_DOWNLOAD_ROUTE, ROUTE_MANUAL
        from core.config import DEFAULT_CONFIG

        # The default must leave the per-item toggle alone — existing installs
        # rely on it, and silently resetting it would look like a bug.
        assert DEFAULT_DOWNLOAD_ROUTE == ROUTE_MANUAL
        assert DEFAULT_CONFIG["download_route"] == ROUTE_MANUAL

    def test_direct_is_a_separate_choice_from_manual(self):
        from core.download_core import DOWNLOAD_ROUTES, ROUTE_MANUAL

        assert ROUTE_MANUAL in DOWNLOAD_ROUTES
        assert "direct" in DOWNLOAD_ROUTES
        assert ROUTE_MANUAL != "direct"

    def test_an_unknown_route_falls_back_to_the_default(self):
        from core.download_core import _read_download_route, DEFAULT_DOWNLOAD_ROUTE
        import core.download_core as dc

        original = dc.get_config
        try:
            dc.get_config = lambda: {"download_route": "sideways"}
            assert _read_download_route() == DEFAULT_DOWNLOAD_ROUTE
        finally:
            dc.get_config = original
