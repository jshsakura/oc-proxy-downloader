# -*- coding: utf-8 -*-
"""Additional tests to fill in branch coverage for ``simple_parser``."""

from unittest.mock import MagicMock

import pytest

from core import simple_parser as sp


# ---------------------------------------------------------------------------
# parse_1fichier_simple_sync — flow with a wait time
# ---------------------------------------------------------------------------


def _make_wait_page_html(wait_seconds: int) -> str:
    """Wait-page HTML in the ``var ct = N`` form."""
    return f"""
    <html><body>
        <table>
            <tr>
                <td><img src="/qr.pl?k=1"></td>
                <td class="normal">
                    <span style="font-weight:bold">file.bin</span>
                    <br>
                    <span style="font-size:0.9em;font-style:italic">100 MB</span>
                </td>
            </tr>
        </table>
        <form id="f1"><input type="hidden" name="adz" value="x"></form>
        <script>var ct = {wait_seconds};</script>
    </body></html>
    """


def test_parse_simple_sync_with_wait_time_skips_actual_sleep(monkeypatch):
    """When there is a wait time, count down for as many ``time.sleep`` calls as needed."""

    get_response = MagicMock()
    get_response.status_code = 200
    get_response.text = _make_wait_page_html(60)
    get_response.headers = {}

    post_response = MagicMock()
    post_response.status_code = 302
    post_response.text = ""
    post_response.headers = {"Location": "https://a-2.1fichier.com/p1/file.bin"}

    cookie = MagicMock()
    cookie.name = "session"
    cookie.value = "v"

    scraper = MagicMock()
    scraper.cookies = [cookie]
    scraper.get.return_value = get_response
    scraper.post.return_value = post_response

    monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)
    sleep_calls = []
    monkeypatch.setattr(sp.time, "sleep", lambda s: sleep_calls.append(s))

    # Called without download_id → the wait loop runs a single plain sleep
    result = sp.parse_1fichier_simple_sync(
        "https://1fichier.com/?abc",
        password=None,
        proxies=None,
        proxy_addr=None,
        download_id=None,
        sse_callback=None,
    )

    assert result["wait_time"] == 60
    assert sum(sleep_calls) == 60
    assert result["download_link"].startswith("https://a-2.1fichier.com/")


def test_parse_simple_sync_sse_callback_invoked_during_wait(monkeypatch):
    """When download_id is present, the SSE callback is invoked during the countdown.
    After the switch to a cancel_signal-based design, DB mocking is no longer needed.
    """
    import threading
    from core import cancel_signal

    cancel_signal.reset_all_for_tests()

    get_response = MagicMock()
    get_response.status_code = 200
    get_response.text = _make_wait_page_html(60)
    get_response.headers = {}

    post_response = MagicMock()
    post_response.status_code = 302
    post_response.text = ""
    post_response.headers = {"Location": "https://a-2.1fichier.com/p1/file.bin"}

    scraper = MagicMock()
    scraper.cookies = []
    scraper.get.return_value = get_response
    scraper.post.return_value = post_response

    monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)
    monkeypatch.setattr(sp.time, "sleep", lambda s: None)
    # Event.wait belongs to the threading module — patching time.sleep does not
    # affect it, so patch it to return timeout (False) immediately.
    monkeypatch.setattr(threading.Event, "wait",
                        lambda self, timeout=None: self.is_set())

    sse_messages = []

    def sse_cb(msg_type, payload):
        sse_messages.append((msg_type, payload))

    try:
        sp.parse_1fichier_simple_sync(
            "https://1fichier.com/?abc",
            password=None,
            proxies=None,
            proxy_addr=None,
            download_id=42,
            sse_callback=sse_cb,
        )
    finally:
        cancel_signal.reset_all_for_tests()

    types = [m[0] for m in sse_messages]
    assert "status_update" in types
    assert any(t == "waiting" for t in types)


def test_parse_simple_sync_returns_none_when_stopped_during_wait(monkeypatch):
    """If cancel_signal is set during the wait, return None (no DB polling)."""
    from core import cancel_signal

    get_response = MagicMock()
    get_response.status_code = 200
    get_response.text = _make_wait_page_html(60)
    get_response.headers = {}

    scraper = MagicMock()
    scraper.cookies = []
    scraper.get.return_value = get_response

    monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)

    # If the cancel signal is set *before* entering the countdown, get_event
    # returns an already-set Event, so the first wait call wakes immediately as True.
    cancel_signal.reset_all_for_tests()
    cancel_signal.signal_cancel(42)

    try:
        result = sp.parse_1fichier_simple_sync(
            "https://1fichier.com/?abc",
            download_id=42,
        )
        assert result is None
    finally:
        cancel_signal.reset_all_for_tests()


