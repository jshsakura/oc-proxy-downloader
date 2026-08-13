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

from contextlib import AsyncExitStack, asynccontextmanager


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
