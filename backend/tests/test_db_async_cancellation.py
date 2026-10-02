# -*- coding: utf-8 -*-
"""A cancelled DB call must not leave its worker thread running.

``asyncio.to_thread`` cannot interrupt a thread. When the awaiting task was
cancelled (a download being stopped), the task's ``finally`` closed the session
while the thread was still executing a query on the same SQLite connection. Two
threads on one connection crashed the whole process with a segfault.
"""

import asyncio
import threading

import pytest

from core import db_async


class _SlowDB:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = False

    def commit(self):
        self.started.set()
        self.release.wait(timeout=5)
        self.finished = True


@pytest.mark.asyncio
async def test_cancelled_call_waits_for_its_worker_thread_before_raising():
    db = _SlowDB()
    task = asyncio.create_task(db_async.commit(db))
    while not db.started.is_set():
        await asyncio.sleep(0.01)

    task.cancel()
    asyncio.get_running_loop().call_later(0.2, db.release.set)

    with pytest.raises(asyncio.CancelledError):
        await task
    # By the time the caller's ``finally`` can run, the thread is done with the
    # connection, so closing the session is safe.
    assert db.finished is True


@pytest.mark.asyncio
async def test_uncancelled_call_still_returns_its_result():
    class DB:
        def refresh(self, instance):
            instance.touched = True

    class Row:
        touched = False

    row = Row()
    await db_async.refresh(DB(), row)
    assert row.touched is True
