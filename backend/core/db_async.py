# -*- coding: utf-8 -*-
"""Session calls hopped off the event loop.

A running download commits progress continuously, so SQLite's write lock is
held for much of a download's life. An ``async def`` handler that executes a
query or commits waits for that lock *on the event loop*, which stalls every
other request in the app — the failure that made every send from the board time
out while the downloader itself was healthy.

These helpers move the wait into a worker thread, where it costs one request
instead of all of them.

Building a query (``db.query(...).filter(...)``) is lazy and touches nothing, so
the hop wraps the terminal call rather than the construction: build the query
inline, pass it here to run it.

One caveat when using these: ``Session`` expires its objects on commit, so
reading an attribute *after* ``commit(db)`` issues a fresh SELECT — back on the
event loop. Capture what the response needs into locals before committing.
"""

import asyncio
from typing import Any, List, Optional

from sqlalchemy.orm import Query, Session


async def first(query: Query) -> Optional[Any]:
    """``query.first()``, off the loop."""
    return await asyncio.to_thread(query.first)


async def all_rows(query: Query) -> List[Any]:
    """``query.all()``, off the loop."""
    return await asyncio.to_thread(query.all)


async def count(query: Query) -> int:
    """``query.count()``, off the loop."""
    return await asyncio.to_thread(query.count)


async def commit(db: Session) -> None:
    """``db.commit()``, off the loop. This is the call that waits on the write
    lock, and the one that used to freeze the app."""
    await asyncio.to_thread(db.commit)


def _reload(db: Session, model, row_ids: List[int]) -> None:
    """Load the rows, which re-populates the identity map for those instances."""
    db.query(model).filter(model.id.in_(row_ids)).all()


async def reload(db: Session, model, row_ids: List[int]) -> None:
    """Un-expire instances that a commit invalidated, in one query, off the loop.

    ``commit()`` expires every instance it flushed, so the next attribute read
    on any of them issues a fresh SELECT — back on the event loop, once per row.
    A bulk restart hit that for each item it had just written. Collect the ids
    *before* committing (reading ``.id`` afterwards is itself one of those
    SELECTs) and pass them here.
    """
    if not row_ids:
        return
    await asyncio.to_thread(_reload, db, model, row_ids)
