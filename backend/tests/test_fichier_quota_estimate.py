# -*- coding: utf-8 -*-
"""The 1fichier quota row says when it should free, from our own transfers."""

from datetime import datetime, timedelta

from core.error_messages import fichier_quota_frees_at


NOW = datetime(2026, 10, 13, 10, 15)


def test_frees_when_the_oldest_transfer_in_the_window_ages_out():
    started = [
        datetime(2026, 10, 12, 7, 11),   # already outside the window
        datetime(2026, 10, 12, 13, 56),
        datetime(2026, 10, 12, 16, 6),
    ]
    assert fichier_quota_frees_at(started, NOW) == datetime(2026, 10, 13, 13, 56)


def test_nothing_started_lately_means_no_estimate():
    assert fichier_quota_frees_at([NOW - timedelta(days=2), None], NOW) is None