# ---------------------------------------------------------------------------
# Cloudflare → FlareSolverr fallback
# ---------------------------------------------------------------------------


class _FakeCookieJar(list):
    """List-backed cookie jar that also supports the requests ``set`` API."""

    def set(self, name, value, domain=None):
        cookie = MagicMock()
        cookie.name = name
        cookie.value = value
        self.append(cookie)


class TestIsCloudflareBlock:
    def test_detects_cf_mitigated_header(self):
        resp = MagicMock()
        resp.headers = {"cf-mitigated": "challenge"}
        resp.text = ""
        assert sp._is_cloudflare_block(resp) is True

    def test_detects_challenge_body(self):
        resp = MagicMock()
        resp.headers = {}
        resp.text = "<html><title>Just a moment...</title>cf_chl</html>"
        assert sp._is_cloudflare_block(resp) is True

    def test_normal_page_is_not_a_block(self):
        resp = MagicMock()
        resp.headers = {}
        resp.text = "<html><body>file.bin</body></html>"
        assert sp._is_cloudflare_block(resp) is False


def test_cloudflare_block_falls_back_to_flaresolverr(monkeypatch):
    """A CF challenge on the first GET triggers a FlareSolverr cookie fetch and a retry."""
    cf_response = MagicMock()
    cf_response.status_code = 403
    cf_response.text = "<html><title>Just a moment...</title></html>"
    cf_response.headers = {"cf-mitigated": "challenge"}

    ok_response = MagicMock()
    ok_response.status_code = 200
    ok_response.text = _make_wait_page_html(30)
    ok_response.headers = {}

    post_response = MagicMock()
    post_response.status_code = 302
    post_response.text = ""
    post_response.headers = {"Location": "https://a-2.1fichier.com/p1/file.bin"}

    scraper = MagicMock()
    scraper.cookies = _FakeCookieJar()
    scraper.get.side_effect = [cf_response, ok_response]
    scraper.post.return_value = post_response

    monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)
    monkeypatch.setattr(sp.time, "sleep", lambda s: None)

    fs_calls = []

    def fake_fs(url, referer="", proxies=None):
        fs_calls.append(url)
        return {"cookies": {"cf_clearance": "tok"}, "user_agent": "Chrome/142"}

    monkeypatch.setattr(sp, "get_flaresolverr_context_for_url", fake_fs)

    result = sp.parse_1fichier_simple_sync(
        "https://1fichier.com/?abc",
        password=None, proxies=None, proxy_addr=None,
        download_id=None, sse_callback=None,
    )

    assert fs_calls, "FlareSolverr fallback was not invoked on a CF block"
    assert scraper.get.call_count == 2, "GET was not retried after obtaining CF cookies"
    assert result["download_link"].startswith("https://a-2.1fichier.com/")


def test_cloudflare_block_without_fs_cookies_does_not_retry(monkeypatch):
    """If FlareSolverr yields no cookies, no retry happens and the CF block surfaces."""
    cf_response = MagicMock()
    cf_response.status_code = 403
    cf_response.text = "<html><title>Attention Required! | Cloudflare</title></html>"
    cf_response.headers = {}

    scraper = MagicMock()
    scraper.cookies = _FakeCookieJar()
    scraper.get.return_value = cf_response

    monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)
    monkeypatch.setattr(
        sp, "get_flaresolverr_context_for_url",
        lambda url, referer="", proxies=None: {"cookies": {}, "user_agent": None},
    )

    with pytest.raises(Exception):
        sp.parse_1fichier_simple_sync(
            "https://1fichier.com/?abc",
            password=None, proxies=None, proxy_addr=None,
            download_id=None, sse_callback=None,
        )

    assert scraper.get.call_count == 1


# ---------------------------------------------------------------------------
# extract_file_info_simple — additional patterns
# ---------------------------------------------------------------------------


class TestExtractFileInfoExtra:
    def test_returns_none_when_html_invalid(self):
        # BeautifulSoup parses any input, so None is returned only for truly empty input.
        result = sp.extract_file_info_simple("")
        assert result is None or result == {}

    def test_size_parenthesis_pattern(self):
        html = """<html><body><p>file (12.5 GB)</p></body></html>"""
        info = sp.extract_file_info_simple(html)
        assert info is not None
        assert "GB" in info.get("size", "")
