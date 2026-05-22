# -*- coding: utf-8 -*-
"""MegaUp/DataNodes 등 사이트별 호스팅 파서 테스트."""

import pytest

from core import hoster_parsers as hp


class _FakeCookies:
    def get_dict(self):
        return {"sid": "cookie"}


class _FakeResponse:
    def __init__(self, text="", status_code=200, headers=None):
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}


class _FakeScraper:
    def __init__(self, get_response=None, post_response=None):
        self.headers = {}
        self.cookies = _FakeCookies()
        self.get_response = get_response or _FakeResponse()
        self.post_response = post_response or _FakeResponse()
        self.captured_post = None

    def get(self, *args, **kwargs):
        return self.get_response

    def post(self, *args, **kwargs):
        self.captured_post = {"args": args, "kwargs": kwargs}
        return self.post_response


def test_megaup_parser_extracts_file_info_and_download_link(monkeypatch):
    html = """
    <html>
      <head><title>IRISFAL.rar - MegaUp</title></head>
      <body>
        <h2>IRISFAL.rar</h2>
        <strong>IRISFAL.rar (2.19 GB)</strong>
        <script>
          $('.download-timer').html("<a class='btn btn--primary'
            href='https://download.megaup.net/?url=abc123'><span>DOWNLOAD</span></a>");
        </script>
      </body>
    </html>
    """
    monkeypatch.setattr(
        hp.cloudscraper,
        "create_scraper",
        lambda: _FakeScraper(get_response=_FakeResponse(html)),
    )
    monkeypatch.setattr(
        hp,
        "_resolve_megaup_final_link",
        lambda link, **kwargs: (link, kwargs["cookies"], kwargs["user_agent"], kwargs["referer"]),
    )

    result = hp.parse_megaup_sync("https://megaup.net/id/IRISFAL.rar")

    assert result["download_link"] == "https://download.megaup.net/?url=abc123"
    assert result["file_info"] == {"name": "IRISFAL.rar", "size": "2.19 GB"}
    assert result["wait_time"] == 2
    assert result["cookies"] == {"sid": "cookie"}


def test_megaup_resolver_follows_download_token_page(monkeypatch):
    captured = {}
    html = """
    <html><title>Download Page - MegaUp</title>
      <a href="https://megadl.boats/download/movie.rar?download_token=tok">click here</a>
    </html>
    """

    class _Resp:
        text = html
        url = "https://download.megaup.net/?url=abc"
        headers = {"Content-Type": "text/html; charset=UTF-8"}

        def close(self):
            pass

    def fake_get(url, headers, cookies, timeout, allow_redirects, stream):
        captured.update({"url": url, "headers": headers, "cookies": cookies, "stream": stream})
        return _Resp()

    monkeypatch.setattr(
        hp,
        "get_flaresolverr_context_for_url",
        lambda url, referer="": {"cookies": {"cf_clearance": "ok"}, "user_agent": "Chrome/142"},
    )
    monkeypatch.setattr(hp.requests, "get", fake_get)

    final_link, cookies, user_agent, referer = hp._resolve_megaup_final_link(
        "https://download.megaup.net/?url=abc",
        referer="https://megaup.net/id/movie.rar",
        cookies={"sid": "cookie"},
        user_agent="Chrome/125",
    )

    assert final_link == "https://megadl.boats/download/movie.rar?download_token=tok"
    assert cookies == {"sid": "cookie", "cf_clearance": "ok"}
    assert user_agent == "Chrome/142"
    assert referer == "https://download.megaup.net/?url=abc"
    assert captured["stream"] is True


def test_megaup_parser_reports_dead_page(monkeypatch):
    monkeypatch.setattr(
        hp.cloudscraper,
        "create_scraper",
        lambda: _FakeScraper(get_response=_FakeResponse("File Not Found", 404)),
    )

    with pytest.raises(hp.HosterParseError, match="MegaUp 파일 없음"):
        hp.parse_megaup_sync("https://megaup.net/dead/file.rar")


def test_datanodes_parser_posts_download2_and_uses_redirect(monkeypatch):
    page = """
    <html>
      <title>Download File</title><span>popup limit 2 MB</span><strong>movie.rar 2.19 GB</strong>
      <input type="hidden" name="rand" value="abc-rand">
    </html>
    """
    fake = _FakeScraper(
        get_response=_FakeResponse(page),
        post_response=_FakeResponse("", 302, headers={"Location": "https://cdn.datanodes.to/file.rar"}),
    )
    monkeypatch.setattr(hp.cloudscraper, "create_scraper", lambda: fake)

    result = hp.parse_datanodes_sync(
        "https://datanodes.to/f0mley3vka9k/IRISFAL-NSwTcH-%5BBASE%5D.rar"
    )

    assert result["download_link"] == "https://cdn.datanodes.to/file.rar"
    assert result["file_info"]["name"] == "IRISFAL-NSwTcH-[BASE].rar"
    assert result["file_info"]["size"] == "2.19 GB"
    post_kwargs = fake.captured_post["kwargs"]
    posted = {key: value for key, (_, value) in post_kwargs["files"].items()}
    assert posted["op"] == "download2"
    assert posted["id"] == "f0mley3vka9k"
    assert posted["rand"] == "abc-rand"
    assert "file_code=f0mley3vka9k" in post_kwargs["headers"]["Cookie"]


