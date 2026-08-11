# -*- coding: utf-8 -*-
"""A backlog must not run the app out of database connections.

Restarting 65 queued downloads took the whole service down:

    QueuePool limit of size 10 overflow 20 reached, connection timed out

Every download task opens a session and keeps it for the life of the download,
including the part where it is parked on a semaphore waiting for a slot. So the
number of live sessions tracks how many items are *queued*, not how many are
transferring — a 65-item backlog wanted 65 connections against a pool of 30.
The 31st waited a minute and failed, and the API went down with it, because
answering a request needs a connection too.

The queue is unbounded by design, so no fixed pool size is the answer. For
SQLite a connection is a file handle; pooling one was never worth an outage.
"""

import sqlalchemy
from sqlalchemy.pool import NullPool

import pytest

from core.db import SessionLocal, engine
from core.models import Base, DownloadRequest


@pytest.fixture(autouse=True, scope="module")
def _schema():
    """The isolated test database starts empty; the query below needs a table."""
    Base.metadata.create_all(bind=engine)


# Comfortably past the old 10 + 20 ceiling, and past any backlog seen so far.
CONCURRENT_SESSIONS = 80


def test_the_engine_has_no_connection_ceiling():
    """A ceiling caps the queue, and the queue is not something we cap."""
    assert isinstance(engine.pool, NullPool)


def test_many_sessions_can_be_held_at_once():
    """The shape of the failure: sessions opened, then held, then used.

    Holding is the point — closing each one before opening the next would pass
    against the old pool too and prove nothing.
    """
    sessions = [SessionLocal() for _ in range(CONCURRENT_SESSIONS)]
    try:
        for session in sessions:
            session.execute(sqlalchemy.text("SELECT 1")).scalar()
    finally:
        for session in sessions:
            session.close()


def test_a_request_can_still_be_served_while_a_backlog_holds_sessions():
    """The part that turned a stalled queue into an outage: with every
    connection taken, the API could not answer either."""
    held = [SessionLocal() for _ in range(CONCURRENT_SESSIONS)]
    for session in held:
        session.execute(sqlalchemy.text("SELECT 1"))
    try:
        latecomer = SessionLocal()
        try:
            # What a list endpoint does. It must not wait on the backlog.
            latecomer.query(DownloadRequest).limit(1).all()
        finally:
            latecomer.close()
    finally:
        for session in held:
            session.close()
