# -*- coding: utf-8 -*-
"""Verifies the pure helpers and download-context behavior of ``core.download_core``.

In particular, it guards against these two regressions:
  1. The aiohttp download being called without the parser session's
     cookies/User-Agent/Referer, causing the 1fichier download host to return
     ``HTTP 404: Not Found``.
  2. A 404 raised during the download stage being labeled externally as
     ``파싱 실패`` (parse failure).
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import core.download_core as dc
from core.download_core import DEFAULT_DOWNLOAD_USER_AGENT, build_download_headers


class TestBuildDownloadHeaders:
    def test_uses_default_user_agent_when_missing(self):
        headers = build_download_headers()
        assert headers["User-Agent"] == DEFAULT_DOWNLOAD_USER_AGENT
        assert headers["Accept"] == "*/*"
        assert "Referer" not in headers

    def test_uses_provided_user_agent(self):
        headers = build_download_headers(user_agent="MyAgent/1.0")
        assert headers["User-Agent"] == "MyAgent/1.0"

    def test_includes_referer_when_provided(self):
        headers = build_download_headers(referer="https://1fichier.com/?abc")
        assert headers["Referer"] == "https://1fichier.com/?abc"

    def test_disables_compression_to_avoid_aiohttp_decoding_issues(self):
        # 1fichier sometimes applies an extra transfer encoding, so we
        # specify ``Accept-Encoding: identity`` explicitly.
        assert build_download_headers()["Accept-Encoding"] == "identity"


class TestFileNameReplacement:
    def test_replaces_1fichier_placeholder_with_real_name(self):
        assert dc._should_replace_file_name(
            "1fichier:526sy7th2mb9xhrny46x",
            "movie.mkv",
        ) is True

    def test_keeps_existing_real_name(self):
        assert dc._should_replace_file_name("movie.mkv", "other.mkv") is False


class _FakeAioResponse:
    def __init__(self, status, reason="OK", headers=None):
        self.status = status
        self.reason = reason
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeAioSession:
    """A fake aiohttp session used to capture session calls."""

    last_instance: "_FakeAioSession | None" = None

    def __init__(self, *args, **kwargs):
        self.kwargs = kwargs
        self.captured_get = None
        self.response = _FakeAioResponse(404, "Not Found")
        _FakeAioSession.last_instance = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url, headers=None, proxy=None):
        self.captured_get = {"url": url, "headers": headers, "proxy": proxy}
        return self.response


@pytest.fixture
def fake_aiohttp(monkeypatch):
    """Replace aiohttp.ClientSession with a fake."""

    monkeypatch.setattr(dc.aiohttp, "ClientSession", _FakeAioSession)
    monkeypatch.setattr(dc.aiohttp, "ClientTimeout", lambda **kwargs: kwargs)
    yield _FakeAioSession


class _FakeDownloadRequest:
    """A fake request object that does not use the SQLAlchemy model."""

    def __init__(self):
        self.id = 1
        self.url = "https://1fichier.com/?abc"
        self.original_url = "https://1fichier.com/?abc"
        self.file_name = "movie.mkv"
        self.file_size = "1 GB"
        self.total_size = 0
        self.downloaded_size = 0
        self.save_path = "/tmp/__nonexistent_test_path__/movie.mkv.part"
        self.started_at = None
        self.finished_at = None
        self.status = None
        self.error = None
        self.use_proxy = False
        self.password = None


class _FakeDb:
    """A dummy that mimics commit/refresh of a SQLAlchemy Session."""

    def commit(self):
        pass

    def refresh(self, _):
        pass

    def close(self):
        pass


@pytest.mark.asyncio
async def test_direct_download_passes_cookies_and_headers(fake_aiohttp, monkeypatch):
    """The cookies/UA/Referer passed by the parser must reach both the aiohttp session and the GET request."""

    core = dc.DownloadCore()
    req = _FakeDownloadRequest()
    db = _FakeDb()

    monkeypatch.setattr(dc, "send_telegram_start_notification", lambda *a, **kw: None)
    monkeypatch.setattr(dc, "send_telegram_notification", lambda *a, **kw: None)
    core.send_download_update = AsyncMock()

    # Avoid real file IO
    import utils.file_helpers as fh

    monkeypatch.setattr(fh, "download_file_content", AsyncMock(return_value=0))
    monkeypatch.setattr(dc, "download_file_content", AsyncMock(return_value=0))
    monkeypatch.setattr(fh, "get_final_file_path", lambda p: p)
    monkeypatch.setattr(dc, "get_final_file_path", lambda p: p)
    monkeypatch.setattr(dc.shutil, "move", lambda *a, **kw: None)

    # Set the fake response to 200
    def session_factory(*args, **kwargs):
        s = _FakeAioSession(*args, **kwargs)
        s.response = _FakeAioResponse(200, "OK", headers={"Content-Length": "0"})
        return s

    monkeypatch.setattr(dc.aiohttp, "ClientSession", session_factory)

    cookies = {"cf_clearance": "abc123", "PHPSESSID": "sess"}
    download_url = "https://a-1.1fichier.com/p38234d8d/movie.mkv"
    # Make save_path not exist (avoid the resume branch)
    assert not __import__("os").path.exists(req.save_path)

    await core._download_file_directly(
        req,
        db,
        download_url,
        cookies=cookies,
        user_agent="UA-test",
        referer="https://1fichier.com/?abc",
    )

    captured_session = _FakeAioSession.last_instance
    assert captured_session is not None
    assert captured_session.kwargs.get("cookies") == cookies

    captured = captured_session.captured_get
    assert captured["url"] == download_url
    assert captured["headers"]["User-Agent"] == "UA-test"
    assert captured["headers"]["Referer"] == "https://1fichier.com/?abc"


@pytest.mark.asyncio
async def test_direct_download_raises_with_aiohttp_style_404(fake_aiohttp, monkeypatch):
    """When the download server returns 404, it raises in the ``HTTP 404: Not Found`` form."""

    core = dc.DownloadCore()
    req = _FakeDownloadRequest()
    db = _FakeDb()

    monkeypatch.setattr(dc, "send_telegram_notification", lambda *a, **kw: None)
    monkeypatch.setattr(dc, "send_telegram_start_notification", lambda *a, **kw: None)
    core.send_download_update = AsyncMock()

    with pytest.raises(Exception) as excinfo:
        await core._download_file_directly(
            req,
            db,
            "https://a-1.1fichier.com/expired",
            cookies={},
            user_agent="UA",
            referer="https://1fichier.com/?abc",
        )

    assert "HTTP 404: Not Found" in str(excinfo.value)


@pytest.mark.asyncio
async def test_special_hoster_direct_download_rejects_html_response(monkeypatch):
    """If the hoster's final link is a security/interstitial HTML page, do not save it as a file."""

    core = dc.DownloadCore()
    req = _FakeDownloadRequest()
    req.url = "https://megaup.net/code/movie.rar"
    req.original_url = req.url
    db = _FakeDb()

    monkeypatch.setattr(dc, "send_telegram_notification", lambda *a, **kw: None)
    monkeypatch.setattr(dc, "send_telegram_start_notification", lambda *a, **kw: None)
    core.send_download_update = AsyncMock()

    def session_factory(*args, **kwargs):
        s = _FakeAioSession(*args, **kwargs)
        s.response = _FakeAioResponse(
            200,
            "OK",
            headers={"Content-Type": "text/html; charset=UTF-8"},
        )
        return s

    monkeypatch.setattr(dc.aiohttp, "ClientSession", session_factory)
    monkeypatch.setattr(dc.aiohttp, "ClientTimeout", lambda **kwargs: kwargs)

    with pytest.raises(Exception) as excinfo:
        await core._download_file_directly(
            req,
            db,
            "https://download.megaup.net/?url=token",
            cookies={},
            user_agent="UA",
            referer=req.url,
        )

    assert "파일 대신 HTML" in str(excinfo.value)


