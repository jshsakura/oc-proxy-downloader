# -*- coding: utf-8 -*-
"""Unit tests for the audit route's lock management / filter selector.

Most important regression guards:
- Even if two requests arrive at once, only one passes (lock race condition #2).
- On empty results or exceptions, the lock is always released so the next request is accepted.
- ``_select_targets`` AND-combines the ids/status/failure_kinds/since/until filters.
"""

import asyncio
import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, DownloadRequest, StatusEnum
from api.routes.audit import (
    AuditRequest,
    _select_targets,
    _audit_lock,
    start_audit,
)


@pytest.fixture()
def memory_db():
    """An isolated in-memory SQLite session + sample data for unit tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    now = datetime.datetime(2026, 5, 1, 12, 0, 0)
    sample_rows = [
        DownloadRequest(
            url="https://1fichier.com/?a", status=StatusEnum.failed,
            failure_kind="dead", requested_at=now,
        ),
        DownloadRequest(
            url="https://1fichier.com/?b", status=StatusEnum.failed,
            failure_kind="cloudflare", requested_at=now + datetime.timedelta(days=1),
        ),
        DownloadRequest(
            url="https://1fichier.com/?c", status=StatusEnum.stopped,
            failure_kind=None, requested_at=now + datetime.timedelta(days=2),
        ),
        DownloadRequest(
            url="https://1fichier.com/?d", status=StatusEnum.done,
            failure_kind=None, requested_at=now + datetime.timedelta(days=3),
        ),
    ]
    for r in sample_rows:
        db.add(r)
    db.commit()
    yield db
    db.close()


@pytest.fixture(autouse=True)
def reset_audit_lock():
    """Release a held lock after each test — it is a global singleton, so a leak breaks the next test."""
    yield
    if _audit_lock.locked():
        _audit_lock.release()


class TestSelectTargets:
    def test_default_filter_returns_failed_and_stopped(self, memory_db):
        # failed (a, b) + stopped (c) — done (d) excluded
        ids = _select_targets(AuditRequest(), memory_db)
        assert len(ids) == 3

    def test_ids_overrides_other_filters(self, memory_db):
        # Specify only d (status=done) by id — other status filters ignored
        d = memory_db.query(DownloadRequest).filter_by(
            url="https://1fichier.com/?d"
        ).first()
        req = AuditRequest(ids=[d.id], status_filter=["failed"])
        assert _select_targets(req, memory_db) == [d.id]

    def test_failure_kinds_filter(self, memory_db):
        req = AuditRequest(failure_kinds=["dead"])
        ids = _select_targets(req, memory_db)
        # Only dead matches — just a (1)
        rows = memory_db.query(DownloadRequest).filter(
            DownloadRequest.id.in_(ids)
        ).all()
        assert all(r.failure_kind == "dead" for r in rows)
        assert len(rows) == 1

    def test_since_until_filter_narrows_period(self, memory_db):
        since = datetime.datetime(2026, 5, 2, 0, 0, 0)
        until = datetime.datetime(2026, 5, 3, 23, 59, 59)
        req = AuditRequest(since=since, until=until)
        ids = _select_targets(req, memory_db)
        # b (5/2), c (5/3) — d (done) excluded, a (5/1) also excluded
        rows = memory_db.query(DownloadRequest).filter(
            DownloadRequest.id.in_(ids)
        ).all()
        assert len(rows) == 2
        for r in rows:
            assert since <= r.requested_at <= until

    def test_only_with_failure_kind_excludes_null(self, memory_db):
        req = AuditRequest(only_with_failure_kind=True)
        ids = _select_targets(req, memory_db)
        rows = memory_db.query(DownloadRequest).filter(
            DownloadRequest.id.in_(ids)
        ).all()
        # c is excluded because failure_kind=NULL
        assert all(r.failure_kind is not None for r in rows)

    def test_failure_kinds_takes_precedence_over_only_with(self, memory_db):
        # When failure_kinds is specified, only_with_failure_kind is ignored (already narrower)
        req = AuditRequest(
            failure_kinds=["cloudflare"], only_with_failure_kind=False
        )
        ids = _select_targets(req, memory_db)
        rows = memory_db.query(DownloadRequest).filter(
            DownloadRequest.id.in_(ids)
        ).all()
        assert len(rows) == 1
        assert rows[0].failure_kind == "cloudflare"

    def test_limit_caps_result(self, memory_db):
        req = AuditRequest(limit=1)
        ids = _select_targets(req, memory_db)
        assert len(ids) == 1


class TestAuditLockRace:
    """Guards against defect #2 — only one side may pass on concurrent requests.

    The real background task uses the module-level ``SessionLocal``, so it crashes
    immediately in the unit-test environment (no tables). Therefore we acquire/release
    the lock manually and verify only the gating logic of ``start_audit`` directly.
    """

    @pytest.mark.asyncio
    async def test_locked_state_returns_409(self, memory_db):
        # Assume the lock is already held externally
        await _audit_lock.acquire()
        try:
            with pytest.raises(HTTPException) as exc:
                await start_audit(AuditRequest(), memory_db)
            assert exc.value.status_code == 409
            assert exc.value.detail == "audit_already_running"
        finally:
            _audit_lock.release()

    @pytest.mark.asyncio
    async def test_no_targets_releases_lock(self):
        """Right after a zero-target response, the lock must be released so the next request can be accepted."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        db.add(DownloadRequest(url="https://x", status=StatusEnum.done))
        db.commit()

        # Start with the lock not held → 0 targets → lock released immediately
        first = await start_audit(AuditRequest(), db)
        assert first["started"] is False
        assert first["total"] == 0
        assert not _audit_lock.locked()

        # The next call passes with the same result (no lock leak)
        second = await start_audit(AuditRequest(), db)
        assert second["started"] is False
        assert not _audit_lock.locked()
        db.close()
