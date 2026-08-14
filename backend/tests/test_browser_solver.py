# -*- coding: utf-8 -*-
"""Tests for the headful-browser Turnstile fallback and its wiring."""

import pytest

from core import browser_solver as bs
from core import hoster_sites as hs
from core.browser_solver import BrowserSolveResult
from core.hoster_common import HosterParseError


# --- flow registry ---


def test_datanodes_flow_does_not_wait_for_a_banner_the_page_dropped():
    """The redesigned page has no "File Ready" text; polling for it only burnt
    a minute of the solve budget before the first click."""
    flow = bs.flow_for_host("datanodes.to")
    assert flow.ready_text is None
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


# --- link capture ---


def test_a_storage_node_navigation_counts_as_the_link():
    """The host hands the file over by navigating the tab at its storage node. If
    that node is unreachable no download event ever fires, and the link the host
    DID issue used to be thrown away as "captcha passed but no link issued"."""
    page = "https://datanodes.to/exren3rgg1m9"

    assert bs._is_file_navigation(
        "https://stor03.datanodes.to:8443/d/ykmm/Some%20Game.part2.rar", page
    )


def test_ad_and_page_navigations_are_not_mistaken_for_the_link():
    page = "https://datanodes.to/exren3rgg1m9"

    # popunder ad network — different site
    assert not bs._is_file_navigation("https://andallthemise.org/x/y.rar", page)
    # the host's own pages are not files, extension or not — including the
    # file-named one that just re-renders the download page
    assert not bs._is_file_navigation("https://datanodes.to/download", page)
    assert not bs._is_file_navigation("https://datanodes.to/premium.php", page)
    assert not bs._is_file_navigation("https://datanodes.to/exren3rgg1m9/Some%20Game.rar", page)


# --- serialisation ---


def test_solves_for_one_site_never_overlap(monkeypatch):
    """A site must never be hit concurrently: parse_concurrency (default 3) would
    otherwise start three browsers against the same host at once."""
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


# --- time budget ---


def test_budget_stays_under_the_outer_parse_cap():
    """download_core aborts the await at 300s but cannot stop this thread, so the
    solve must finish on its own before then or it keeps holding the lock."""
    from core.download_core import SPECIAL_HOSTER_PARSE_TIMEOUT_SEC

    assert bs.SOLVE_BUDGET_SEC < SPECIAL_HOSTER_PARSE_TIMEOUT_SEC
    assert bs.LOCK_WAIT_SEC + bs.MIN_SOLVE_BUDGET_SEC <= bs.SOLVE_BUDGET_SEC


def test_deadline_reports_expiry_with_the_stage():
    d = bs.Deadline(0)

    assert d.expired()
    with pytest.raises(HosterParseError, match="제한시간"):
        d.check("토큰 대기")


def test_deadline_clips_a_step_timeout_to_what_is_left():
    assert bs.Deadline(1).budget_ms(60_000) <= 1_000
    assert bs.Deadline(600).budget_ms(20_000) == 20_000


def test_queue_slots_are_released_when_a_solve_fails(monkeypatch):
    """A raise inside the browser must strand neither the site queue nor a browser
    slot, or that site wedges permanently."""
    monkeypatch.setenv("DISPLAY", ":99")

    def boom():
        raise RuntimeError("browser died")

    monkeypatch.setattr(bs, "sync_playwright", boom)

    with pytest.raises(RuntimeError):
        bs.solve_download_page("https://datanodes.to/abc", bs.DATANODES_FLOW)

    site_queue = bs._host_lock("datanodes.to")
    assert site_queue.acquire(timeout=1), "site queue must be free after a failure"
    site_queue.release()
    assert bs._BROWSER_SLOTS.acquire(timeout=1), "browser slot must be returned"
    bs._BROWSER_SLOTS.release()


def test_queued_solve_gives_up_when_no_useful_time_remains(monkeypatch):
    """Rather than start a browser it cannot finish, a link that waited too long
    fails as transient so the retry logic picks it up later."""
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(bs, "MIN_SOLVE_BUDGET_SEC", 10 ** 6)
    monkeypatch.setattr(bs, "sync_playwright", lambda: pytest.fail("must not launch"))

    with pytest.raises(HosterParseError, match="대기열에서 시간이 초과"):
        bs.solve_download_page("https://datanodes.to/abc", bs.DATANODES_FLOW)


def test_different_sites_do_not_queue_behind_each_other(monkeypatch):
    """Per-site queues are the point: a slow DataNodes solve must not hold up a
    Send.now link, as a single global lock used to."""
    import threading
    import time

    monkeypatch.setenv("DISPLAY", ":99")
    started = []
    release = threading.Event()

    class _Blocking:
        def __enter__(self):
            started.append(time.monotonic())
            release.wait(timeout=5)
            raise RuntimeError("stop")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(bs, "sync_playwright", lambda: _Blocking())

    def run(url):
        try:
            bs.solve_download_page(url, bs.DEFAULT_FLOW)
        except RuntimeError:
            pass

    threads = [
        threading.Thread(target=run, args=("https://datanodes.to/a",)),
        threading.Thread(target=run, args=("https://send.now/b",)),
    ]
    for t in threads:
        t.start()
    # Both hold their own site queue, and two browser slots exist, so both should
    # have entered before either is released.
    time.sleep(1.0)
    entered_together = len(started) == 2
    release.set()
    for t in threads:
        t.join(timeout=10)

    assert entered_together, "two different sites must be able to run at once"


def test_queue_timeout_is_reported_as_queued_not_as_a_failure():
    """The queue message has to classify as KIND_QUEUED; as a plain failure it
    would eat the retry budget and eventually drop the link."""
    from core.error_messages import KIND_QUEUED, classify_error

    assert classify_error("파싱", bs.QUEUE_WAIT_MESSAGE).kind == KIND_QUEUED


# --- builds without a browser ---


def test_browser_only_hosts_are_refused_before_any_network_work(monkeypatch):
    """On the standalone build these links can never succeed, so the user should
    hear that immediately instead of after a page fetch and a form POST."""
    from core import hoster_parsers as hp

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(hp, "parse_datanodes_sync",
                        lambda *a, **k: pytest.fail("must not reach the parser"))

    with pytest.raises(HosterParseError, match="Docker 버전에서만 지원됩니다"):
        hp.parse_special_hoster_sync("https://datanodes.to/abc")


def test_hosts_without_a_captcha_are_unaffected_without_a_browser(monkeypatch):
    """Only the browser-flow hosts are gated; everything else still parses."""
    from core import hoster_parsers as hp

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(hp, "parse_pixeldrain_sync", lambda *a, **k: {"download_link": "ok"})

    assert hp.parse_special_hoster_sync("https://pixeldrain.com/u/abc")["download_link"] == "ok"


def test_browser_support_follows_the_display(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":99")
    assert bs.is_browser_supported()
    monkeypatch.delenv("DISPLAY", raising=False)
    assert not bs.is_browser_supported()