@pytest.mark.asyncio
async def test_special_hoster_403_uses_flaresolverr_cookies_then_retries(monkeypatch):
    """A 403 on a special hoster's final link is retried once after obtaining FlareSolverr cookies."""

    core = dc.DownloadCore()
    req = _FakeDownloadRequest()
    req.url = "https://megaup.net/code/movie.rar"
    req.original_url = req.url
    db = _FakeDb()

    monkeypatch.setattr(dc, "send_telegram_notification", lambda *a, **kw: None)
    monkeypatch.setattr(dc, "send_telegram_start_notification", lambda *a, **kw: None)
    monkeypatch.setattr(
        dc,
        "get_flaresolverr_context_for_url",
        lambda *a, **kw: {"cookies": {"cf_clearance": "ok"}, "user_agent": "Chrome/142"},
    )
    core.send_download_update = AsyncMock()

    import utils.file_helpers as fh
    monkeypatch.setattr(fh, "download_file_content", AsyncMock(return_value=0))
    monkeypatch.setattr(dc, "download_file_content", AsyncMock(return_value=0))
    monkeypatch.setattr(fh, "get_final_file_path", lambda p: p)
    monkeypatch.setattr(dc, "get_final_file_path", lambda p: p)
    monkeypatch.setattr(dc.shutil, "move", lambda *a, **kw: None)

    class SequenceSession(_FakeAioSession):
        instances = []

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            SequenceSession.instances.append(self)
            self.response = (
                _FakeAioResponse(403, "Forbidden")
                if len(SequenceSession.instances) == 1
                else _FakeAioResponse(200, "OK", headers={"Content-Length": "0"})
            )

    monkeypatch.setattr(dc.aiohttp, "ClientSession", SequenceSession)
    monkeypatch.setattr(dc.aiohttp, "ClientTimeout", lambda **kwargs: kwargs)

    await core._download_file_directly(
        req,
        db,
        "https://download.megaup.net/?url=token",
        cookies={},
        user_agent="UA",
        referer=req.url,
    )

    assert len(SequenceSession.instances) == 2
    assert SequenceSession.instances[1].kwargs["cookies"] == {"cf_clearance": "ok"}
    assert SequenceSession.instances[1].captured_get["headers"]["User-Agent"] == "Chrome/142"


