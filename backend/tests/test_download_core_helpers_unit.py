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

from core.download_core import (
    DownloadCore,
    FICHIER_HOST_BACKOFF_SECONDS,
    EGRESS_DIRECT,
    EGRESS_VPN,
)


class TestFichierHostBackoff:
    """Backoff is per egress: 1fichier counts its free-tier limit per IP, so a
    block on one egress must not pause the other."""

    def test_block_streak_lengthens_cooldown_and_caps(self):
        dc = DownloadCore()
        assert dc._fichier_cooldown_until.get(EGRESS_DIRECT) is None

        for i, expected in enumerate(FICHIER_HOST_BACKOFF_SECONDS, start=1):
            before = datetime.datetime.now()
            dc._register_fichier_block(EGRESS_DIRECT)
            assert dc._fichier_block_streak[EGRESS_DIRECT] == i
            delta = (dc._fichier_cooldown_until[EGRESS_DIRECT] - before).total_seconds()
            # cooldown is roughly the scheduled backoff for this streak position
            assert abs(delta - expected) < 5

        # Beyond the schedule length, it stays capped at the last value.
        dc._register_fichier_block(EGRESS_DIRECT)
        before = datetime.datetime.now()
        dc._register_fichier_block(EGRESS_DIRECT)
        delta = (dc._fichier_cooldown_until[EGRESS_DIRECT] - before).total_seconds()
        assert abs(delta - FICHIER_HOST_BACKOFF_SECONDS[-1]) < 5

    def test_success_resets_backoff(self):
        dc = DownloadCore()
        dc._register_fichier_block(EGRESS_DIRECT)
        dc._register_fichier_block(EGRESS_DIRECT)
        assert dc._fichier_block_streak[EGRESS_DIRECT] == 2
        assert dc._fichier_cooldown_until[EGRESS_DIRECT] is not None

        dc._register_fichier_success(EGRESS_DIRECT)
        assert dc._fichier_block_streak[EGRESS_DIRECT] == 0
        assert dc._fichier_cooldown_until[EGRESS_DIRECT] is None

    def test_successful_login_wakes_every_egress_queue(self):
        dc = DownloadCore()
        dc._register_fichier_block(EGRESS_DIRECT, "일일 무료 다운로드 한도")
        dc._register_fichier_block(EGRESS_VPN, "일일 무료 다운로드 한도")

        dc.clear_fichier_cooldowns("test")

        assert dc._fichier_cooldown_until[EGRESS_DIRECT] is None
        assert dc._fichier_cooldown_until[EGRESS_VPN] is None
        assert dc._fichier_block_streak[EGRESS_DIRECT] == 0
        assert dc._fichier_block_streak[EGRESS_VPN] == 0

    def test_queue_deadline_is_published_to_every_waiting_row(self, monkeypatch):
        dc = DownloadCore()
        dc._register_fichier_block(EGRESS_DIRECT, "일일 무료 다운로드 한도")

        class _Row:
            def __init__(self, row_id):
                self.id = row_id
                self.next_retry_at = None

        rows = [_Row(1), _Row(2)]

        class _Query:
            def filter(self, *args):
                return self

        class _Db:
            def query(self, *args):
                return _Query()

        async def all_rows(_query):
            return rows

        async def commit(_db):
            return None

        updates = []

        monkeypatch.setattr("core.download_core.db_async.all_rows", all_rows)
        monkeypatch.setattr("core.download_core.db_async.commit", commit)

        async def send(row_id, data):
            updates.append((row_id, data))

        monkeypatch.setattr(dc, "send_download_update", send)
        asyncio.run(dc._publish_fichier_cooldown(_Db(), EGRESS_DIRECT))

        deadline = dc._fichier_cooldown_until[EGRESS_DIRECT]
        assert [row.next_retry_at for row in rows] == [deadline, deadline]
        assert [row_id for row_id, _ in updates] == [1, 2]

    def test_daily_quota_holds_the_entire_egress_until_tomorrow(self):
        dc = DownloadCore()
        now = datetime.datetime.now()

        dc._register_fichier_block(
            EGRESS_DIRECT,
            "1fichier 일일 무료 다운로드 한도(10개)를 모두 사용했습니다",
        )

        cooldown = dc._fichier_cooldown_until[EGRESS_DIRECT]
        assert cooldown.date() == (now + datetime.timedelta(days=1)).date()
        assert (cooldown.hour, cooldown.minute) == (0, 10)
        assert dc._fichier_cooldown_until.get(EGRESS_VPN) is None

    def test_a_blocked_egress_leaves_the_other_alone(self):
        # The reason the state is keyed at all: a flagged IP on one route must
        # not stop the route that is still working.
        dc = DownloadCore()
        dc._register_fichier_block(EGRESS_DIRECT)

        assert dc._fichier_cooldown_until[EGRESS_DIRECT] is not None
        assert dc._fichier_cooldown_until.get(EGRESS_VPN) is None
        assert dc._fichier_block_streak.get(EGRESS_VPN, 0) == 0

    def test_each_egress_gets_its_own_slot(self):
        # One 1fichier slot per egress, not one shared slot.
        dc = DownloadCore()
        direct = dc._fichier_sem(EGRESS_DIRECT)
        vpn = dc._fichier_sem(EGRESS_VPN)

        assert direct is not vpn
        assert dc._fichier_sem(EGRESS_DIRECT) is direct  # cached, not rebuilt
        assert direct._value == dc.MAX_FICHIER_LOCAL_DOWNLOADS
        assert vpn._value == dc.MAX_FICHIER_LOCAL_DOWNLOADS

    def test_await_cooldown_returns_immediately_when_inactive(self):
        dc = DownloadCore()

        class _Req:
            id = 1
            status = None

        # No cooldown set → must not block or touch the DB.
        asyncio.run(dc._await_fichier_cooldown(_Req(), db=None))