def test_datanodes_parser_follows_download1_countdown_json(monkeypatch):
    page = """
    <html>
      <form>
        <input type="hidden" name="op" value="download1">
        <input type="hidden" name="id" value="f0mley3vka9k">
        <input type="hidden" name="fname" value="movie.rar">
        <input type="hidden" name="referer" value="">
        <button name="method_free" value="Free Download >>">Continue</button>
      </form>
    </html>
    """
    countdown = """
    <html>
      <download-countdown code="f0mley3vka9k" referer="https://datanodes.to/download"
        rand="abc-rand" free-method="Free Download &gt;&gt;" premium-method="">
      </download-countdown>
    </html>
    """

    class QueueScraper(_FakeScraper):
        def __init__(self):
            super().__init__(get_response=_FakeResponse(page))
            self.posts = []

        def post(self, *args, **kwargs):
            self.posts.append({"args": args, "kwargs": kwargs})
            if len(self.posts) == 1:
                return _FakeResponse(countdown)
            return _FakeResponse('{"url":"https%3A%2F%2Ftunnel5.dlproxy.uk%2Fdownload%2Fmovie.rar%3Fsig%3Dabc"}')

    fake = QueueScraper()
    monkeypatch.setattr(hp.cloudscraper, "create_scraper", lambda: fake)

    result = hp.parse_datanodes_sync("https://datanodes.to/f0mley3vka9k/movie.rar")

    assert result["download_link"] == "https://tunnel5.dlproxy.uk/download/movie.rar?sig=abc"
    assert fake.posts[0]["kwargs"]["data"]["op"] == "download1"
    posted = {key: value for key, (_, value) in fake.posts[1]["kwargs"]["files"].items()}
    assert posted["op"] == "download2"
    assert posted["rand"] == "abc-rand"
    assert posted["g_captch__a"] == "1"


def test_datanodes_parser_rejects_homepage_as_download_link(monkeypatch):
    fake = _FakeScraper(
        get_response=_FakeResponse("<html><strong>movie.rar 2 MB</strong></html>"),
        post_response=_FakeResponse("<a href='https://datanodes.to/'>Download</a>", 200),
    )
    monkeypatch.setattr(hp.cloudscraper, "create_scraper", lambda: fake)

    with pytest.raises(hp.HosterParseError, match="다운로드 링크를 찾을 수 없음"):
        hp.parse_datanodes_sync("https://datanodes.to/f0mley3vka9k/movie.rar")


def test_rapidgator_large_free_file_is_reported_as_premium_required(monkeypatch):
    html = """
    <html><body>
      <p><strong>Downloading:</strong> big.rar</p>
      <div>File size: <strong>2.19 GB</strong></div>
      <div>You can download files up to 500 MB in free mode</div>
    </body></html>
    """
    monkeypatch.setattr(
        hp.cloudscraper,
        "create_scraper",
        lambda: _FakeScraper(get_response=_FakeResponse(html)),
    )

    with pytest.raises(hp.HosterParseError, match="500 MB 초과"):
        hp.parse_rapidgator_constraints_sync("https://rapidgator.net/file/abc/big.rar.html")


def test_blocked_hosts_are_identified():
    assert hp.is_special_hoster_url("https://gofile.io/d/abc") is True
    assert hp.is_special_hoster_url("https://send.now/abc") is True
    with pytest.raises(hp.HosterParseError, match="Gofile"):
        hp.parse_special_hoster_sync("https://gofile.io/d/abc")


def test_flaresolverr_cookie_bootstrap_uses_origin_not_file_url(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "status": "ok",
                "solution": {
                    "userAgent": "Chrome/142",
                    "cookies": [{"name": "cf_clearance", "value": "ok"}],
                },
            }

    def fake_post(url, json, timeout):
        captured["payload"] = json
        return _Resp()

    monkeypatch.setattr(hp.requests, "post", fake_post)

    context = hp.get_flaresolverr_context_for_url(
        "https://download.megaup.net/?url=large-file-token",
        referer="https://megaup.net/file",
    )

    assert context == {"cookies": {"cf_clearance": "ok"}, "user_agent": "Chrome/142"}
    assert hp.get_flaresolverr_cookies_for_url("not a url") == {}
    assert captured["payload"]["url"] == "https://download.megaup.net/"
    assert "large-file-token" not in captured["payload"]["url"]


def test_sendnow_uses_flaresolverr_page_when_available(monkeypatch):
    html = """
    <html>
      <h1>movie.rar</h1>
      <a href="https://cdn.send.now/movie.rar">Download now</a>
    </html>
    """

    monkeypatch.setattr(
        hp,
        "_get_page_with_flaresolverr",
        lambda url, referer="": (html, {"cf_clearance": "ok"}, url),
    )

    result = hp.parse_special_hoster_sync("https://send.now/abc")

    assert result["download_link"] == "https://cdn.send.now/movie.rar"
    assert result["cookies"] == {"cf_clearance": "ok"}
    assert result["file_info"]["name"] == "movie.rar"


def test_sendnow_turnstile_is_reported_after_flaresolverr(monkeypatch):
    html = """
    <html>
      <title>Download Challenge</title>
      <form><input name="cf-turnstile-response"></form>
    </html>
    """

    monkeypatch.setattr(
        hp,
        "_get_page_with_flaresolverr",
        lambda url, referer="": (html, {"cf_clearance": "ok"}, url),
    )

    with pytest.raises(hp.HosterParseError, match="Turnstile 검증 필요"):
        hp.parse_special_hoster_sync("https://send.now/abc")
