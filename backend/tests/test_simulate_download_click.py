# -*- coding: utf-8 -*-
"""Verifies the behavior of ``simulate_download_click`` /
``parse_1fichier_simple_sync`` / ``preparse_1fichier_standalone`` by mocking
cloudscraper responses.
"""

from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from core import simple_parser as sp


# ---------------------------------------------------------------------------
# _collect_form_data
# ---------------------------------------------------------------------------


def _form(html):
    return BeautifulSoup(html, "html.parser").find("form")


class TestCollectFormData:
    def test_excludes_save_submit_button_for_registered_user(self):
        """The 'Save on my account' submit on a registered-user form must not enter form_data.
        A real browser includes only the clicked submit (download is JS-triggered, so no submit).
        """
        form = _form("""
            <form id="f1">
              <input type="submit" name="save" value="Save on my account">
              <input type="checkbox" name="dl_no_ssl">
              <input type="checkbox" name="dlinline">
            </form>
        """)
        data = sp._collect_form_data(form, password=None)
        assert "save" not in data, "save submit 은 절대 포함되면 안 됨"

    def test_excludes_unchecked_checkboxes(self):
        """Browsers do not send unchecked checkboxes, so exclude them from form_data too."""
        form = _form("""
            <form id="f1">
              <input type="checkbox" name="dl_no_ssl">
              <input type="checkbox" name="dlinline">
              <input type="checkbox" name="use_credits">
            </form>
        """)
        assert sp._collect_form_data(form, password=None) == {}

    def test_includes_checked_checkboxes(self):
        form = _form("""
            <form id="f1">
              <input type="checkbox" name="dl_no_ssl" checked>
              <input type="checkbox" name="dlinline" checked value="yes">
            </form>
        """)
        data = sp._collect_form_data(form, password=None)
        assert data == {"dl_no_ssl": "on", "dlinline": "yes"}

    def test_includes_hidden_fields(self):
        form = _form("""
            <form id="f1">
              <input type="hidden" name="adz" value="adv-token-123">
              <input type="hidden" name="csrf" value="">
            </form>
        """)
        data = sp._collect_form_data(form, password=None)
        assert data["adz"] == "adv-token-123"
        # Hidden fields must be included even with an empty value
        assert "csrf" in data

    def test_includes_password_when_provided(self):
        form = _form("""
            <form id="f1">
              <input type="password" name="pass" value="">
            </form>
        """)
        data = sp._collect_form_data(form, password="secret")
        assert data["pass"] == "secret"

    def test_skips_password_when_not_provided(self):
        form = _form("""
            <form id="f1">
              <input type="password" name="pass" value="">
            </form>
        """)
        # If password is None, this is not a password-protected file — do not send it
        data = sp._collect_form_data(form, password=None)
        assert data == {}

    def test_skips_inputs_without_name(self):
        form = _form("""
            <form id="f1">
              <input type="hidden" value="orphan">
              <input type="hidden" name="ok" value="ok">
            </form>
        """)
        assert sp._collect_form_data(form, password=None) == {"ok": "ok"}

    def test_does_not_auto_inject_submit_field(self):
        """Guards against a regression of the old auto-add ``submit=Download`` behavior."""
        form = _form("""
            <form id="f1">
              <input type="checkbox" name="dl_no_ssl">
            </form>
        """)
        data = sp._collect_form_data(form, password=None)
        assert "submit" not in data
        assert data == {}

    def test_real_registered_user_form_only_yields_empty_dict(self):
        """A form structure captured from a real 1fichier registered-user GET page —
        if nothing is checked/entered, form_data must be empty (the behavior when
        the browser clicks #dlw → JS submit).
        """
        form = _form("""
            <form id="f1" method="post" action="https://1fichier.com/?abc">
              <select id="did" name="did"><option value="0">Root</option></select>
              <input type="submit" name="save" value="Save on my account">
              <input type="checkbox" name="dl_no_ssl">
              <input type="checkbox" name="dlinline">
              <input type="checkbox" name="use_credits">
            </form>
        """)
        # select is not an input, so _collect_form_data does not handle it.
        # If select handling is added later, this test must be updated too.
        assert sp._collect_form_data(form, password=None) == {}