@pytest.mark.asyncio
async def test_direct_download_auto_reparses_on_404(monkeypatch):
    """On a 404, if parse_url is given, automatically re-parse and retry with the new link."""

    core = dc.DownloadCore()
    req = _FakeDownloadRequest()
    db = _FakeDb()

    monkeypatch.setattr(dc, "send_telegram_notification", lambda *a, **kw: None)
    monkeypatch.setattr(dc, "send_telegram_start_notification", lambda *a, **kw: None)
    core.send_download_update = AsyncMock()

    # File IO mocking
    import utils.file_helpers as fh
    monkeypatch.setattr(fh, "download_file_content", AsyncMock(return_value=0))
    monkeypatch.setattr(dc, "download_file_content", AsyncMock(return_value=0))
    monkeypatch.setattr(fh, "get_final_file_path", lambda p: p)
    monkeypatch.setattr(dc, "get_final_file_path", lambda p: p)
    monkeypatch.setattr(dc.shutil, "move", lambda *a, **kw: None)

    # First attempt → 404, second attempt → 200
    call_seq = {"i": 0}

    def session_factory(*args, **kwargs):
        s = _FakeAioSession(*args, **kwargs)
        if call_seq["i"] == 0:
            s.response = _FakeAioResponse(404, "Not Found")
        else:
            s.response = _FakeAioResponse(200, "OK", headers={"Content-Length": "0"})
        call_seq["i"] += 1
        return s

    monkeypatch.setattr(dc.aiohttp, "ClientSession", session_factory)

    # Fake re-parse result
    async def fake_reparse(req, parse_url, **kw):
        return {
            "download_link": "https://a-2.1fichier.com/p2/movie.mkv",
            "cookies": {"new": "cookie"},
            "user_agent": "UA-new",
            "referer": parse_url,
        }

    core._reparse_for_retry = fake_reparse

    await core._download_file_directly(
        req,
        db,
        "https://a-1.1fichier.com/p1/movie.mkv",
        cookies={"old": "cookie"},
        user_agent="UA-old",
        referer="https://1fichier.com/?abc123",
        parse_url="https://1fichier.com/?abc123",
    )

    # Should have attempted twice (first failed, second succeeded)
    assert call_seq["i"] == 2


@pytest.mark.asyncio
async def test_direct_download_does_not_reparse_when_parse_url_missing(monkeypatch):
    """Without parse_url, a 404 raises as-is without re-parsing."""

    core = dc.DownloadCore()
    req = _FakeDownloadRequest()
    db = _FakeDb()

    monkeypatch.setattr(dc, "send_telegram_notification", lambda *a, **kw: None)
    monkeypatch.setattr(dc, "send_telegram_start_notification", lambda *a, **kw: None)
    core.send_download_update = AsyncMock()

    def session_factory(*args, **kwargs):
        s = _FakeAioSession(*args, **kwargs)
        s.response = _FakeAioResponse(404, "Not Found")
        return s

    monkeypatch.setattr(dc.aiohttp, "ClientSession", session_factory)

    with pytest.raises(Exception, match="HTTP 404"):
        await core._download_file_directly(
            req,
            db,
            "https://a-1.1fichier.com/expired",
            cookies={},
            user_agent="UA",
            referer=None,
            parse_url=None,
        )


@pytest.mark.asyncio
async def test_reparse_for_retry_rejects_download_host(monkeypatch):
    """If only an expired download-host URL is available, do not use it for re-parsing."""

    core = dc.DownloadCore()
    req = _FakeDownloadRequest()
    called = False

    def fake_parse(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(dc, "parse_1fichier_simple_sync", fake_parse)

    result = await core._reparse_for_retry(
        req,
        "https://a-1.1fichier.com/p1expired/movie.mkv",
    )

    assert result is None
    assert called is False
