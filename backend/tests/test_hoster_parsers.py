# -*- coding: utf-8 -*-
"""Tests for per-site hoster parsers such as MegaUp/DataNodes."""

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


def _patch_gofile_tokens(monkeypatch):
    monkeypatch.setattr(hp, "_gofile_session", lambda: object())
    monkeypatch.setattr(hp, "_gofile_guest_token", lambda session: "guest-tok")


def test_gofile_content_id_extraction():
    assert hp._gofile_content_id("https://gofile.io/d/6uARDV") == "6uARDV"
    assert hp._gofile_content_id("https://gofile.io/6uARDV") == "6uARDV"
    assert hp._gofile_content_id("https://gofile.io/d/6uARDV/") == "6uARDV"
    assert hp._gofile_content_id("https://gofile.io/") == ""


def test_gofile_single_file_resolves_direct_link(monkeypatch):
    _patch_gofile_tokens(monkeypatch)
    contents = {
        "status": "ok",
        "data": {
            "type": "folder",
            "children": {
                "abc": {
                    "type": "file",
                    "name": "movie.rar",
                    "size": 2353388182,
                    "link": "https://store1.gofile.io/download/abc/movie.rar",
                },
            },
        },
    }
    monkeypatch.setattr(hp, "_gofile_fetch_contents", lambda *a, **k: contents)

    result = hp.parse_special_hoster_sync("https://gofile.io/d/6uARDV")

    assert result["download_link"] == "https://store1.gofile.io/download/abc/movie.rar"
    assert result["cookies"] == {"accountToken": "guest-tok"}
    assert result["file_info"]["name"] == "movie.rar"
    assert result["file_info"]["size"] == "2.19 GB"


def test_gofile_top_level_file_resolves_direct_link(monkeypatch):
    _patch_gofile_tokens(monkeypatch)
    contents = {
        "status": "ok",
        "data": {
            "type": "file",
            "name": "single.zip",
            "link": "https://store2.gofile.io/download/xyz/single.zip",
        },
    }
    monkeypatch.setattr(hp, "_gofile_fetch_contents", lambda *a, **k: contents)

    result = hp.parse_special_hoster_sync("https://gofile.io/d/abc")

    assert result["download_link"] == "https://store2.gofile.io/download/xyz/single.zip"
    assert result["file_info"]["name"] == "single.zip"


def test_gofile_datacenter_ip_block_is_reported(monkeypatch):
    _patch_gofile_tokens(monkeypatch)
    monkeypatch.setattr(
        hp, "_gofile_fetch_contents",
        lambda *a, **k: {"status": "error-notPremium", "data": {}},
    )

    with pytest.raises(hp.HosterParseError, match="목록 조회 차단"):
        hp.parse_special_hoster_sync("https://gofile.io/d/6uARDV")


def test_gofile_contents_call_omits_wt_and_uses_web_params(monkeypatch):
    captured = {}

    class _Resp:
        def json(self):
            return {"status": "ok", "data": {"type": "file", "name": "f.bin",
                                             "link": "https://store.gofile.io/download/web/x/f.bin"}}

    class _Sess:
        headers = {}

        def get(self, url, params=None, headers=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(hp, "_gofile_session", lambda: _Sess())
    monkeypatch.setattr(hp, "_gofile_guest_token", lambda session: "guest-tok")

    hp.parse_special_hoster_sync("https://gofile.io/d/abc")

    assert "wt" not in (captured["params"] or {})
    assert captured["params"]["pageSize"] == "1000"
    assert captured["headers"]["Authorization"] == "Bearer guest-tok"


def test_gofile_missing_content_is_reported_as_dead(monkeypatch):
    _patch_gofile_tokens(monkeypatch)
    monkeypatch.setattr(
        hp, "_gofile_fetch_contents",
        lambda *a, **k: {"status": "error-notFound", "data": {}},
    )

    with pytest.raises(hp.HosterParseError, match="없음 또는 삭제"):
        hp.parse_special_hoster_sync("https://gofile.io/d/6uARDV")


def test_gofile_multi_file_folder_is_reported(monkeypatch):
    _patch_gofile_tokens(monkeypatch)
    contents = {
        "status": "ok",
        "data": {
            "type": "folder",
            "children": {
                "a": {"type": "file", "name": "a.rar", "link": "https://x/a"},
                "b": {"type": "file", "name": "b.rar", "link": "https://x/b"},
            },
        },
    }
    monkeypatch.setattr(hp, "_gofile_fetch_contents", lambda *a, **k: contents)

    with pytest.raises(hp.HosterParseError, match="여러 개"):
        hp.parse_special_hoster_sync("https://gofile.io/d/6uARDV")


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