# ---------------------------------------------------------------------------
# simulate_download_click
# ---------------------------------------------------------------------------


def _make_scraper_with_post_response(*, status, text="", location=None):
    scraper = MagicMock()
    response = MagicMock()
    response.status_code = status
    response.text = text
    response.headers = {}
    if location is not None:
        response.headers["Location"] = location
    response.url = "https://1fichier.com/?abc"
    scraper.post.return_value = response
    return scraper, response


WAIT_PAGE_HTML = """
<html><body>
    <form id="f1" method="post">
        <input type="hidden" name="adz" value="adv-token">
        <input type="submit" name="submit" value="Click">
    </form>
</body></html>
"""


class TestSimulateDownloadClick:
    def test_returns_redirect_location_when_download_host(self):
        scraper, _ = _make_scraper_with_post_response(
            status=302,
            location="https://a-1.1fichier.com/p7token/movie.mkv",
        )

        link = sp.simulate_download_click(
            scraper,
            "https://1fichier.com/?abc",
            WAIT_PAGE_HTML,
            None,
            {"User-Agent": "UA"},
            None,
        )
        assert link == "https://a-1.1fichier.com/p7token/movie.mkv"

    def test_redirect_to_homepage_is_rejected(self):
        """If Location is the 1fichier main page, it must not be recognized as a download link."""
        scraper, _ = _make_scraper_with_post_response(
            status=302,
            location="https://1fichier.com/?abc",
            text="",  # no body
        )

        with pytest.raises(Exception):
            sp.simulate_download_click(
                scraper,
                "https://1fichier.com/?abc",
                WAIT_PAGE_HTML,
                None,
                {"User-Agent": "UA"},
                None,
            )

    def test_returns_link_from_html_response_when_no_redirect(self):
        success_html = """
        <html><body>
            <a href="https://a-2.1fichier.com/p1abc/file.zip">Click here to download</a>
        </body></html>
        """
        scraper, _ = _make_scraper_with_post_response(status=200, text=success_html)

        link = sp.simulate_download_click(
            scraper,
            "https://1fichier.com/?abc",
            WAIT_PAGE_HTML,
            None,
            {"User-Agent": "UA"},
            None,
        )
        assert link == "https://a-2.1fichier.com/p1abc/file.zip"

    def test_raises_when_no_form(self):
        scraper, _ = _make_scraper_with_post_response(status=200)
        with pytest.raises(Exception, match="다운로드 폼"):
            sp.simulate_download_click(
                scraper,
                "https://1fichier.com/?abc",
                "<html><body>no form here</body></html>",
                None,
                {"User-Agent": "UA"},
                None,
            )

    def test_form_post_uses_origin_and_referer(self):
        success_html = """<html><body>
        <a href="https://a-2.1fichier.com/p1abc/file.zip">Download</a>
        </body></html>"""
        scraper, _ = _make_scraper_with_post_response(status=200, text=success_html)

        sp.simulate_download_click(
            scraper,
            "https://1fichier.com/?abc",
            WAIT_PAGE_HTML,
            None,
            {"User-Agent": "UA"},
            None,
        )

        call = scraper.post.call_args
        post_headers = call.kwargs["headers"]
        assert post_headers["Origin"] == "https://1fichier.com"
        assert post_headers["Referer"] == "https://1fichier.com/?abc"
        assert post_headers["Content-Type"] == "application/x-www-form-urlencoded"

    def test_password_is_sent_in_form_when_present(self):
        password_form_html = """<html><body>
        <form id="f1">
          <input type="password" name="pass" value="">
          <input type="hidden" name="adz" value="abc">
        </form>
        </body></html>"""
        success_html = """<html><body>
        <a href="https://a-2.1fichier.com/p1abc/file.zip">Download</a>
        </body></html>"""
        scraper, _ = _make_scraper_with_post_response(status=200, text=success_html)

        sp.simulate_download_click(
            scraper,
            "https://1fichier.com/?abc",
            password_form_html,
            password="my-secret",
            headers={"User-Agent": "UA"},
            proxies=None,
        )

        call = scraper.post.call_args
        assert call.kwargs["data"].get("pass") == "my-secret"

    def test_additional_wait_time_triggers_retry_post(self, monkeypatch):
        """If the first POST response indicates an additional wait time, POST once more."""

        first_response = MagicMock()
        first_response.status_code = 200
        first_response.text = "<html><body><script>var ct = 60;</script></body></html>"
        first_response.headers = {}

        retry_response = MagicMock()
        retry_response.status_code = 302
        retry_response.text = ""
        retry_response.headers = {"Location": "https://a-1.1fichier.com/ptoken/file.bin"}

        scraper = MagicMock()
        scraper.post.side_effect = [first_response, retry_response]

        monkeypatch.setattr(sp.time, "sleep", lambda s: None)

        link = sp.simulate_download_click(
            scraper,
            "https://1fichier.com/?abc",
            WAIT_PAGE_HTML,
            None,
            {"User-Agent": "UA"},
            None,
        )
        assert link == "https://a-1.1fichier.com/ptoken/file.bin"
        assert scraper.post.call_count == 2

    def test_unknown_response_raises_link_not_found_with_diagnostics(self):
        """On a 200 with no candidate found, raise with a message that includes debug clues."""
        scraper, _ = _make_scraper_with_post_response(
            status=200,
            text="<html><head><title>Unexpected page</title></head><body><a href='/foo'>foo</a></body></html>",
        )
        with pytest.raises(Exception) as excinfo:
            sp.simulate_download_click(
                scraper,
                "https://1fichier.com/?abc",
                WAIT_PAGE_HTML,
                None,
                {"User-Agent": "UA"},
                None,
            )
        msg = str(excinfo.value)
        assert "다운로드 링크를 찾을 수 없음" in msg
        # The message must include the clues needed for debugging
        assert "POST status=200" in msg
        assert "title=" in msg
        assert "forms=" in msg
        assert "a_tags=" in msg

    def test_post_response_with_block_reason_raises_block_message(self):
        """If the POST response is a block page, raise as ``1fichier 차단``."""
        scraper, _ = _make_scraper_with_post_response(
            status=200,
            text="<html><body>Accès restreint – professional infrastructure detected.</body></html>",
        )
        with pytest.raises(Exception, match="1fichier 차단"):
            sp.simulate_download_click(
                scraper,
                "https://1fichier.com/?abc",
                WAIT_PAGE_HTML,
                None,
                {"User-Agent": "UA"},
                None,
            )

    def test_retry_loop_succeeds_within_max_attempts(self, monkeypatch):
        """First and second attempts are wait pages; the third attempt yields the download link."""
        wait_page = "<html><body><script>var ct = 60;</script><form id='f1'></form></body></html>"

        wait1 = MagicMock(); wait1.status_code = 200; wait1.text = wait_page; wait1.headers = {}
        wait2 = MagicMock(); wait2.status_code = 200; wait2.text = wait_page; wait2.headers = {}
        success = MagicMock()
        success.status_code = 302
        success.text = ""
        success.headers = {"Location": "https://a-1.1fichier.com/ptoken/file.bin"}

        scraper = MagicMock()
        scraper.post.side_effect = [wait1, wait2, success]

        monkeypatch.setattr(sp.time, "sleep", lambda s: None)

        link = sp.simulate_download_click(
            scraper, "https://1fichier.com/?abc", WAIT_PAGE_HTML,
            None, {"User-Agent": "UA"}, None,
        )
        assert link == "https://a-1.1fichier.com/ptoken/file.bin"
        assert scraper.post.call_count == 3, "MAX_POST_ATTEMPTS=3 안에서 성공해야 함"

    def test_retry_loop_stops_at_max_attempts(self, monkeypatch):
        """On reaching MAX_POST_ATTEMPTS, stop trying and raise with a diagnostic message."""
        wait_page = "<html><body><script>var ct = 60;</script><form id='f1'></form></body></html>"

        responses = []
        for _ in range(sp.MAX_POST_ATTEMPTS + 2):
            r = MagicMock()
            r.status_code = 200
            r.text = wait_page
            r.headers = {}
            responses.append(r)

        scraper = MagicMock()
        scraper.post.side_effect = responses

        monkeypatch.setattr(sp.time, "sleep", lambda s: None)

        with pytest.raises(Exception):
            sp.simulate_download_click(
                scraper, "https://1fichier.com/?abc", WAIT_PAGE_HTML,
                None, {"User-Agent": "UA"}, None,
            )
        assert scraper.post.call_count == sp.MAX_POST_ATTEMPTS, \
            "정확히 MAX_POST_ATTEMPTS 만큼만 시도해야 함"

    def test_retry_wait_aborts_on_cancel_signal(self, monkeypatch):
        """If the cancel signal is set during the extra_wait sleep between retries, abort immediately."""
        import threading
        from core import cancel_signal

        cancel_signal.reset_all_for_tests()

        wait_page = "<html><body><script>var ct = 60;</script><form id='f1'></form></body></html>"
        wait_resp = MagicMock()
        wait_resp.status_code = 200
        wait_resp.text = wait_page
        wait_resp.headers = {}

        scraper = MagicMock()
        scraper.post.return_value = wait_resp

        # Scenario where the cancel signal is set right after the first POST —
        # patch Event.wait to return True immediately (True only when set)
        monkeypatch.setattr(sp.time, "sleep", lambda s: None)
        monkeypatch.setattr(threading.Event, "wait",
                            lambda self, timeout=None: self.is_set())
        cancel_signal.signal_cancel(99)

        try:
            with pytest.raises(Exception, match="사용자 정지"):
                sp.simulate_download_click(
                    scraper, "https://1fichier.com/?abc", WAIT_PAGE_HTML,
                    None, {"User-Agent": "UA"}, None,
                    download_id=99, sse_callback=None,
                )
            # Only the first POST runs, then cancel right after entering retry
            assert scraper.post.call_count == 1
        finally:
            cancel_signal.reset_all_for_tests()

    def test_retry_loop_stops_early_when_no_extra_wait(self):
        """If the response is a plain failure rather than a wait page, abort immediately — avoids pointless retries."""
        scraper, _ = _make_scraper_with_post_response(
            status=200,
            text="<html><head><title>Unexpected</title></head><body></body></html>",
        )
        with pytest.raises(Exception):
            sp.simulate_download_click(
                scraper, "https://1fichier.com/?abc", WAIT_PAGE_HTML,
                None, {"User-Agent": "UA"}, None,
            )
        assert scraper.post.call_count == 1, "추가 대기시간 없으면 1번만 시도"

    def test_post_response_returning_homepage_raises_form_rejection(self):
        """Case where the homepage is returned without a block message — classified as form-submit rejection."""
        homepage = """
        <html>
          <head><title>1fichier.com: Cloud Storage</title></head>
          <body>
            <a href="/">Home</a>
            <a href="/tarifs.html">Prices</a>
            <a href="/register.pl">Register</a>
          </body>
        </html>
        """
        scraper, _ = _make_scraper_with_post_response(status=200, text=homepage)
        with pytest.raises(Exception) as excinfo:
            sp.simulate_download_click(
                scraper,
                "https://1fichier.com/?abc",
                WAIT_PAGE_HTML,
                None,
                {"User-Agent": "UA"},
                None,
            )
        msg = str(excinfo.value)
        assert "폼 제출 거부" in msg
        assert "POST status=200" in msg


