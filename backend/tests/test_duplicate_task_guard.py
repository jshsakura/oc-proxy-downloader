# -*- coding: utf-8 -*-
"""Regression test for the duplicate download-task guard.

A retry press, the auto-start-next sweep, and restart-after-reboot can all
re-enter ``start_download_async`` for an id that is already running — e.g. a
download parked in the ``pending`` state while it waits on a per-site
semaphore still holds a live task. Before the guard, a second task was created
and overwrote ``download_tasks[id]``, orphaning the first. Both then wrote the
same ``.part`` file (clobbering the download) and a deleted row could be
resurrected by an orphan's commit. The guard makes the re-entrant call a no-op.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.download_core import DownloadCore


class _Req:
    """Minimal stand-in — the guard only reads ``.id`` before returning."""

    def __init__(self, req_id):
        self.id = req_id


@pytest.mark.asyncio
async def test_start_download_is_noop_when_live_task_exists():
    dc = DownloadCore()
    live_task = MagicMock()
    live_task.done.return_value = False
    dc.download_tasks[7] = live_task

    result = await dc.start_download_async(_Req(7), MagicMock())

    # Reports success (the caller's intent — "this download is running" — holds)
    assert result is True
    # The existing task is untouched: no duplicate/replacement was created.
    assert dc.download_tasks[7] is live_task
    assert len(dc.download_tasks) == 1


@pytest.mark.asyncio
async def test_finished_task_does_not_trigger_the_guard(monkeypatch):
    """A previously finished task must not block a fresh (re)start.

    The method's broad ``except`` swallows downstream errors and returns False,
    so we can't assert via a raised exception. Instead we prove the guard was
    NOT taken by observing a side effect from the first post-guard line —
    ``cancel_signal.clear(req.id)`` only runs when execution falls through.
    """
    dc = DownloadCore()
    dc.send_download_update = AsyncMock()  # avoid real SSE in the except path
    finished_task = MagicMock()
    finished_task.done.return_value = True
    dc.download_tasks[9] = finished_task

    cleared = {}
    monkeypatch.setattr(
        "core.download_core.cancel_signal.clear",
        lambda req_id: cleared.setdefault("id", req_id),
        raising=True,
    )

    # ``req.url`` is touched right after the guard; raising there halts the
    # pipeline cheaply (the error is caught internally and returns False).
    class _RaisingReq:
        id = 9

        @property
        def url(self):
            raise RuntimeError("reached post-guard logic")

    result = await dc.start_download_async(_RaisingReq(), MagicMock())

    assert cleared.get("id") == 9, "guard wrongly short-circuited a finished task"
    assert result is False
