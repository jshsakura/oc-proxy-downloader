# -*- coding: utf-8 -*-
"""Regression test: special-hoster parsing must not hang forever.

MegaUp/DataNodes resolution chains several network calls. If one stalls, the
download used to sit in the ``parsing`` state indefinitely and never release
its per-site semaphore. A hard cap now fails the download instead. This test
makes the underlying parse block longer than a shrunk cap and asserts the task
fails promptly rather than waiting on the hung call.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import core.download_core as dc_mod
from core.download_core import DownloadCore
from core.models import StatusEnum
from core.hoster_common import HosterParseError


class _Req:
    def __init__(self):
        self.id = 1
        self.url = "https://megaup.net/abc/file.rar"
        self.password = None
        self.status = StatusEnum.pending
        self.finished_at = None
        self.use_proxy = False
        self.file_name = "file.rar"
        self.file_size = None
        self.total_size = 0


class _Verdict:
    user_message = "timeout"
    kind = "unknown"
    next_retry_at = None
    attempt_count = 1


@pytest.mark.parametrize("raw,expected", [
    ("MultiUp 모든 지원 미러 실패 (Gofile 파일 없음)", False),
    ("DataVaults 무료 다운로드에 reCAPTCHA v2 사람 확인이 필요합니다", False),
    ("HTTP 404: Not Found", False),
    ("HTTP 503: Service Unavailable", False),
    ("HTTP 429: Too Many Requests", False),
    ("Connection reset by peer", True),
    ("Read timeout occurred", True),
])
def test_proxy_rotation_only_for_transport_failure(raw, expected):
    assert dc_mod._retry_special_parse_on_next_proxy(raw) is expected


@pytest.mark.asyncio
async def test_parsing_times_out_instead_of_hanging(monkeypatch):
    dc = DownloadCore()
    dc.send_download_update = AsyncMock()

    # Shrink the cap and make the parse block well past it.
    monkeypatch.setattr(dc_mod, "SPECIAL_HOSTER_PARSE_TIMEOUT_SEC", 0.2, raising=True)
    monkeypatch.setattr(
        dc_mod, "parse_special_hoster_sync",
        lambda *a, **k: time.sleep(1.5),  # hangs (returns None after the cap)
        raising=True,
    )
    monkeypatch.setattr(
        dc_mod, "apply_failure_to_request",
        lambda *a, **k: _Verdict(), raising=True,
    )

    req = _Req()
    started = time.monotonic()
    await dc._download_special_hoster_async(req, MagicMock())
    elapsed = time.monotonic() - started

    # Failed (not stuck in parsing), and returned at the cap — not after the hang.
    assert req.status == StatusEnum.failed
    assert elapsed < 1.0, f"did not time out promptly (took {elapsed:.2f}s)"
    dc.send_download_update.assert_awaited()


@pytest.mark.asyncio
async def test_human_verification_does_not_cycle_through_proxies(monkeypatch):
    dc = DownloadCore()
    dc.send_download_update = AsyncMock()
    req = _Req()
    req.url = "https://datavaults.co/abc/file.nsp"
    req.use_proxy = True
    parse = MagicMock(side_effect=HosterParseError("DataVaults 무료 다운로드에 reCAPTCHA v2 사람 확인이 필요합니다"))
    next_proxy = AsyncMock(return_value="proxy.example:8888")
    failed_proxy = AsyncMock()
    monkeypatch.setattr(dc_mod, "parse_special_hoster_sync", parse)
    monkeypatch.setattr(dc_mod.proxy_manager, "get_user_proxy_list", AsyncMock(return_value=["p1", "p2", "p3"]))
    monkeypatch.setattr(dc_mod.proxy_manager, "get_next_available_proxy", next_proxy)
    monkeypatch.setattr(dc_mod.proxy_manager, "mark_proxy_failed", failed_proxy)
    monkeypatch.setattr(dc_mod.proxy_manager, "get_total_failed_count", AsyncMock(return_value=0))
    monkeypatch.setattr(dc_mod.db_async, "commit", AsyncMock())
    monkeypatch.setattr(dc_mod.db_async, "refresh", AsyncMock())
    monkeypatch.setattr(dc_mod.sse_manager, "broadcast_message", AsyncMock())
    monkeypatch.setattr(dc_mod, "apply_failure_to_request", lambda *a, **k: _Verdict())

    await dc._download_special_hoster_async(req, MagicMock())

    assert parse.call_count == 1
    assert next_proxy.await_count == 1
    failed_proxy.assert_not_awaited()
