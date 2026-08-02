# -*- coding: utf-8 -*-
"""Tests for the headful-browser Turnstile fallback and its wiring."""

import pytest

from core import browser_solver as bs
from core import hoster_sites as hs
from core.browser_solver import BrowserSolveResult
from core.hoster_common import HosterParseError


# --- flow registry ---


def test_datanodes_flow_waits_for_the_precheck_animation():
    """Clicking before "File Ready" appears is silently dropped by the site."""
    flow = bs.flow_for_host("datanodes.to")
    assert flow.ready_text == "File Ready"
    assert flow.submit_selector == 'button[name="method_free"]'


def test_flow_lookup_ignores_www_prefix():
    assert bs.flow_for_host("www.datanodes.to") is bs.flow_for_host("datanodes.to")


def test_unknown_host_gets_the_generic_flow():
    flow = bs.flow_for_host("some-new-hoster.example")
    assert flow is bs.DEFAULT_FLOW
    assert flow.submit_selector is None


# --- proxy translation ---


def test_no_proxy_mapping_means_no_browser_proxy():
    assert bs._proxy_settings(None) is None
    assert bs._proxy_settings({}) is None


def test_https_proxy_wins_and_becomes_a_server_entry():
    settings = bs._proxy_settings({"http": "http://1.1.1.1:1", "https": "http://2.2.2.2:8080"})
    assert settings == {"server": "http://2.2.2.2:8080"}


def test_proxy_credentials_are_split_out_of_the_url():
    """Chromium ignores userinfo in --proxy-server, so it must be passed apart."""
    settings = bs._proxy_settings({"https": "http://bob:s3cret@10.0.0.5:3128"})
    assert settings == {
        "server": "http://10.0.0.5:3128",
        "username": "bob",
        "password": "s3cret",
    }


# --- display guard ---


def test_missing_display_fails_fast_with_a_clear_message(monkeypatch):
    """Turnstile issues no token headless, so a missing X display must not be
    reported as a generic parse failure."""
    monkeypatch.setattr(bs.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)

    with pytest.raises(HosterParseError, match="X 디스플레이가 필요합니다"):
        bs.solve_download_page("https://datanodes.to/abc", bs.DATANODES_FLOW)


# --- datanodes wiring ---


def _countdown_page_with_turnstile():
    return """
    <html><body>
      <download-countdown code="abc" rand="r1" referer="https://datanodes.to/download"
        free-method="Free Download &gt;&gt;" captcha-html="&lt;div class=&quot;cf-turnstile&quot;&gt;&lt;/div&gt;">
      </download-countdown>
    </body></html>
    """


def test_datanodes_turnstile_page_goes_straight_to_the_browser(monkeypatch):
    """Replaying the form cannot clear an in-page Turnstile, so the parse must not
    waste a POST round trip before falling back."""
    page = _countdown_page_with_turnstile()
    posts = []
    calls = []

    class _Scraper:
        def get(self, url, **kwargs):
            return _Response(page)

        def post(self, url, **kwargs):
            posts.append(url)
            return _Response(page)

    class _Response:
        def __init__(self, text):
            self.text = text
            self.status_code = 200
            self.headers = {}
            self.content = text.encode()
            self.cookies = _Cookies()

    class _Cookies:
        def get_dict(self):
            return {}

    monkeypatch.setattr(hs, "_scraper", lambda proxies=None: _Scraper())
    monkeypatch.setattr(hs, "_cloudflare_challenge_seen", lambda response, text: False)
    monkeypatch.setattr(
        hs,
        "solve_download_page",
        lambda url, flow, proxies=None: calls.append((url, flow, proxies))
        or BrowserSolveResult(
            download_link="https://tunnel5.dlproxy.uk/download/xyz?sig=1",
            cookies={"a": "b"},
            user_agent="UA/1.0",
        ),
    )

    result = hs.parse_datanodes_sync("https://datanodes.to/abc")

    assert result["download_link"] == "https://tunnel5.dlproxy.uk/download/xyz?sig=1"
    assert posts == [], "the captcha page must short-circuit before the download2 POST"
    assert calls[0][0] == "https://datanodes.to/abc"
    assert calls[0][1] is bs.DATANODES_FLOW
