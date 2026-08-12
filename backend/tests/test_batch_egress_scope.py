# -*- coding: utf-8 -*-
"""A batch action must not skip half the queue.

The local and proxy gauges each carry their own stop-all / restart-failed
buttons. That was right while ``use_proxy`` was something the user set per item.
It stopped being right the moment egress routing was switched on: the router
assigns the egress, so the user cannot know which gauge a download landed under.

Observed live — pressing "restart" on the local gauge reported one item
restarted and left twenty untouched, all of them `use_proxy=True` because the
router had put them on the VPN. They were not failing; they were invisible.

Under automatic routing the split is an implementation detail, so a batch action
covers everything. Under ``manual`` the user picked the egress themselves, and
the buttons keep meaning what they say.
"""

import pytest

from api.routes.downloads import _egress_filter
from core.download_core import ROUTE_MANUAL


@pytest.fixture()
def route(monkeypatch):
    def _set(value):
        monkeypatch.setattr("api.routes.downloads._read_download_route", lambda: value)
    return _set


def _sql(clause):
    return str(clause.compile(compile_kwargs={"literal_binds": True}))


class TestAutomaticRouting:

    @pytest.mark.parametrize("mode", ["balance", "auto", "vpn", "direct"])
    @pytest.mark.parametrize("want_proxy", [True, False])
    def test_the_filter_matches_everything(self, route, mode, want_proxy):
        """Whichever gauge the button lives on, it has to reach the rows the
        router sent the other way."""
        route(mode)

        assert "use_proxy" not in _sql(_egress_filter(want_proxy))

    def test_both_gauges_agree_when_the_router_decides(self, route):
        route("balance")

        assert _sql(_egress_filter(True)) == _sql(_egress_filter(False))


class TestManualRouting:

    def test_the_local_button_still_means_local(self, route):
        route(ROUTE_MANUAL)

        clause = _sql(_egress_filter(False))
        assert "use_proxy" in clause
        assert "false" in clause.lower()

    def test_the_proxy_button_still_means_proxy(self, route):
        route(ROUTE_MANUAL)

        clause = _sql(_egress_filter(True))
        assert "use_proxy" in clause
        assert "true" in clause.lower()

    def test_the_two_buttons_stay_distinct(self, route):
        """Manual means the user chose; a batch action must respect that."""
        route(ROUTE_MANUAL)

        assert _sql(_egress_filter(True)) != _sql(_egress_filter(False))
