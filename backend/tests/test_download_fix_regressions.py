# -*- coding: utf-8 -*-
"""Deterministic regression tests for download failure and stability fixes."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiohttp
from Crypto.Cipher import AES
import pytest

from api.routes.downloads import (
    stop_all_downloads,
    stop_all_local_downloads,
    stop_all_proxy_downloads,
)
from core import browser_solver as bs, cancel_signal, config as config_mod, db_async
from core.browser_solver import BROWSER_FLOW_HOSTS
import core.download_core as dc
from core.executors import CAPTCHA_PARSE_EXECUTOR, parse_executor_for
from core.host_policy import canonical_host
import core.hoster_parsers as hp
import core.hoster_sites as hs
from core.mega_crypto import a32_to_bytes, decrypt_attr
from core.models import DownloadRequest, StatusEnum
from core.ouo_resolver import OuoResolver, OuoResolverConfig
from core.parser import FichierParser
from services.mirror_failover import switch_to_next_mirror
import services.ouo_unwrap_service as ouo_unwrap
from utils.file_helpers import download_file_content


BACKEND_ROOT = Path(__file__).resolve().parent.parent


class _FakeChunkStream:
    """Async chunk iterator that yields ``chunks`` and optionally raises ``error``."""

    def __init__(self, chunks: list[bytes], error: Exception | None = None, on_chunk=None):
        self._chunks = list(chunks)
        self._error = error
        self._on_chunk = on_chunk

    async def iter_chunked(self, size: int):
        for idx, chunk in enumerate(self._chunks):
            if self._on_chunk is not None:
                self._on_chunk(idx, chunk)
            yield chunk
        if self._error is not None:
            raise self._error


class _FakeResponse:
    def __init__(
        self,
        status: int,
        headers: dict[str, str],
        chunks: list[bytes],
        error: Exception | None = None,
        on_chunk=None,
        url: str = "https://cdn.example.com/file.bin",
        reason: str = "OK",
    ):
        self.status = status
        self.headers = headers
        self.url = url
        self.reason = reason
        self.content = _FakeChunkStream(chunks, error=error, on_chunk=on_chunk)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _SequencedClientSession:
    """Replaces aiohttp.ClientSession in _download_file_directly tests."""

    instances: list["_SequencedClientSession"] = []
    responses: list[_FakeResponse] = []

    def __init__(self, *args, **kwargs):
        self.requests: list[tuple[str, dict]] = []
        _SequencedClientSession.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url: str, headers: dict | None = None, proxy: str | None = None):
        self.requests.append((url, dict(headers or {})))
        if not _SequencedClientSession.responses:
            raise AssertionError("No canned response left in _SequencedClientSession")
        return _SequencedClientSession.responses.pop(0)


# ---------------------------------------------------------------------------
# 1. Mid-stream Range resume for non-special hosters & progressive retry reset
# ---------------------------------------------------------------------------


class TestMidStreamRangeResume:
    @pytest.mark.asyncio
    async def test_non_special_hoster_resumes_mid_stream_content_length_error(
        self, tmp_path, monkeypatch
    ):
        """A non-special hoster (e.g. 1fichier/MediaFire direct URL) that drops mid-stream
        with ContentLengthError must resume via HTTP Range on the existing .part file."""
        monkeypatch.setattr(
            dc,
            "generate_file_path",
            lambda name, is_temporary=True: str(tmp_path / (f"{name}.part" if is_temporary else name)),
        )
        monkeypatch.setattr(dc.sse_manager, "broadcast_message", AsyncMock())
        monkeypatch.setattr(dc.db_async, "commit", AsyncMock())
        monkeypatch.setattr(dc.db_async, "refresh", AsyncMock())
        monkeypatch.setattr(dc.asyncio, "sleep", AsyncMock())

        payload_error = aiohttp.ClientPayloadError(
            "Response payload is not completed: <ContentLengthError: 400, "
            "message='Not enough data to satisfy content length header.'>"
        )
        _SequencedClientSession.instances = []
        _SequencedClientSession.responses = [
            _FakeResponse(
                200,
                {
                    "Content-Length": "10",
                    "Content-Type": "application/octet-stream",
                },
                [b"12345"],
                error=payload_error,
            ),
            _FakeResponse(
                206,
                {
                    "Content-Length": "5",
                    "Content-Range": "bytes 5-9/10",
                    "Content-Type": "application/octet-stream",
                },
                [b"67890"],
            ),
        ]
        monkeypatch.setattr(dc.aiohttp, "ClientSession", _SequencedClientSession)

        core = dc.DownloadCore()
        req = SimpleNamespace(
            id=101,
            url="https://cdn-1.1fichier.com/abc/archive.bin",
            original_url="https://1fichier.com/?abc",
            file_name="archive.bin",
            file_size="10 B",
            save_path=None,
            status=StatusEnum.downloading,
            downloaded_size=0,
            total_size=10,
            error=None,
            failure_kind=None,
            attempt_count=0,
            attempts_json=None,
            next_retry_at=None,
            started_at=None,
            finished_at=None,
            use_proxy=False,
            mirror_urls=None,
            password=None,
        )
        db = MagicMock()

        await core._download_file_directly(req, db, req.url)

        assert req.status == StatusEnum.done
        final_file = tmp_path / "archive.bin"
        assert final_file.exists()
        assert final_file.read_bytes() == b"1234567890"
        assert len(_SequencedClientSession.instances) == 2
        second_headers = _SequencedClientSession.instances[1].requests[0][1]
        assert second_headers.get("Range") == "bytes=5-"

    @pytest.mark.asyncio
    async def test_progressive_mid_stream_resumes_exceed_3_retries_when_making_progress(
        self, tmp_path, monkeypatch
    ):
        """A multi-GB file that disconnects 5 times while growing .part each time
        must reset same_url_retries on progress and complete on the 6th chunk."""
        monkeypatch.setattr(
            dc,
            "generate_file_path",
            lambda name, is_temporary=True: str(tmp_path / (f"{name}.part" if is_temporary else name)),
        )
        monkeypatch.setattr(dc.sse_manager, "broadcast_message", AsyncMock())
        monkeypatch.setattr(dc.db_async, "commit", AsyncMock())
        monkeypatch.setattr(dc.db_async, "refresh", AsyncMock())
        monkeypatch.setattr(dc.asyncio, "sleep", AsyncMock())

        ssl_err = Exception("SSL record layer failure")
        _SequencedClientSession.instances = []
        _SequencedClientSession.responses = [
            _FakeResponse(
                200,
                {"Content-Length": "12", "Content-Type": "application/octet-stream"},
                [b"aa"],
                error=ssl_err,
            ),
            _FakeResponse(
                206,
                {"Content-Length": "10", "Content-Range": "bytes 2-11/12"},
                [b"bb"],
                error=ssl_err,
            ),
            _FakeResponse(
                206,
                {"Content-Length": "8", "Content-Range": "bytes 4-11/12"},
                [b"cc"],
                error=ssl_err,
            ),
            _FakeResponse(
                206,
                {"Content-Length": "6", "Content-Range": "bytes 6-11/12"},
                [b"dd"],
                error=ssl_err,
            ),
            _FakeResponse(
                206,
                {"Content-Length": "4", "Content-Range": "bytes 8-11/12"},
                [b"ee"],
                error=ssl_err,
            ),
            _FakeResponse(
                206,
                {"Content-Length": "2", "Content-Range": "bytes 10-11/12"},
                [b"ff"],
            ),
        ]
        monkeypatch.setattr(dc.aiohttp, "ClientSession", _SequencedClientSession)

        core = dc.DownloadCore()
        req = SimpleNamespace(
            id=102,
            url="https://cdn-1.1fichier.com/xyz/big.bin",
            original_url="https://1fichier.com/?xyz",
            file_name="big.bin",
            file_size="12 B",
            save_path=None,
            status=StatusEnum.downloading,
            downloaded_size=0,
            total_size=12,
            error=None,
            failure_kind=None,
            attempt_count=0,
            attempts_json=None,
            next_retry_at=None,
            started_at=None,
            finished_at=None,
            use_proxy=False,
            mirror_urls=None,
            password=None,
        )
        db = MagicMock()

        await core._download_file_directly(req, db, req.url)

        assert req.status == StatusEnum.done
        assert (tmp_path / "big.bin").read_bytes() == b"aabbccddeeff"

    @pytest.mark.asyncio
    async def test_non_progressive_mid_stream_disconnect_stops_after_max_retries(
        self, tmp_path, monkeypatch
    ):
        """When a stream disconnects repeatedly without advancing .part bytes,
        same_url_retries is NOT reset and the loop terminates after 3 retries."""
        monkeypatch.setattr(dc, "get_download_path", lambda: tmp_path)
        monkeypatch.setattr(dc.sse_manager, "broadcast_message", AsyncMock())
        monkeypatch.setattr(dc.db_async, "commit", AsyncMock())
        monkeypatch.setattr(dc.db_async, "refresh", AsyncMock())
        monkeypatch.setattr(dc.asyncio, "sleep", AsyncMock())

        part = tmp_path / "stuck.bin.part"
        part.write_bytes(b"12345")

        payload_err = aiohttp.ClientPayloadError("Not enough data to satisfy content length header")
        _SequencedClientSession.instances = []
        # 4 responses: initial + 3 retries, none writing any new bytes before erroring
        _SequencedClientSession.responses = [
            _FakeResponse(
                206,
                {"Content-Length": "5", "Content-Range": "bytes 5-9/10"},
                [],
                error=payload_err,
            )
            for _ in range(4)
        ]
        monkeypatch.setattr(dc.aiohttp, "ClientSession", _SequencedClientSession)

        core = dc.DownloadCore()
        req = SimpleNamespace(
            id=103,
            url="https://cdn.example.com/stuck.bin",
            original_url=None,
            file_name="stuck.bin",
            file_size="10 B",
            save_path=str(part),
            status=StatusEnum.downloading,
            downloaded_size=5,
            total_size=10,
            error=None,
            failure_kind=None,
            attempt_count=0,
            attempts_json=None,
            next_retry_at=None,
            started_at=None,
            finished_at=None,
            use_proxy=False,
            mirror_urls=None,
            password=None,
        )
        db = MagicMock()

        with pytest.raises(aiohttp.ClientPayloadError):
            await core._download_file_directly(req, db, req.url)

        assert len(_SequencedClientSession.instances) == 4
        assert req.attempt_count == 1


# ---------------------------------------------------------------------------
# 2. Exact total_size update on HTTP 206 resume
# ---------------------------------------------------------------------------


class TestHttp206UpdatesApproximateTotalSize:
    @pytest.mark.asyncio
    async def test_206_content_range_corrects_approximate_preparse_total_size(
        self, tmp_path, monkeypatch
    ):
        """When req.total_size holds an inflated human-readable estimate (e.g. 2000 bytes)
        and a 206 resume states the exact resource length (1000 bytes), req.total_size
        must be updated so assert_downloaded_a_real_file succeeds."""
        monkeypatch.setattr(dc.sse_manager, "broadcast_message", AsyncMock())
        monkeypatch.setattr(dc.db_async, "commit", AsyncMock())
        monkeypatch.setattr(dc.db_async, "refresh", AsyncMock())

        part = tmp_path / "video.mp4.part"
        part.write_bytes(b"a" * 600)

        req = SimpleNamespace(
            id=201,
            url="https://store.gofile.io/download/web/1/video.mp4",
            original_url="https://gofile.io/d/1",
            file_name="video.mp4",
            file_size="2 KB",
            save_path=str(part),
            status=StatusEnum.downloading,
            downloaded_size=600,
            total_size=2000,  # Inflated estimate from "2 KB" preparse text
            error=None,
            failure_kind=None,
            attempt_count=0,
            attempts_json=None,
            next_retry_at=None,
            started_at=None,
            finished_at=None,
            use_proxy=False,
        )
        resp = _FakeResponse(
            206,
            {
                "Content-Range": "bytes 600-999/1000",
                "Content-Length": "400",
                "Content-Type": "application/octet-stream",
            },
            [b"b" * 400],
        )

        core = dc.DownloadCore()
        await core._consume_response_and_finish(
            req, MagicMock(), resp, initial_size=600, download_mode="local"
        )

        assert req.total_size == 1000
        assert req.status == StatusEnum.done
        final_path = tmp_path / "video.mp4"
        assert final_path.exists()
        assert final_path.stat().st_size == 1000


# ---------------------------------------------------------------------------
# 3. MultiUp mirror expansion & universal _fall_back_to_next_mirror
# ---------------------------------------------------------------------------


class TestMultiUpAndMirrorFailover:
    def test_multiup_mirror_candidates_support_expanded_hosts(self):
        mirrors = [
            ("https://1fichier.com/?mirror1", "valid"),
            ("https://pixeldrain.com/u/pd123", "valid"),
            ("https://datanodes.to/dn123/file.rar", "valid"),
            ("https://www.mediafire.com/file/mf123/file.rar", "valid"),
            ("https://send.now/sn123", "valid"),
        ]
        candidates = hs._multiup_mirror_candidates(mirrors)
        names = [name for name, _, _ in candidates]
        assert names == ["DataNodes", "Pixeldrain", "MediaFire", "Send.now", "1fichier"]

    def test_parse_1fichier_mirror_sync_delegates_to_simple_parser(self, monkeypatch):
        monkeypatch.setattr(
            hs.simple_parser,
            "parse_1fichier_simple_sync",
            lambda url, proxies=None: {"download_link": "https://cdn.1fichier.com/dl.rar"},
        )
        res = hs.parse_1fichier_mirror_sync("https://1fichier.com/?abc")
        assert res["download_link"] == "https://cdn.1fichier.com/dl.rar"

    @pytest.mark.asyncio
    async def test_non_special_hoster_failure_falls_back_to_next_mirror(
        self, tmp_path, monkeypatch
    ):
        """When a MultiUp mirror resolved to a non-special hoster (1fichier.com)
        fails during _perform_local_download_async, _fall_back_to_next_mirror
        returns the row to MultiUp (req.original_url) as pending and records 1fichier.com
        in _mirrors_tried."""
        monkeypatch.setattr(dc, "get_download_path", lambda: tmp_path)
        monkeypatch.setattr(dc.sse_manager, "broadcast_message", AsyncMock())
        monkeypatch.setattr(dc.db_async, "commit", AsyncMock())
        monkeypatch.setattr(dc.db_async, "refresh", AsyncMock())

        _SequencedClientSession.instances = []
        _SequencedClientSession.responses = [
            _FakeResponse(404, {}, []),
        ]
        monkeypatch.setattr(dc.aiohttp, "ClientSession", _SequencedClientSession)

        core = dc.DownloadCore()
        multiup_source = "https://multiup.io/en/mirror/abc123/game.rar"
        req = SimpleNamespace(
            id=301,
            url="https://1fichier.com/?deadlink",
            original_url=multiup_source,
            file_name="game.rar",
            file_size="100 MB",
            save_path=str(tmp_path / "game.rar.part"),
            status=StatusEnum.downloading,
            downloaded_size=0,
            total_size=0,
            error=None,
            failure_kind=None,
            attempt_count=0,
            attempts_json=None,
            next_retry_at=None,
            started_at=None,
            finished_at=None,
            use_proxy=False,
            mirror_urls=None,
        )
        db = MagicMock()

        await core._perform_local_download_async(req, db)

        assert req.url == multiup_source
        assert req.status == StatusEnum.pending
        assert "1fichier.com" in core._mirrors_tried.get(301, frozenset())

    def test_switch_to_next_mirror_ignores_missing_part_file_race(self, tmp_path, monkeypatch):
        part = tmp_path / "race.rar.part"
        part.write_bytes(b"partial")
        req = SimpleNamespace(
            id=302,
            url="https://1fichier.com/?a",
            original_url="https://1fichier.com/?a",
            mirror_urls=json.dumps(["https://datanodes.to/b"]),
            save_path=str(part),
            downloaded_size=7,
            total_size=100,
            status=StatusEnum.failed,
            failure_kind="transient",
            attempt_count=1,
            next_retry_at=None,
            finished_at=None,
            error=None,
        )
        monkeypatch.setattr("services.mirror_failover.os.remove", MagicMock(side_effect=FileNotFoundError("gone")))
        nxt = switch_to_next_mirror(req, dc.datetime.datetime.now())
        assert nxt == "https://datanodes.to/b"
        assert req.save_path is None
        assert req.status == StatusEnum.pending


# ---------------------------------------------------------------------------
# 4. Stop-state protection (StatusEnum.stopped & cancel_signal)
# ---------------------------------------------------------------------------


class TestStopStateProtection:
    @pytest.mark.asyncio
    async def test_mid_stream_cancel_signal_keeps_stopped_and_skips_finalize(
        self, tmp_path, monkeypatch
    ):
        """If cancel_signal is triggered while streaming chunks, download_file_content
        marks req.status = StatusEnum.stopped and _consume_response_and_finish
        does NOT finalize or mark the download as done."""
        cancel_signal.clear(401)
        monkeypatch.setattr(dc.sse_manager, "broadcast_message", AsyncMock())
        monkeypatch.setattr(dc.db_async, "commit", AsyncMock())
        monkeypatch.setattr(dc.db_async, "refresh", AsyncMock())

        part = tmp_path / "stopme.bin.part"
        req = SimpleNamespace(
            id=401,
            url="https://cdn.example.com/stopme.bin",
            original_url=None,
            file_name="stopme.bin",
            save_path=str(part),
            status=StatusEnum.downloading,
            downloaded_size=0,
            total_size=10,
            error=None,
        )

        def _trigger_stop_on_first_chunk(idx, _chunk):
            if idx == 0:
                cancel_signal.signal_cancel(401)

        resp = _FakeResponse(
            200,
            {"Content-Length": "10", "Content-Type": "application/octet-stream"},
            [b"12345", b"67890"],
            on_chunk=_trigger_stop_on_first_chunk,
        )

        core = dc.DownloadCore()
        core._finalize_completed_file = AsyncMock()

        await core._consume_response_and_finish(
            req, MagicMock(), resp, initial_size=0, download_mode="local"
        )

        assert req.status == StatusEnum.stopped
        core._finalize_completed_file.assert_not_awaited()
        cancel_signal.clear(401)

    @pytest.mark.asyncio
    async def test_stop_all_endpoints_cancel_tasks_and_signal_waiting_and_proxying(
        self, monkeypatch
    ):
        monkeypatch.setattr("api.routes.downloads.sse_manager.broadcast_message", AsyncMock())
        monkeypatch.setattr(db_async, "commit", AsyncMock())

        row_waiting = SimpleNamespace(
            id=410,
            status=StatusEnum.waiting,
            next_retry_at="2026-10-17T12:00:00",
            error=None,
            use_proxy=False,
        )
        row_proxying = SimpleNamespace(
            id=411,
            status=StatusEnum.proxying,
            next_retry_at="2026-10-17T12:00:00",
            error=None,
            use_proxy=True,
        )

        fake_task_410 = MagicMock()
        fake_task_411 = MagicMock()
        dc.download_core.download_tasks[410] = fake_task_410
        dc.download_core.download_tasks[411] = fake_task_411
        cancel_signal.clear(410)
        cancel_signal.clear(411)

        monkeypatch.setattr(db_async, "all_rows", AsyncMock(return_value=[row_waiting, row_proxying]))
        db = MagicMock()

        res = await stop_all_downloads(db=db)
        assert res["stopped_count"] == 2
        assert row_waiting.status == StatusEnum.stopped
        assert row_proxying.status == StatusEnum.stopped
        assert row_waiting.next_retry_at is None
        assert row_proxying.next_retry_at is None
        assert cancel_signal.is_cancelled(410)
        assert cancel_signal.is_cancelled(411)
        fake_task_410.cancel.assert_called_once()
        fake_task_411.cancel.assert_called_once()

        # Also verify stop_all_proxy_downloads cancels tasks and signals cancel_signal
        row_proxy2 = SimpleNamespace(
            id=412,
            status=StatusEnum.proxying,
            next_retry_at="2026-10-17T12:00:00",
            error=None,
            use_proxy=True,
        )
        fake_task_412 = MagicMock()
        dc.download_core.download_tasks[412] = fake_task_412
        cancel_signal.clear(412)
        monkeypatch.setattr(db_async, "all_rows", AsyncMock(return_value=[row_proxy2]))

        res_proxy = await stop_all_proxy_downloads(db=db)
        assert res_proxy["stopped_count"] == 1
        assert cancel_signal.is_cancelled(412)
        assert row_proxy2.next_retry_at is None
        fake_task_412.cancel.assert_called_once()

        cancel_signal.clear(410)
        cancel_signal.clear(411)
        cancel_signal.clear(412)


# ---------------------------------------------------------------------------
# 5. Single attempt_count increment & stage="다운로드" after parsing succeeds
# ---------------------------------------------------------------------------


class TestSingleFailureRecordingAndStage:
    @pytest.mark.asyncio
    async def test_special_hoster_download_failure_records_once_with_download_stage(
        self, tmp_path, monkeypatch
    ):
        """When parsing succeeds in _download_special_hoster_async and _download_file_directly
        fails, apply_failure_to_request must be called exactly ONCE (attempt_count == 1)
        and with stage='다운로드' rather than '파싱'."""
        monkeypatch.setattr(
            dc,
            "generate_file_path",
            lambda name, is_temporary=True: str(tmp_path / (f"{name}.part" if is_temporary else name)),
        )
        monkeypatch.setattr(dc.sse_manager, "broadcast_message", AsyncMock())
        monkeypatch.setattr(dc.db_async, "commit", AsyncMock())
        monkeypatch.setattr(dc.db_async, "refresh", AsyncMock())

        _SequencedClientSession.instances = []
        _SequencedClientSession.responses = [
            _FakeResponse(503, {}, [], error=None),
        ]
        _SequencedClientSession.responses[0].reason = "Service Unavailable"
        monkeypatch.setattr(dc.aiohttp, "ClientSession", _SequencedClientSession)
        monkeypatch.setattr(
            dc,
            "parse_special_hoster_sync",
            lambda url, password=None, proxies=None: {
                "download_link": "https://cdn.datanodes.to/dl/file.rar",
                "file_info": {"name": "file.rar", "size": "100 MB"},
                "headers": {},
            },
        )

        core = dc.DownloadCore()
        req = SimpleNamespace(
            id=501,
            url="https://datanodes.to/abc/file.rar",
            original_url="https://datanodes.to/abc/file.rar",
            file_name="file.rar",
            file_size="100 MB",
            save_path=None,
            status=StatusEnum.pending,
            downloaded_size=0,
            total_size=0,
            error=None,
            failure_kind=None,
            attempt_count=0,
            attempts_json=None,
            next_retry_at=None,
            started_at=None,
            finished_at=None,
            use_proxy=False,
            mirror_urls=None,
            password=None,
        )
        db = MagicMock()

        await core._download_special_hoster_async(req, db)

        assert req.attempt_count == 1
        attempts = json.loads(req.attempts_json)
        assert len(attempts) == 1
        assert attempts[0]["stage"] == "다운로드"


# ---------------------------------------------------------------------------
# 6. BROWSER_FLOW_HOSTS & CAPTCHA_PARSE_EXECUTOR routing
# ---------------------------------------------------------------------------


class TestBrowserFlowExecutorRouting:
    @pytest.mark.parametrize(
        "host",
        [
            "terabox.com",
            "send.cm",
            "tusfiles.com",
            "tusfiles.net",
            "buzzheavier.com",
            "bzzhr.co",
            "bhvr.cc",
        ],
    )
    def test_newly_added_browser_hosts_route_to_captcha_executor(self, host):
        assert host in BROWSER_FLOW_HOSTS
        assert parse_executor_for(f"https://{host}/file123") is CAPTCHA_PARSE_EXECUTOR


# ---------------------------------------------------------------------------
# 7. OuoResolver & ouo_unwrap_service allowed host parity
# ---------------------------------------------------------------------------


class TestOuoAllowedHostParity:
    @pytest.mark.parametrize(
        "final_url",
        [
            "https://vikingfile.com/f/abc123",
            "https://vik1ngfile.site/f/abc123",
            "https://akirabox.com/abc123",
            "https://rootz.so/d/abc123",
            "https://mixdrop.ag/f/abc123",
            "https://multiup.io/en/mirror/abc123/game.rar",
            "https://drive.google.com/file/d/abc123/view",
            "https://filecrypt.cc/Container/ABC123.html",
            "https://send.cm/abc123",
            "https://tusfiles.com/abc123",
            "https://bunkr.si/f/abc123",
            "https://cyberdrop.me/a/abc123",
            "https://terabox.com/s/1abc123",
            "https://buzzheavier.com/f/abc123",
        ],
    )
    def test_ouo_resolver_and_unwrap_service_accept_all_supported_hosts(self, final_url):
        resolver = OuoResolver(OuoResolverConfig())
        unwrap_resolver = OuoResolver(
            OuoResolverConfig(allowed_download_hosts=ouo_unwrap._ALLOWED_HOSTS)
        )
        assert resolver.is_valid_final_url(final_url) is True
        assert unwrap_resolver.is_valid_final_url(final_url) is True


# ---------------------------------------------------------------------------
# 8. FichierParser XPath selector list & MEGA UTF-8 filename decryption
# ---------------------------------------------------------------------------


class TestParserAndMegaUtf8:
    def test_fichier_parser_selectors_are_not_implicitly_concatenated(self):
        assert (
            '//a[@href and string-length(@href) > 50 and contains(@href, "1fichier")]'
            in FichierParser.DOWNLOAD_SELECTORS
        )
        assert '//a[contains(@class, "ok btn-general")]' in FichierParser.DOWNLOAD_SELECTORS

    def test_mega_decrypt_attr_preserves_utf8_cjk_filenames(self):
        aes_key = (0x11223344, 0x55667788, 0x99AABBCC, 0xDDEEFF00)
        payload = 'MEGA{"n":"게임_한글파일명_テスト.zip"}'.encode("utf-8")
        padded = payload + b"\0" * ((16 - len(payload) % 16) % 16)
        cipher = AES.new(a32_to_bytes(aes_key), AES.MODE_CBC, b"\0" * 16)
        encrypted = cipher.encrypt(padded)

        attrs = decrypt_attr(encrypted, aes_key)
        assert attrs == {"n": "게임_한글파일명_テスト.zip"}


# ---------------------------------------------------------------------------
# 9. Config non-destructive read on corruption & atomic write
# ---------------------------------------------------------------------------


class TestConfigSafety:
    def test_get_config_does_not_overwrite_corrupted_file_on_disk(
        self, tmp_path, monkeypatch
    ):
        cfg_file = tmp_path / "config.json"
        corrupted_bytes = b'{"telegram_bot_token": "secret-token", "fichier_email": '
        cfg_file.write_bytes(corrupted_bytes)

        monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)

        loaded = config_mod.get_config()
        assert loaded["language"] == config_mod.DEFAULT_CONFIG["language"]
        # Critically, the corrupted file on disk was NOT wiped with DEFAULT_CONFIG
        assert cfg_file.read_bytes() == corrupted_bytes

    def test_save_config_writes_atomically_without_leftover_tmp_files(
        self, tmp_path, monkeypatch
    ):
        cfg_file = tmp_path / "config.json"
        monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(config_mod, "CONFIG_FILE", cfg_file)

        config_mod.save_config({"language": "en", "max_concurrent_downloads": 5}, merge=False)
        config_mod.save_config({"theme": "dark"}, merge=True)

        stored = json.loads(cfg_file.read_text(encoding="utf-8"))
        assert stored["language"] == "en"
        assert stored["max_concurrent_downloads"] == 5
        assert stored["theme"] == "dark"
        tmp_files = list(tmp_path.glob(".*.tmp"))
        assert tmp_files == []


# ---------------------------------------------------------------------------
# 10. Structural guard: zero mid-function imports in modified modules
# ---------------------------------------------------------------------------


class TestTopLevelImportsInModifiedFiles:
    @pytest.mark.parametrize(
        "rel_path",
        [
            "core/download_core.py",
            "core/hoster_sites.py",
            "core/browser_solver.py",
            "core/config.py",
            "utils/file_helpers.py",
            "api/routes/settings.py",
            "services/download_service.py",
        ],
    )
    def test_no_mid_function_imports(self, rel_path):
        tree = ast.parse((BACKEND_ROOT / rel_path).read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if isinstance(child, (ast.Import, ast.ImportFrom)):
                        offenders.append(f"{rel_path}:{child.lineno} in {node.name}()")
        assert offenders == [], f"Mid-function imports found: {offenders}"

    def test_mixdrop_mxdrop_click_redirect_domain_is_supported(self):
        assert canonical_host("mxdrop.click") == "mixdrop.ag"
        assert hp.is_special_hoster_url("https://mxdrop.click/f/k0nv3o6kspdq0n") is True
        assert bs.flow_for_host("mxdrop.click") is bs.MIXDROP_FLOW

        frame = object()
        page = SimpleNamespace(main_frame=frame, url="https://mixdrop.ag/f/k0nv3o6kspdq0n")
        calls = []
        request = SimpleNamespace(
            url="https://mxdrop.click/f/k0nv3o6kspdq0n",
            frame=frame,
            is_navigation_request=lambda: True,
        )
        route = SimpleNamespace(
            request=request,
            fulfill=lambda **kwargs: calls.append("blocked"),
            continue_=lambda: calls.append("allowed"),
        )
        bs._guard_hoster_navigation(route, page, "https://mixdrop.ag/f/k0nv3o6kspdq0n")
        assert calls == ["allowed"]

