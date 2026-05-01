# -*- coding: utf-8 -*-
"""``core.download_core`` 의 순수 헬퍼와 다운로드 컨텍스트 동작 검증.

특히 다음 두 가지 회귀를 막는다:
  1. aiohttp 다운로드가 파서 세션의 쿠키/User-Agent/Referer 없이 호출되어
     1fichier 다운로드 호스트가 ``HTTP 404: Not Found`` 를 반환하는 문제.
  2. 다운로드 단계에서 발생한 404 가 외부에서 ``파싱 실패`` 로 라벨링되는 문제.
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
        # 1fichier 가 트랜스퍼 인코딩을 추가로 적용하는 일이 있어
        # ``Accept-Encoding: identity`` 를 명시한다.
        assert build_download_headers()["Accept-Encoding"] == "identity"


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
    """Session 호출을 캡처하기 위한 가짜 aiohttp 세션."""

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
    """aiohttp.ClientSession 을 가짜로 치환."""

    monkeypatch.setattr(dc.aiohttp, "ClientSession", _FakeAioSession)
    monkeypatch.setattr(dc.aiohttp, "ClientTimeout", lambda **kwargs: kwargs)
    yield _FakeAioSession


class _FakeDownloadRequest:
    """SQLAlchemy 모델을 사용하지 않는 가짜 요청 객체."""

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
    """SQLAlchemy Session 의 commit/refresh 를 흉내내는 더미."""

    def commit(self):
        pass

    def refresh(self, _):
        pass

    def close(self):
        pass


@pytest.mark.asyncio
async def test_direct_download_passes_cookies_and_headers(fake_aiohttp, monkeypatch):
    """파서가 넘긴 쿠키/UA/Referer 가 aiohttp 세션과 GET 요청에 모두 전달돼야 한다."""

    core = dc.DownloadCore()
    req = _FakeDownloadRequest()
    db = _FakeDb()

    monkeypatch.setattr(dc, "send_telegram_start_notification", lambda *a, **kw: None)
    monkeypatch.setattr(dc, "send_telegram_notification", lambda *a, **kw: None)
    core.send_download_update = AsyncMock()

    # 실제 파일 IO 회피
    import utils.file_helpers as fh

    monkeypatch.setattr(fh, "download_file_content", AsyncMock(return_value=0))
    monkeypatch.setattr(dc, "download_file_content", AsyncMock(return_value=0))
    monkeypatch.setattr(fh, "get_final_file_path", lambda p: p)
    monkeypatch.setattr(dc, "get_final_file_path", lambda p: p)
    monkeypatch.setattr(dc.shutil, "move", lambda *a, **kw: None)

    # 가짜 응답을 200 으로 설정
    def session_factory(*args, **kwargs):
        s = _FakeAioSession(*args, **kwargs)
        s.response = _FakeAioResponse(200, "OK", headers={"Content-Length": "0"})
        return s

    monkeypatch.setattr(dc.aiohttp, "ClientSession", session_factory)

    cookies = {"cf_clearance": "abc123", "PHPSESSID": "sess"}
    download_url = "https://a-1.1fichier.com/p38234d8d/movie.mkv"
    # save_path 가 존재하지 않게 (이어받기 분기 회피)
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
    """다운로드 서버가 404 를 내면 ``HTTP 404: Not Found`` 형식으로 raise 된다."""

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
async def test_direct_download_auto_reparses_on_404(monkeypatch):
    """404 발생 시 parse_url 이 주어지면 자동 재파싱 후 새 링크로 재시도한다."""

    core = dc.DownloadCore()
    req = _FakeDownloadRequest()
    db = _FakeDb()

    monkeypatch.setattr(dc, "send_telegram_notification", lambda *a, **kw: None)
    monkeypatch.setattr(dc, "send_telegram_start_notification", lambda *a, **kw: None)
    core.send_download_update = AsyncMock()

    # 파일 IO mocking
    import utils.file_helpers as fh
    monkeypatch.setattr(fh, "download_file_content", AsyncMock(return_value=0))
    monkeypatch.setattr(dc, "download_file_content", AsyncMock(return_value=0))
    monkeypatch.setattr(fh, "get_final_file_path", lambda p: p)
    monkeypatch.setattr(dc, "get_final_file_path", lambda p: p)
    monkeypatch.setattr(dc.shutil, "move", lambda *a, **kw: None)

    # 첫 시도 → 404, 두 번째 시도 → 200
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

    # 재파싱 결과 fake
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
        referer="https://1fichier.com/?abc",
        parse_url="https://1fichier.com/?abc",
    )

    # 두 번 시도(첫 실패, 둘째 성공) 했어야 함
    assert call_seq["i"] == 2


@pytest.mark.asyncio
async def test_direct_download_does_not_reparse_when_parse_url_missing(monkeypatch):
    """parse_url 이 없으면 404 를 받아도 재파싱하지 않고 그대로 raise."""

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