# ---------------------------------------------------------------------------
# parse_1fichier_simple_sync
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_scraper_class(monkeypatch):
    """Make ``cloudscraper.create_scraper`` always return the same fake object."""

    fakes = []

    def factory(**kwargs):
        scraper = MagicMock()
        scraper.cookies = []
        fakes.append(scraper)
        return scraper

    monkeypatch.setattr(sp.cloudscraper, "create_scraper", factory)
    return fakes


def test_parse_simple_sync_raises_on_404_with_clear_message(fake_scraper_class):
    response = MagicMock()
    response.status_code = 404
    response.text = "<html>not found</html>"
    response.headers = {}

    # Capture the GET call
    def make_scraper(**kwargs):
        s = MagicMock()
        s.cookies = []
        s.get.return_value = response
        fake_scraper_class.append(s)
        return s

    with patch.object(sp.cloudscraper, "create_scraper", side_effect=make_scraper):
        with pytest.raises(Exception, match="HTTP 404"):
            sp.parse_1fichier_simple_sync("https://1fichier.com/?abc")


def test_parse_simple_sync_returns_session_context_on_success(monkeypatch):
    # 1) Mock the first GET response (wait page) — no wait time
    success_html = """
    <html><body>
        <table>
            <tr>
                <td><img src="/qr.pl?key=1"></td>
                <td class="normal">
                    <span style="font-weight:bold">movie.mkv</span>
                    <br>
                    <span style="font-size:0.9em;font-style:italic">1 GB</span>
                </td>
            </tr>
        </table>
        <form id="f1"><input type="hidden" name="adz" value="x"></form>
    </body></html>
    """
    get_response = MagicMock()
    get_response.status_code = 200
    get_response.text = success_html
    get_response.headers = {}

    # 2) Mock the POST response (download-link redirect)
    post_response = MagicMock()
    post_response.status_code = 302
    post_response.text = ""
    post_response.headers = {"Location": "https://a-3.1fichier.com/ptoken/movie.mkv"}
    post_response.url = "https://1fichier.com/?abc"

    # Cookies
    cookie = MagicMock()
    cookie.name = "PHPSESSID"
    cookie.value = "cookieval"

    scraper = MagicMock()
    scraper.cookies = [cookie]
    scraper.get.return_value = get_response
    scraper.post.return_value = post_response

    monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)

    result = sp.parse_1fichier_simple_sync("https://1fichier.com/?abc")
    assert result["download_link"] == "https://a-3.1fichier.com/ptoken/movie.mkv"
    assert result["file_info"]["name"] == "movie.mkv"
    assert result["cookies"] == {"PHPSESSID": "cookieval"}
    assert result["user_agent"]
    assert result["referer"].startswith("https://1fichier.com/")


# ---------------------------------------------------------------------------
# preparse_1fichier_standalone
# ---------------------------------------------------------------------------


def test_preparse_returns_none_for_non_1fichier_url():
    assert sp.preparse_1fichier_standalone("https://example.com/abc") is None


def test_preparse_returns_none_when_status_not_200(monkeypatch):
    response = MagicMock()
    response.status_code = 404
    response.text = ""

    scraper = MagicMock()
    scraper.get.return_value = response
    monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)

    assert sp.preparse_1fichier_standalone("https://1fichier.com/?abc") is None


def test_preparse_returns_file_info_on_success(monkeypatch):
    response = MagicMock()
    response.status_code = 200
    response.text = """
    <html><body>
        <table>
            <tr>
                <td><img src="/qr.pl?k=1"></td>
                <td class="normal">
                    <span style="font-weight:bold">archive.zip</span>
                    <br>
                    <span style="font-size:0.9em;font-style:italic">512 MB</span>
                </td>
            </tr>
        </table>
    </body></html>
    """

    scraper = MagicMock()
    scraper.get.return_value = response
    monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)

    info = sp.preparse_1fichier_standalone("https://1fichier.com/?abc&af=1")
    assert info["name"] == "archive.zip"
    assert info["size"] == "512 MB"
