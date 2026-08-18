"""Routing must learn which egress a host refuses.

1fichier answers a datacentre IP with "professional infrastructure detected" —
classified as proxy_blocked. Retrying that egress can only fail again, so the
router has to stop choosing it instead of burning the queue on it.
"""
import datetime
import json

import pytest

from core import download_core as dc_module
from core.config import DEFAULT_CONFIG
from core.download_core import (
    DEFAULT_DOWNLOAD_ROUTE,
    DOWNLOAD_ROUTES,
    DownloadCore,
    EGRESS_BLOCK_TTL,
    EGRESS_DIRECT,
    EGRESS_VPN,
    ROUTE_MANUAL,
    _read_download_route,
    egress_denied_for_host,
)
from core.error_messages import KIND_PROXY_BLOCKED, classify_error


class TestEgressBlockMemory:
    def test_a_refused_egress_is_remembered(self):
        dc = DownloadCore()
        assert not dc._egress_blocked_for("1fichier.com", EGRESS_VPN)

        dc._register_egress_block("1fichier.com", EGRESS_VPN)

        assert dc._egress_blocked_for("1fichier.com", EGRESS_VPN)
        # Only that pairing — the same host over the direct line is untouched,
        # and other hosts may well accept the proxy. (Not datanodes.to: it
        # carries a standing denial, see TestStandingHostEgressDenial.)
        assert not dc._egress_blocked_for("1fichier.com", EGRESS_DIRECT)
        assert not dc._egress_blocked_for("gofile.io", EGRESS_VPN)

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
        verdict = classify_error("파싱", "1fichier 차단: VPS/VPN IP 차단")
        assert verdict.kind == KIND_PROXY_BLOCKED

    def test_a_bare_retry_count_does_not(self):
        verdict = classify_error("파싱", "프록시 파싱 실패 - 최대 재시도 횟수(1) 초과")
        assert verdict.kind != KIND_PROXY_BLOCKED


class TestLearningSurvivesTheRetrySweep:
    """The auto-retry sweep clears failure_kind before restarting a download, so
    routing cannot read it there. attempts_json is what survives."""

    def test_kind_is_read_from_the_attempt_log(self):

        class Req:
            failure_kind = None  # the sweep just cleared it
            attempts_json = json.dumps([
                {"kind": "transient"},
                {"kind": KIND_PROXY_BLOCKED},
            ])

        assert DownloadCore._last_attempt_kind(Req()) == KIND_PROXY_BLOCKED

    def test_missing_or_broken_log_is_not_an_error(self):

        class NoLog:
            attempts_json = None

        class Broken:
            attempts_json = "{not json"

        assert DownloadCore._last_attempt_kind(NoLog()) is None
        assert DownloadCore._last_attempt_kind(Broken()) is None


class FakeDb:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


class FakeReq:
    def __init__(self, url, use_proxy=True, attempt_count=0, proxy_pinned=False):
        self.id = 1
        self.url = url
        self.original_url = url
        self.use_proxy = use_proxy
        self.attempt_count = attempt_count
        self.attempts_json = None
        self.proxy_pinned = proxy_pinned


def _route(dc, req, route="balance"):
    """Run _apply_download_route with a given route and a live proxy available.

    Layered over DEFAULT_CONFIG the way the real get_config is, so the shipped
    host_egress_deny policy is in play rather than silently absent.
    """
    original = dc_module.get_config
    try:
        dc_module.get_config = lambda: {**DEFAULT_CONFIG, "download_route": route}
        dc._proxy_egress_available = lambda db: True
        dc._apply_download_route(req, FakeDb())
    finally:
        dc_module.get_config = original
    return req.use_proxy


