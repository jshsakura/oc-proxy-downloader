# -*- coding: utf-8 -*-
"""Tests for keeping slow captcha parses off the pool the whole app shares."""

from core import app_factory
from core.browser_solver import DEFAULT_MAX_CONCURRENT_BROWSERS
from core.executors import CAPTCHA_PARSE_EXECUTOR, parse_executor_for


def test_captcha_hosts_parse_on_their_own_pool():
    """A solve holds its thread for minutes; on the default executor a couple of
    them left the API with no worker and the UI stuck on skeletons."""
    assert parse_executor_for("https://datanodes.to/abc") is CAPTCHA_PARSE_EXECUTOR
    assert parse_executor_for("https://send.now/abc") is CAPTCHA_PARSE_EXECUTOR


def test_www_prefix_still_routes_to_the_captcha_pool():
    assert parse_executor_for("https://www.datanodes.to/abc") is CAPTCHA_PARSE_EXECUTOR


def test_ordinary_hosts_stay_on_the_default_executor():
    """Most parses finish in seconds and belong in the shared pool."""
    assert parse_executor_for("https://1fichier.com/?abc") is None
    assert parse_executor_for("https://gofile.io/d/abc") is None
    assert parse_executor_for("") is None


def test_captcha_pool_matches_the_browser_cap():
    """Sized to the browser ceiling so the queue forms here rather than inside a
    pool other work depends on."""
    assert CAPTCHA_PARSE_EXECUTOR._max_workers == DEFAULT_MAX_CONCURRENT_BROWSERS


def test_default_pool_keeps_headroom_above_the_parse_budget():
    """Parsing must not be able to consume every worker: the status endpoints the
    UI polls run on this same pool."""
    assert app_factory.EXECUTOR_HEADROOM_WORKERS > 0

