# -*- coding: utf-8 -*-
"""Tests for the newly-added hosters (Pixeldrain, MediaFire, Bunkr) and the
registry-driven dispatch that routes to them."""

import base64

import pytest

from core import hoster_parsers as hp
from core import hoster_sites as hs


# --- fakes ------------------------------------------------------------------

class _Resp:
    def __init__(self, text="", status_code=200, json_data=None, headers=None):
        self.text = text
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}

    def json(self):
        return self._json


class _FakeSession:
    def __init__(self, get_response):
        self.headers = {}
        self.proxies = {}
        self._get_response = get_response
        self.captured = {}

    def get(self, url, timeout=None, **kwargs):
        self.captured["url"] = url
        return self._get_response


class _FakeCookies:
    def get_dict(self):
        return {"sid": "cookie"}


class _FakeScraper:
    def __init__(self, get_response):
        self.headers = {}
        self.cookies = _FakeCookies()
        self._get_response = get_response

    def get(self, *args, **kwargs):
        return self._get_response


# --- Pixeldrain -------------------------------------------------------------

def test_pixeldrain_id_extraction():
    assert hs._pixeldrain_file_id("https://pixeldrain.com/u/AbCd123") == "AbCd123"
    assert hs._pixeldrain_file_id("https://pixeldrain.com/api/file/XyZ9") == "XyZ9"
    assert hs._pixeldrain_file_id("https://pixeldrain.com/") == ""


def test_pixeldrain_resolves_api_download_link(monkeypatch):
    info = {"success": True, "id": "AbCd", "name": "movie.mkv", "size": 123456789}
    session = _FakeSession(_Resp(json_data=info, status_code=200))
    monkeypatch.setattr(hp.requests, "Session", lambda: session)

    result = hp.parse_pixeldrain_sync("https://pixeldrain.com/u/AbCd")

    assert result["download_link"] == "https://pixeldrain.com/api/file/AbCd?download"
    assert result["file_info"]["name"] == "movie.mkv"
    assert result["file_info"]["size"] == "117.74 MB"


def test_pixeldrain_missing_file_raises(monkeypatch):
    session = _FakeSession(_Resp(json_data={"success": False}, status_code=404))
    monkeypatch.setattr(hp.requests, "Session", lambda: session)

    with pytest.raises(hp.HosterParseError):
        hp.parse_pixeldrain_sync("https://pixeldrain.com/u/dead")


def test_pixeldrain_link_without_id_raises():
    with pytest.raises(hp.HosterParseError):
        hp.parse_pixeldrain_sync("https://pixeldrain.com/")


# --- MediaFire --------------------------------------------------------------

def test_mediafire_extracts_plain_download_button(monkeypatch):
    page = (
        '<html><body>'
        '<div class="filename">movie.zip</div>'
        '<a id="downloadButton" aria-label="Download file" '
        'href="https://download1234.mediafire.com/abc/movie.zip">Download (1.50 GB)</a>'
        '</body></html>'
    )
    monkeypatch.setattr(hp.cloudscraper, "create_scraper", lambda: _FakeScraper(_Resp(page)))

    result = hp.parse_mediafire_sync("https://www.mediafire.com/file/abc/movie.zip/file")

    assert result["download_link"] == "https://download1234.mediafire.com/abc/movie.zip"
    assert result["file_info"]["name"] == "movie.zip"
    assert result["file_info"]["size"] == "1.50 GB"


def test_mediafire_decodes_scrambled_url(monkeypatch):
    real = "https://download5678.mediafire.com/xyz/archive.rar"
    scrambled = base64.b64encode(real.encode()).decode()
    page = (
        f'<html><body><a id="downloadButton" data-scrambled-url="{scrambled}">'
        f'Download</a></body></html>'
    )
    monkeypatch.setattr(hp.cloudscraper, "create_scraper", lambda: _FakeScraper(_Resp(page)))

    result = hp.parse_mediafire_sync("https://www.mediafire.com/file/xyz/archive.rar/file")

    assert result["download_link"] == real


def test_mediafire_no_link_raises(monkeypatch):
    page = "<html><body><p>No download here</p></body></html>"
    monkeypatch.setattr(hp.cloudscraper, "create_scraper", lambda: _FakeScraper(_Resp(page)))

    with pytest.raises(hp.HosterParseError):
        hp.parse_mediafire_sync("https://www.mediafire.com/file/none/x/file")


# --- Bunkr ------------------------------------------------------------------

def test_bunkr_extracts_direct_cdn_link(monkeypatch):
    page = (
        '<html><body>'
        '<a href="https://m">bad</a>'
        '<a class="btn-download" href="https://get.bunkr.ru/file/movie.mkv">Download</a>'
        '<strong>1.20 GB</strong>'
        '</body></html>'
    )
    monkeypatch.setattr(hp.cloudscraper, "create_scraper", lambda: _FakeScraper(_Resp(page)))

    result = hp.parse_bunkr_sync("https://bunkr.si/f/movie")

    assert result["download_link"] == "https://get.bunkr.ru/file/movie.mkv"


