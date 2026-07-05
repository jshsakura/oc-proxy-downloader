# -*- coding: utf-8 -*-
"""Tests for proxy type detection and the self-healing proxy pool.

Covers two fixes:
1. ``detect_proxy_type`` correctly classifies IP:PORT, host:PORT, URLs, and
   fallbacks (previously an indentation bug returned ``None`` for host:PORT and
   for scheme-less list URLs, so those proxies were silently dropped).
2. ``get_next_available_proxy`` puts a failed proxy on a *cooldown* rather than
   retiring it permanently, so the pool self-heals once the window elapses.
"""

import asyncio
import datetime

import pytest

from core.db import engine, SessionLocal
from core.models import Base, ProxyStatus, UserProxy
from core.proxy_manager import (
    ProxyManager,
    detect_proxy_type,
    PROXY_FAILURE_COOLDOWN_SEC,
)


@pytest.fixture(scope="module", autouse=True)
def _create_tables():
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_db():
    def _wipe():
        session = SessionLocal()
        try:
            session.query(ProxyStatus).delete()
            session.query(UserProxy).delete()
            session.commit()
        finally:
            session.close()

    _wipe()
    yield
    _wipe()


class TestDetectProxyType:
    def test_ip_port_is_single(self):
        assert detect_proxy_type("1.2.3.4:8080") == "single"

    def test_host_port_is_single(self):
        # Regression: the indentation bug made this return None.
        assert detect_proxy_type("proxy.example.com:3128") == "single"

    def test_http_url_is_list(self):
        assert detect_proxy_type("http://example.com/proxies.txt") == "list"
        assert detect_proxy_type("https://example.com/proxies.txt") == "list"

    def test_unknown_falls_back_to_list(self):
        # Regression: previously fell through to None.
        assert detect_proxy_type("just-a-hostname") == "list"


def _add_single_proxy(session, address):
    session.add(UserProxy(address=address, proxy_type="single", is_active=True))
    session.commit()


def _mark_failed_at(session, addr, when):
    ip, port = addr.split(":")
    session.add(
        ProxyStatus(
            ip=ip,
            port=int(port),
            success=False,
            last_status="fail",
            last_used_at=when,
            last_failed_at=when,
        )
    )
    session.commit()


class TestSelfHealingPool:
    def test_recent_failure_is_excluded(self):
        session = SessionLocal()
        try:
            _add_single_proxy(session, "10.0.0.1:8080")
            _add_single_proxy(session, "10.0.0.2:8080")
            # 10.0.0.1 just failed -> on cooldown, must not be handed out.
            _mark_failed_at(session, "10.0.0.1:8080", datetime.datetime.now())

            pm = ProxyManager()
            chosen = asyncio.run(pm.get_next_available_proxy(session, download_id=1))
            assert chosen == "10.0.0.2:8080"
        finally:
            session.close()

    def test_expired_failure_is_eligible_again(self):
        session = SessionLocal()
        try:
            _add_single_proxy(session, "10.0.0.1:8080")
            # Failed longer ago than the cooldown -> should be selectable again.
            stale = datetime.datetime.now() - datetime.timedelta(
                seconds=PROXY_FAILURE_COOLDOWN_SEC + 60
            )
            _mark_failed_at(session, "10.0.0.1:8080", stale)

            pm = ProxyManager()
            chosen = asyncio.run(pm.get_next_available_proxy(session, download_id=2))
            assert chosen == "10.0.0.1:8080"
        finally:
            session.close()

    def test_all_cooling_retries_oldest_failure(self):
        session = SessionLocal()
        try:
            _add_single_proxy(session, "10.0.0.1:8080")
            _add_single_proxy(session, "10.0.0.2:8080")
            now = datetime.datetime.now()
            # Both on cooldown; .2 failed longer ago -> it is the fallback pick.
            _mark_failed_at(session, "10.0.0.1:8080", now)
            _mark_failed_at(session, "10.0.0.2:8080", now - datetime.timedelta(seconds=120))

            pm = ProxyManager()
            chosen = asyncio.run(pm.get_next_available_proxy(session, download_id=3))
            assert chosen == "10.0.0.2:8080"
        finally:
            session.close()

    def test_release_download_drops_rotation_index(self):
        pm = ProxyManager()
        pm.download_proxy_index[42] = 3
        pm.release_download(42)
        assert 42 not in pm.download_proxy_index
        # Idempotent: releasing an unknown id is a no-op, not a KeyError.
        pm.release_download(999)

    def test_proxy_test_methods_are_bound_to_the_class(self):
        # Regression: an indentation bug had nested these as dead functions inside
        # the module-level detect_proxy_type, so proxy_manager.test_proxy_async
        # raised AttributeError. They must be real ProxyManager methods again.
        pm = ProxyManager()
        for name in ("test_proxy_async", "get_working_proxy_async", "mark_proxy_used"):
            assert callable(getattr(pm, name)), name

    def test_mark_failed_records_failure_time(self):
        session = SessionLocal()
        try:
            pm = ProxyManager()
            asyncio.run(pm.mark_proxy_failed(session, "10.0.0.9:8080"))

            row = session.query(ProxyStatus).filter(
                ProxyStatus.ip == "10.0.0.9", ProxyStatus.port == 8080
            ).first()
            assert row is not None
            assert row.success is False
            assert row.last_failed_at is not None  # regression: was never set
        finally:
            session.close()
