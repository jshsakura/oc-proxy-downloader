# -*- coding: utf-8 -*-
""""Available" has to mean what the picker means by it.

The gauge showed "모든 프록시 소진" over a single VPN that was sitting idle and
perfectly usable. The banner fires on ``available_proxies == 0``, and that
number came from a helper that counted proxies with *no ProxyStatus row at
all* — never tried. One recorded failure, ever, and a proxy was "consumed" for
good, even though ``get_next_available_proxy`` would happily hand it out again
the moment its cooldown elapsed.

Two definitions of the same word in one app, and the UI got the wrong one.
"""

import asyncio
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes.proxy import get_available_proxies
from core.models import Base, ProxyStatus, UserProxy
from core.proxy_manager import PROXY_FAILURE_COOLDOWN_SEC, proxy_manager


VPN = "vpn:8888"


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(UserProxy(address=VPN, proxy_type="single", is_active=True))
    session.commit()
    yield session
    session.close()


def _record_failure(db, ago_seconds):
    db.add(ProxyStatus(
        ip="vpn", port=8888, success=False,
        last_failed_at=datetime.datetime.now() - datetime.timedelta(seconds=ago_seconds),
    ))
    db.commit()


class TestAvailability:

    def test_an_untouched_proxy_is_available(self, db):
        assert asyncio.run(get_available_proxies(db)) == [VPN]

    def test_a_proxy_that_failed_long_ago_is_available_again(self, db):
        """The pool self-heals. This is the case that was being reported as
        exhausted — one old failure and the VPN was written off."""
        _record_failure(db, ago_seconds=PROXY_FAILURE_COOLDOWN_SEC + 60)

        assert asyncio.run(get_available_proxies(db)) == [VPN]

    def test_a_proxy_still_cooling_down_is_not_available(self, db):
        _record_failure(db, ago_seconds=30)

        assert asyncio.run(get_available_proxies(db)) == []

    def test_a_successful_proxy_is_available_despite_having_been_used(self, db):
        """Having been used is not a cost. The old helper counted any recorded
        use — success included — against the pool."""
        db.add(ProxyStatus(ip="vpn", port=8888, success=True,
                           last_used_at=datetime.datetime.now()))
        db.commit()

        assert asyncio.run(get_available_proxies(db)) == [VPN]


class TestAgreesWithThePicker:

    def test_availability_uses_the_pickers_own_rule(self, db):
        """One definition, one place. If these drift again the gauge starts
        lying about the pool a second time."""
        _record_failure(db, ago_seconds=30)

        cooling = proxy_manager.cooling_addresses(db)
        available = asyncio.run(get_available_proxies(db))

        assert VPN in cooling
        assert VPN not in available

    def test_an_inactive_proxy_is_not_offered(self, db):
        db.query(UserProxy).update({UserProxy.is_active: False})
        db.commit()

        assert asyncio.run(get_available_proxies(db)) == []
