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


# --- cookie filtering ---


def _cookie(name, domain, value="v"):
    return {"name": name, "domain": domain, "value": value}


def test_empty_cookie_name_is_dropped():
    """aiohttp raises CookieError("Illegal key ''") the moment such a cookie is
    handed to the download session."""
    raw = [_cookie("", ".datanodes.to"), _cookie("file_code", ".datanodes.to", "abc")]

    assert bs._usable_cookies(raw, "https://datanodes.to/abc") == {"file_code": "abc"}


def test_cookie_names_with_illegal_characters_are_dropped():
    raw = [_cookie("bad name", ".datanodes.to"), _cookie("ok_name", ".datanodes.to")]

    assert set(bs._usable_cookies(raw, "https://datanodes.to/abc")) == {"ok_name"}


def test_third_party_ad_cookies_are_not_forwarded():
    """Popunder ad networks drop cookies into the same context; the file server
    has no use for them."""
    raw = [
        _cookie("cf_clearance", ".datanodes.to"),
        _cookie("csu", "ukankingwithea.com"),
    ]

    assert set(bs._usable_cookies(raw, "https://datanodes.to/abc")) == {"cf_clearance"}


def test_parent_domain_cookies_are_kept_for_a_subdomain_page():
    raw = [_cookie("sess", ".datanodes.to")]

    assert set(bs._usable_cookies(raw, "https://www.datanodes.to/abc")) == {"sess"}


def test_cookie_without_a_domain_is_dropped():
    """A blank domain would otherwise match every host through the suffix test."""
    raw = [_cookie("orphan", "")]

    assert bs._usable_cookies(raw, "https://datanodes.to/abc") == {}


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


def test_without_a_display_the_fallback_names_docker_as_the_requirement(monkeypatch):
    """Standalone builds ship no browser and no display, so the user must be told
    that rather than getting a missing-executable crash out of Playwright."""
    monkeypatch.delenv("DISPLAY", raising=False)

    with pytest.raises(HosterParseError, match="Docker 버전에서만 지원됩니다"):
        bs.solve_download_page("https://datanodes.to/abc", bs.DATANODES_FLOW)


def test_display_present_means_the_fallback_is_allowed_to_run(monkeypatch):
    """The guard must not reject the Docker image, where Xvfb sets DISPLAY."""
    monkeypatch.setenv("DISPLAY", ":99")

    assert bs._require_display() is None


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


# --- serialisation ---


def test_solves_are_serialised_process_wide(monkeypatch):
    """parse_concurrency (default 3) would otherwise start three headful Chromium
    instances at once and hit the host in a burst."""
    import threading

    monkeypatch.setenv("DISPLAY", ":99")
    overlap = {"max": 0, "current": 0}
    guard = threading.Lock()

    class _FakePlaywright:
        def __enter__(self):
            # Raising out of __enter__ skips __exit__, so the occupancy window is
            # opened and closed here rather than across the two hooks.
            import time
            with guard:
                overlap["current"] += 1
                overlap["max"] = max(overlap["max"], overlap["current"])
            time.sleep(0.05)
            with guard:
                overlap["current"] -= 1
            raise RuntimeError("stop after entry")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(bs, "sync_playwright", lambda: _FakePlaywright())

    def run():
        try:
            bs.solve_download_page("https://datanodes.to/abc", bs.DATANODES_FLOW)
        except RuntimeError:
            pass

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert overlap["max"] == 1, "browsers must never run concurrently"