def test_bunkr_encrypted_page_raises(monkeypatch):
    # No usable file link, only assets — must fail loudly, not save an asset.
    page = (
        '<html><head><link href="https://bunkr.si/style.css"></head>'
        '<body><script src="https://bunkr.si/app.js"></script></body></html>'
    )
    monkeypatch.setattr(hp.cloudscraper, "create_scraper", lambda: _FakeScraper(_Resp(page)))

    with pytest.raises(hp.HosterParseError):
        hp.parse_bunkr_sync("https://bunkr.si/f/enc")


def test_bunkr_rejects_asset_extensions():
    assert hs._is_bunkr_file_link("https://bunkr.si/app.js") is False
    assert hs._is_bunkr_file_link("https://cdn.bunkr.ru/video.mkv") is True
    assert hs._is_bunkr_file_link("https://example.com/video.mkv") is False


def test_bunkr_accepts_extensionless_get_file_route():
    # Regression H4: the get.*/file/ download route (no extension) must validate.
    assert hs._is_bunkr_file_link("https://get.bunkrr.su/file/123456") is True


def test_bunkr_rejects_page_route_and_page_url():
    # Regression H3: the page's own /f/ URL must never be returned as the file.
    assert hs._is_bunkr_file_link("https://bunkr.si/f/archive.part1.rar") is False
    page = "https://bunkr.si/f/archive.part1.rar"
    assert hs._is_bunkr_file_link(page, page) is False


def test_bunkr_rejects_unrelated_get_domain():
    # Regression L2: a get.* host that isn't Bunkr is an ad/redirect, not a file.
    assert hs._is_bunkr_file_link("https://get.evil.com/malware.exe") is False


def test_bunkr_encrypted_page_with_own_url_raises(monkeypatch):
    # An archive file page exposing only its own canonical /f/ URL (no CDN link)
    # must fail loudly, not save the HTML page as the file.
    page = (
        '<html><head><link rel="canonical" href="https://bunkr.si/f/archive.rar">'
        '<meta property="og:url" content="https://bunkr.si/f/archive.rar"></head>'
        '<body><h1>archive.rar</h1></body></html>'
    )
    monkeypatch.setattr(hp.cloudscraper, "create_scraper", lambda: _FakeScraper(_Resp(page)))
    with pytest.raises(hp.HosterParseError):
        hp.parse_bunkr_sync("https://bunkr.si/f/archive.rar")


# --- Pixeldrain edge cases --------------------------------------------------

def test_pixeldrain_list_url_raises_clear_error(monkeypatch):
    # M6: a /l/ list link must give a clear "use individual file" error, not a
    # false "deleted". No network call should happen.
    def _boom():
        raise AssertionError("must not open a session for a list URL")
    monkeypatch.setattr(hp.requests, "Session", _boom)
    with pytest.raises(hp.HosterParseError, match="리스트"):
        hp.parse_pixeldrain_sync("https://pixeldrain.com/l/AbCd")


def test_pixeldrain_non_json_response_raises_hosterparseerror(monkeypatch):
    # M1: a Cloudflare/HTML error body must become a HosterParseError, not a raw
    # JSONDecodeError.
    class _HtmlResp:
        status_code = 503
        def json(self):
            raise ValueError("Expecting value: line 1 column 1")

    class _Sess:
        headers = {}
        proxies = {}
        def get(self, *a, **k):
            return _HtmlResp()

    monkeypatch.setattr(hp.requests, "Session", lambda: _Sess())
    with pytest.raises(hp.HosterParseError):
        hp.parse_pixeldrain_sync("https://pixeldrain.com/u/AbCd")


# --- Registry dispatch ------------------------------------------------------

def test_registry_recognizes_new_hosts_and_www_aliases():
    for host in (
        "pixeldrain.com", "www.pixeldrain.com", "mediafire.com",
        "www.mediafire.com", "bunkr.si", "bunkrr.su",
    ):
        assert host in hp.SPECIAL_HOSTS


def test_dispatch_routes_to_registered_parser(monkeypatch):
    seen = {}

    def fake_pixeldrain(url, proxies=None):
        seen["url"] = url
        seen["proxies"] = proxies
        return {"download_link": "https://pixeldrain.com/api/file/x?download"}

    monkeypatch.setattr(hp, "parse_pixeldrain_sync", fake_pixeldrain)
    proxies = {"https": "http://1.2.3.4:8080"}
    hp.parse_special_hoster_sync("https://pixeldrain.com/u/x", proxies=proxies)

    assert seen["url"] == "https://pixeldrain.com/u/x"
    assert seen["proxies"] == proxies


def test_unknown_host_raises():
    with pytest.raises(hp.HosterParseError):
        hp.parse_special_hoster_sync("https://example.com/file/1")


def test_info_only_prefetch_skips_hosts_without_extractor():
    # Pixeldrain has no HTML info extractor -> prefetch returns {} (no network).
    assert hp.fetch_special_hoster_file_info_sync("https://pixeldrain.com/u/x") == {}


def test_info_only_prefetch_reads_mediafire_page(monkeypatch):
    page = '<html><body><div class="filename">clip.mp4</div><span>800 MB</span></body></html>'
    monkeypatch.setattr(hp.cloudscraper, "create_scraper", lambda: _FakeScraper(_Resp(page)))

    info = hp.fetch_special_hoster_file_info_sync("https://www.mediafire.com/file/x/clip.mp4/file")

    assert info["name"] == "clip.mp4"
    assert info["size"] == "800 MB"