class TestStandingHostEgressDenial:
    """datanodes.to solves the captcha over the VPN and then withholds the link.

    Measured over the whole table: direct 1168 done / 2 failed, VPN 0 done / 24
    failed. Every VPN attempt burns a browser captcha — the most expensive and
    most serialized resource the app has — to reach a guaranteed failure.
    """

    def test_datanodes_is_denied_the_vpn(self):
        assert egress_denied_for_host("datanodes.to", EGRESS_VPN) is True

    def test_datanodes_keeps_the_direct_line(self):
        assert egress_denied_for_host("datanodes.to", EGRESS_DIRECT) is False

    def test_other_hosts_are_untouched(self):
        # 1fichier over the VPN works (7 done / 2 failed) and is worth keeping:
        # its free tier throttles per IP, so a second egress genuinely adds
        # throughput there.
        assert egress_denied_for_host("1fichier.com", EGRESS_VPN) is False
        assert egress_denied_for_host("_default", EGRESS_VPN) is False

    def test_the_standing_denial_reads_as_a_block(self):
        dc = DownloadCore()
        assert dc._egress_blocked_for("datanodes.to", EGRESS_VPN)
        assert not dc._egress_blocked_for("1fichier.com", EGRESS_VPN)

    def test_it_never_expires_unlike_a_learned_block(self):
        # A learned block is about an exit IP going stale. This is hoster policy,
        # so clearing the learned table must not revive it.
        dc = DownloadCore()
        dc._egress_blocked.clear()
        assert dc._egress_blocked_for("datanodes.to", EGRESS_VPN)

    def test_balance_never_routes_datanodes_through_the_vpn(self):
        dc = DownloadCore()
        req = FakeReq("https://datanodes.to/abc123", use_proxy=True)
        assert _route(dc, req) is False

    def test_even_an_explicit_vpn_route_falls_back_to_direct(self):
        # Better a download that works than one that cannot.
        dc = DownloadCore()
        req = FakeReq("https://datanodes.to/abc123", use_proxy=True)
        assert _route(dc, req, route="vpn") is False

    def test_a_denied_host_does_not_disturb_other_hosts(self):
        dc = DownloadCore()
        req = FakeReq("https://1fichier.com/?abc", use_proxy=True)
        assert _route(dc, req, route="vpn") is True


class TestDenialIsConfigurable:
    """The denial must be overridable without a redeploy.

    It was measured against exactly one VPN exit (Surfshark JP). Hardcoding it
    permanently meant a user on a different exit — or datanodes changing policy,
    which MegaUp just did to its own link scheme — stayed blocked until someone
    edited the source and shipped a release.
    """

    @staticmethod
    def _with_config(policy):
        original = dc_module.get_config
        dc_module.get_config = lambda: {"host_egress_deny": policy}
        return original

    def test_the_measured_default_still_applies(self):
        assert DEFAULT_CONFIG["host_egress_deny"] == {"datanodes.to": ["vpn"]}

    def test_a_user_can_switch_it_off(self):
        original = self._with_config({})
        try:
            assert egress_denied_for_host("datanodes.to", EGRESS_VPN) is False
        finally:
            dc_module.get_config = original

    def test_a_user_can_empty_one_host_without_touching_others(self):
        original = self._with_config({"datanodes.to": [], "gofile.io": ["vpn"]})
        try:
            assert egress_denied_for_host("datanodes.to", EGRESS_VPN) is False
            assert egress_denied_for_host("gofile.io", EGRESS_VPN) is True
        finally:
            dc_module.get_config = original

    def test_a_user_can_add_a_host_they_measured_themselves(self):
        original = self._with_config({"rapidgator.net": ["vpn"]})
        try:
            assert egress_denied_for_host("rapidgator.net", EGRESS_VPN) is True
        finally:
            dc_module.get_config = original

    @pytest.mark.parametrize(
        "policy", [None, "datanodes.to", {"datanodes.to": "vpn"}, {"datanodes.to": None}]
    )
    def test_a_malformed_policy_denies_nothing_rather_than_crashing(self, policy):
        # config.json is hand-edited. A typo must not take the download path down,
        # and must not silently deny an egress the user never named.
        original = self._with_config(policy)
        try:
            assert egress_denied_for_host("datanodes.to", EGRESS_VPN) is False
        finally:
            dc_module.get_config = original


class TestStandingDenialOutranksEveryRoute:
    """The denial is not a preference between working paths — it is one path that
    cannot work. `manual` is the shipped default and its whole job is to leave the
    per-item toggle alone, so without this the rule did nothing on a stock install.
    """

    def test_manual_still_refuses_a_denied_egress(self):
        dc = DownloadCore()
        req = FakeReq("https://datanodes.to/abc123", use_proxy=True)
        assert _route(dc, req, route=ROUTE_MANUAL) is False

    def test_manual_leaves_other_hosts_toggled_as_the_user_set_them(self):
        dc = DownloadCore()
        req = FakeReq("https://1fichier.com/?abc", use_proxy=True)
        assert _route(dc, req, route=ROUTE_MANUAL) is True

    def test_manual_does_not_touch_an_already_direct_item(self):
        dc = DownloadCore()
        req = FakeReq("https://datanodes.to/abc123", use_proxy=False)
        db = FakeDb()
        original = dc_module.get_config
        try:
            dc_module.get_config = lambda: {"download_route": ROUTE_MANUAL}
            dc._apply_download_route(req, db)
        finally:
            dc_module.get_config = original
        assert req.use_proxy is False
        assert db.commits == 0, "nothing changed, so nothing should be written"

    def test_a_learned_block_does_not_override_manual(self):
        # Deliberately narrower than the standing denial: a learned block is a
        # heuristic read off live failures and it expires, so letting it silently
        # override the user's own toggle would be guessing on their behalf.
        dc = DownloadCore()
        dc._register_egress_block("1fichier.com", EGRESS_VPN)
        req = FakeReq("https://1fichier.com/?abc", use_proxy=True)
        assert _route(dc, req, route=ROUTE_MANUAL) is True


