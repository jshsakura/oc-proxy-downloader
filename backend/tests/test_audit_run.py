# -*- coding: utf-8 -*-
"""The batch audit loop, actually run.

Every unit around this was covered — target selection, per-host verdicts, how a
verdict is applied — and the loop that ties them together was not. So a local
variable named ``probe_url`` shadowing the imported ``probe_url`` function got
through green tests and into production, where every single item failed with
``'str' object is not callable`` and 262 rows were "audited" without one verdict
being written.

These tests drive the loop end to end against an in-memory database.
"""

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes import audit as audit_route
from core.models import Base, DownloadRequest, StatusEnum
from services.link_probe import KIND_ALIVE, KIND_UNSUPPORTED, ProbeResult
from core.error_messages import KIND_DEAD


DEAD_URL = "https://datanodes.to/gone"
ALIVE_URL = "https://datanodes.to/here"
OFF_SCOPE_URL = "https://multiup.io/download/x/y.nsp"


def _probe_for(url):
    if url == DEAD_URL:
        return ProbeResult(kind=KIND_DEAD, summary="파일 없음", raw_status=404,
                           body_marker="file not found", retry_after_seconds=None,
                           definitive=True)
    if url == ALIVE_URL:
        return ProbeResult(kind=KIND_ALIVE, summary="링크 살아있음", raw_status=200,
                           body_marker=None, retry_after_seconds=None, definitive=True)
    return ProbeResult(kind=KIND_UNSUPPORTED, summary="미지원", raw_status=None,
                       body_marker=None, retry_after_seconds=None, definitive=False)


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture()
def db(session_factory, monkeypatch):
    monkeypatch.setattr(audit_route, "SessionLocal", session_factory)
    session = session_factory()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _stub_probe(monkeypatch):
    """Only the network is faked — the loop itself is the thing under test."""
    async def fake_probe(url):
        return _probe_for(url)

    monkeypatch.setattr(audit_route, "probe_url", fake_probe)


@pytest.fixture(autouse=True)
def _release_lock():
    yield
    if audit_route._audit_lock.locked():
        audit_route._audit_lock.release()


def _run_audit(ids):
    """Drive the batch the way start_audit does — holding the lock, which
    _run_audit releases in its finally block."""
    async def _go():
        await audit_route._audit_lock.acquire()
        await audit_route._run_audit(ids)

    asyncio.run(_go())


def _add(db, url, **kwargs):
    row = DownloadRequest(url=url, status=StatusEnum.stopped,
                          error="원래 실패 사유", **kwargs)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class TestTheLoopActuallyRuns:

    def test_a_dead_link_is_pinned_and_a_live_one_is_cleared(self, db):
        dead = _add(db, DEAD_URL, failure_kind=None)
        alive = _add(db, ALIVE_URL, failure_kind="dead")

        _run_audit([dead.id, alive.id])

        db.expire_all()
        assert db.get(DownloadRequest, dead.id).failure_kind == KIND_DEAD
        assert db.get(DownloadRequest, alive.id).failure_kind is None

    def test_the_verdict_is_committed_not_just_computed(self, db, session_factory):
        """The loop opens its own session per item; a verdict that never lands
        in the database is the same as no audit at all."""
        dead = _add(db, DEAD_URL)

        _run_audit([dead.id])

        other = session_factory()
        try:
            assert other.get(DownloadRequest, dead.id).failure_kind == KIND_DEAD
        finally:
            other.close()

    def test_one_bad_item_does_not_abort_the_batch(self, db, monkeypatch):
        exploded = _add(db, DEAD_URL)
        good = _add(db, ALIVE_URL, failure_kind="dead")
        calls = []

        async def flaky(url):
            calls.append(url)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return _probe_for(url)

        monkeypatch.setattr(audit_route, "probe_url", flaky)

        _run_audit([exploded.id, good.id])

        db.expire_all()
        assert db.get(DownloadRequest, good.id).failure_kind is None

    def test_the_lock_is_released_when_the_batch_ends(self, db):
        """A leaked lock means every later audit answers 409 forever."""
        row = _add(db, DEAD_URL)

        _run_audit([row.id])

        assert not audit_route._audit_lock.locked()


class TestOffScopeRows:

    def test_an_unsupported_host_keeps_its_failure_reason(self, db):
        """The regression that started all of this: a verdict the prober cannot
        back up must not overwrite the real diagnosis."""
        row = _add(db, OFF_SCOPE_URL, failure_kind="transient")

        _run_audit([row.id])

        db.expire_all()
        refreshed = db.get(DownloadRequest, row.id)
        assert refreshed.error == "원래 실패 사유"
        assert refreshed.failure_kind == "transient"
