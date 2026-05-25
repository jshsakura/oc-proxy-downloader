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


class _Req:
    def __init__(self):
        self.id = 1
        self.url = "https://megaup.net/abc/file.rar"
        self.password = None
        self.status = StatusEnum.pending
        self.finished_at = None


class _Verdict:
    user_message = "timeout"
    kind = "unknown"
    next_retry_at = None
    attempt_count = 1


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