class TestRouteSemantics:
    """"direct only" has to actually force direct, and the default must not."""

    def test_manual_is_the_default(self):

        # The default must leave the per-item toggle alone — existing installs
        # rely on it, and silently resetting it would look like a bug.
        assert DEFAULT_DOWNLOAD_ROUTE == ROUTE_MANUAL
        assert DEFAULT_CONFIG["download_route"] == ROUTE_MANUAL

    def test_direct_is_a_separate_choice_from_manual(self):

        assert ROUTE_MANUAL in DOWNLOAD_ROUTES
        assert "direct" in DOWNLOAD_ROUTES
        assert ROUTE_MANUAL != "direct"

    def test_an_unknown_route_falls_back_to_the_default(self):

        original = dc_module.get_config
        try:
            dc_module.get_config = lambda: {"download_route": "sideways"}
            assert _read_download_route() == DEFAULT_DOWNLOAD_ROUTE
        finally:
            dc_module.get_config = original


class TestAHumanToggleOutranksTheRoute:
    """route 가 auto/vpn/balance 이면 시작할 때마다 앱이 출구를 다시 골랐다.

    사람이 방금 끈 VPN 을 그 자리에서 되켜므로, 스위치를 눌러도 아무 일도 일어나지
    않는 것처럼 보였다 — 실제로 그렇게 보고가 들어왔다. 직접 만진 행은 건너뛴다.
    """

    def test_balance_leaves_a_pinned_item_alone(self):
        dc = DownloadCore()
        req = FakeReq("https://1fichier.com/?abc", use_proxy=False, proxy_pinned=True)
        assert _route(dc, req, route="balance") is False

    def test_even_the_vpn_route_leaves_a_pinned_item_alone(self):
        dc = DownloadCore()
        req = FakeReq("https://1fichier.com/?abc", use_proxy=False, proxy_pinned=True)
        assert _route(dc, req, route="vpn") is False

    def test_a_pin_can_also_hold_the_vpn_on(self):
        dc = DownloadCore()
        req = FakeReq("https://1fichier.com/?abc", use_proxy=True, proxy_pinned=True)
        assert _route(dc, req, route="direct") is True

    def test_a_pin_does_not_survive_a_host_that_refuses_the_vpn(self):
        # 이건 취향 다툼이 아니라 그 호스트에서 그 길이 안 되는 것이다.
        dc = DownloadCore()
        req = FakeReq("https://datanodes.to/abc123", use_proxy=True, proxy_pinned=True)
        assert _route(dc, req, route=ROUTE_MANUAL) is False

    def test_a_pinned_vpn_falls_back_when_no_proxy_is_active(self):
        dc = DownloadCore()
        req = FakeReq("https://1fichier.com/?abc", use_proxy=True, proxy_pinned=True)
        original = dc_module.get_config
        try:
            dc_module.get_config = lambda: {**DEFAULT_CONFIG, "download_route": ROUTE_MANUAL}
            dc._proxy_egress_available = lambda db: False
            dc._apply_download_route(req, FakeDb())
        finally:
            dc_module.get_config = original
        assert req.use_proxy is False


class TestTheSwitchStopsLying:
    """출구를 앱이 바꿨으면 화면에도 그렇게 보여야 한다.

    예전에는 조용히 껐다. DB 는 direct 인데 화면 스위치는 VPN 으로 켜진 채라,
    사용자는 VPN 으로 받는 중이라고 믿었다.
    """

    def test_forcing_direct_reports_what_it_did_and_why(self):
        dc = DownloadCore()
        req = FakeReq("https://datanodes.to/abc123", use_proxy=True)
        original = dc_module.get_config
        try:
            dc_module.get_config = lambda: {**DEFAULT_CONFIG, "download_route": ROUTE_MANUAL}
            dc._proxy_egress_available = lambda db: True
            result = dc._apply_download_route(req, FakeDb())
        finally:
            dc_module.get_config = original
        assert result is not None, "화면에 알릴 것이 없으면 스위치가 또 거짓말을 한다"
        use_proxy, reason = result
        assert use_proxy is False
        assert "datanodes.to" in reason

    def test_a_route_that_changes_nothing_reports_nothing(self):
        dc = DownloadCore()
        req = FakeReq("https://1fichier.com/?abc", use_proxy=True)
        original = dc_module.get_config
        try:
            dc_module.get_config = lambda: {**DEFAULT_CONFIG, "download_route": ROUTE_MANUAL}
            dc._proxy_egress_available = lambda db: True
            assert dc._apply_download_route(req, FakeDb()) is None
        finally:
            dc_module.get_config = original
