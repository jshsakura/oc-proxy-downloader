# -*- coding: utf-8 -*-
"""Waiting for a download slot without holding a database connection.

A download task opens its session at the top and used to keep it open for the
whole run — including the stretch where it is parked on a semaphore waiting its
turn. On a busy queue most tasks are waiting, not transferring, so the app's
live connections tracked *queued* items rather than working ones. Under
``NullPool`` every one of those is a real open file, which is exactly the
resource that ran out and reported itself as
``sqlite3.OperationalError: unable to open database file``.

Nothing needs the session during the wait. Closing it first costs one reconnect
per download and removes the whole class of waste.

**A closed SQLAlchemy session is still usable** — it releases its connection and
expunges its objects, then transparently reconnects on the next query. That is
why the caller keeps the same session object; what it must NOT do is keep using
an ORM instance loaded before the wait, because that instance is now detached.
Re-fetch the row inside the block.
"""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager


class DownloadSlots:
    """A resizable admission limit that preserves holders and waiting tasks.

    Replacing a semaphore on settings changes creates two independent queues.
    Keep one object instead; lowering its limit lets holders drain before new
    work enters. All methods run on the application's asyncio loop.
    """

    def __init__(self, limit: int):
        if limit < 1:
            raise ValueError("download limit must be positive")
        self.limit = limit
        self._active = 0
        self._changed = asyncio.Event()
        self._loop = None

    @property
    def _value(self):
        return max(0, self.limit - self._active)

    def locked(self):
        return self._value == 0

    def _notify(self):
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()

    def set_limit(self, limit: int):
        if limit < 1:
            raise ValueError("download limit must be positive")
        # FastAPI's synchronous settings route runs in a worker thread.
        # Waking asyncio waiters must happen on their own event loop.
        if self._loop is not None and self._loop.is_running():
            try:
                current_loop = asyncio.get_running_loop()
            except RuntimeError:
                current_loop = None
            if current_loop is not self._loop:
                self._loop.call_soon_threadsafe(self.set_limit, limit)
                return
        self.limit = limit
        self._notify()

    async def acquire(self):
        self._loop = asyncio.get_running_loop()
        while self.locked():
            await self._changed.wait()
        self._active += 1
        return True

    def release(self):
        if self._active < 1:
            raise ValueError("download slot released without a holder")
        self._active -= 1
        self._notify()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *exc):
        self.release()


@asynccontextmanager
async def slot_without_session(db, *semaphores):
    """Acquire `semaphores` in order while holding no database connection.

    The session is closed before the wait begins and left for the caller to use
    again inside the block — re-fetch any row you need, since closing detached
    what you had.

    Semaphores are entered in the order given and released in reverse, so pass
    the narrowest queue first: a task waiting on a global ceiling then holds only
    its own host's slot and can never block a different host from starting.
    """
    db.close()
    async with AsyncExitStack() as stack:
        for semaphore in semaphores:
            await stack.enter_async_context(semaphore)
        yield
