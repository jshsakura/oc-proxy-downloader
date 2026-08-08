# -*- coding: utf-8 -*-
"""Adding a URL must answer immediately.

``POST /api/download/`` used to insert the row, resolve ouo shortlinks and
start the parse before answering. Every one of those steps waits on something
slow — the SQLite write lock a running download holds, FlareSolverr, a headless
browser — so the response regularly took 10-20s and sometimes minutes. The
oc-scraper integration posts with a 30s timeout and reports a timeout as a
failed enqueue, which is how a working downloader ended up showing every send
from the board as "전송 실패".

The contract these tests pin: the response comes back before any of that work
runs, and the work still happens afterwards.
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes import downloads as downloads_route
from core.db import engine as app_engine
from core.models import Base, DownloadRequest, StatusEnum


OUO_URL = "https://ouo.io/qs8Ktz"
PLAIN_URL = "https://pixeldrain.com/u/handoff-test"


@pytest.fixture()
def session_factory():
    """An isolated in-memory DB, shared by the request and the background task.

    StaticPool keeps every caller on the one connection that holds the schema —
    the insert runs in a worker thread, which would otherwise get a fresh, empty
    in-memory database.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db(session_factory, monkeypatch):
    """Point the background start at the same DB the request writes to."""
    monkeypatch.setattr(downloads_route, "SessionLocal", session_factory)
    session = session_factory()
    yield session
    session.close()


async def drain_background_starts():
    """Wait for the tasks the route scheduled, the way the running app would."""
    while downloads_route._start_tasks:
        await asyncio.gather(*list(downloads_route._start_tasks))


@pytest.fixture()
def started(monkeypatch):
    """Record the ids handed to the download core instead of starting anything."""
    calls = []

    async def fake_start(req, _db):
        calls.append(req.id)
        return True

    monkeypatch.setattr(downloads_route.download_core, "start_download_async", fake_start)
    return calls


@pytest.mark.asyncio
async def test_response_precedes_the_download_start(db, started):
    """The row exists when the caller is answered; the start has not run yet."""
    result = await downloads_route.add_download({"url": PLAIN_URL}, db)

    assert result["status"] == "pending"
    assert started == [], "the response waited for the download to start"

    await drain_background_starts()

    assert started == [result["id"]]


@pytest.mark.asyncio
async def test_the_row_is_committed_before_the_response(db, started):
    """A caller that immediately polls the id must find it — an in-flight
    background start is not an excuse for a 404."""
    result = await downloads_route.add_download({"url": PLAIN_URL}, db)

    stored = db.query(DownloadRequest).filter(DownloadRequest.id == result["id"]).first()
    assert stored is not None
    assert stored.url == PLAIN_URL
    assert stored.status == StatusEnum.pending


@pytest.mark.asyncio
async def test_ouo_shortlinks_are_not_resolved_inside_the_request(db, started, monkeypatch):
    """Resolving a shortlink drives a browser and can take minutes. The request
    stores it as-is; the background start is what unwraps it."""
    unwrap_calls = []

    def fake_unwrap(url):
        unwrap_calls.append(url)
        return "https://pixeldrain.com/u/unwrapped"

    monkeypatch.setattr(downloads_route, "unwrap_if_ouo", fake_unwrap)

    result = await downloads_route.add_download({"url": OUO_URL}, db)

    assert unwrap_calls == [], "the response waited for the ouo unwrap"
    stored = db.query(DownloadRequest).filter(DownloadRequest.id == result["id"]).first()
    assert stored.url == OUO_URL
    assert stored.original_url == OUO_URL, "the shortlink must survive the unwrap"

    await drain_background_starts()

    assert unwrap_calls == [OUO_URL]
    db.expire_all()
    assert stored.url == "https://pixeldrain.com/u/unwrapped"
    assert started == [result["id"]]


@pytest.mark.asyncio
async def test_a_failed_unwrap_leaves_a_retryable_row(db, started, monkeypatch):
    """A shortlink that cannot be resolved is a transient failure on a real row,
    not a 502 that loses the URL the caller sent."""
    monkeypatch.setattr(downloads_route, "unwrap_if_ouo", lambda url: None)

    result = await downloads_route.add_download({"url": OUO_URL}, db)
    await drain_background_starts()

    db.expire_all()
    stored = db.query(DownloadRequest).filter(DownloadRequest.id == result["id"]).first()
    assert stored.status == StatusEnum.failed
    assert stored.failure_kind == downloads_route.KIND_TRANSIENT
    assert started == []


@pytest.mark.asyncio
async def test_a_re_added_shortlink_matches_the_completed_download(db, started, monkeypatch):
    """Dedup keys on the URL that was sent. For an ouo link the stored url is
    the resolved one, so the match has to come off original_url."""
    monkeypatch.setattr(downloads_route.os.path, "exists", lambda path: True)
    done = DownloadRequest(
        url="https://pixeldrain.com/u/unwrapped",
        original_url=OUO_URL,
        status=StatusEnum.done,
        save_path="/downloads/already-there.nsp",
        file_name="already-there.nsp",
    )
    db.add(done)
    db.commit()

    result = await downloads_route.add_download({"url": OUO_URL}, db)

    assert result["already_completed"] is True
    assert result["id"] == done.id
    assert started == []


def test_the_app_database_runs_in_wal_mode():
    """WAL is what keeps a progress-writing download from locking out an INSERT.
    Without it the handoff above still queues behind the write lock."""
    with app_engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        busy = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()

    assert mode.lower() == "wal"
    assert busy >= 10_000
