# -*- coding: utf-8 -*-
"""``simulate_download_click`` / ``parse_1fichier_simple_sync`` /
``preparse_1fichier_standalone`` 의 행위를 cloudscraper 응답을 모킹해서 검증.
"""

from unittest.mock import MagicMock, patch

import pytest

from core import simple_parser as sp


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
        """Location 이 1fichier 메인 페이지면 다운로드 링크로 인식하면 안 된다."""
        scraper, _ = _make_scraper_with_post_response(
            status=302,
            location="https://1fichier.com/?abc",
            text="",  # 본문 없음
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
        """첫 POST 응답에 추가 대기시간 표시가 있으면 한 번 더 POST 한다."""

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
        """200 인데 후보를 찾을 수 없으면 디버그 단서 포함된 메시지로 raise."""
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
        # 디버깅에 필요한 단서가 메시지에 포함돼야 함
        assert "POST status=200" in msg
        assert "title=" in msg
        assert "forms=" in msg
        assert "a_tags=" in msg

    def test_post_response_with_block_reason_raises_block_message(self):
        """POST 응답이 차단 페이지면 ``1fichier 차단`` 으로 raise."""
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

    def test_post_response_returning_homepage_raises_form_rejection(self):
        """차단 메시지 없이 홈페이지가 반환된 케이스 — 폼 제출 거부로 분류."""
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
    """``cloudscraper.create_scraper`` 가 항상 같은 가짜 객체를 반환하게 한다."""

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

    # GET 호출 캡처
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
    # 1) 첫 GET 응답 (대기페이지) 모킹 — 대기시간 없음
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

    # 2) POST 응답 (다운로드 링크 리다이렉트) 모킹
    post_response = MagicMock()
    post_response.status_code = 302
    post_response.text = ""
    post_response.headers = {"Location": "https://a-3.1fichier.com/ptoken/movie.mkv"}
    post_response.url = "https://1fichier.com/?abc"

    # 쿠키
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
