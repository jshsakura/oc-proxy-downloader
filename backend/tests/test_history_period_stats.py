# -*- coding: utf-8 -*-
"""Tests for /api/history/period, /api/history/stats, and cleanup no-op."""

import asyncio
import datetime
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from core.db import engine, SessionLocal
from core.models import Base, DownloadRequest, StatusEnum
from api.routes.history import router as history_router


@pytest.fixture(scope="module")
def app():
    Base.metadata.create_all(bind=engine)
    application = FastAPI()
    application.include_router(history_router)
    return application


@pytest.fixture(scope="module")
def client(app):
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_db():
    session = SessionLocal()
    try:
        session.query(DownloadRequest).delete()
        session.commit()
    finally:
        session.close()
    yield
    session = SessionLocal()
    try:
        session.query(DownloadRequest).delete()
        session.commit()
    finally:
        session.close()


def _insert_rows(*rows):
    session = SessionLocal()
    try:
        for r in rows:
            session.add(r)
        session.commit()
        ids = [r.id for r in rows]
        return session.query(DownloadRequest).filter(DownloadRequest.id.in_(ids)).all()
    finally:
        session.close()


class TestHistoryPeriod:

    def test_period_pagination_boundaries(self, client):
        base_url = "https://1fichier.com/?pg"
        now = datetime.datetime(2026, 1, 15, 12, 0, 0)
        rows = []
        for i in range(5):
            rows.append(DownloadRequest(
                url=f"{base_url}{i}",
                file_name=f"file{i}.bin",
                status=StatusEnum.done,
                requested_at=now - datetime.timedelta(hours=i),
                total_size=100 * (i + 1),
            ))
        _insert_rows(*rows)

        resp = client.get("/api/history/period", params={
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "page": 1,
            "page_size": 2,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert data["page_size"] == 2
        assert data["total_pages"] == 3
        assert len(data["history"]) == 2

        resp2 = client.get("/api/history/period", params={
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "page": 2,
            "page_size": 2,
        })
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["total"] == 5
        assert len(data2["history"]) == 2

        resp3 = client.get("/api/history/period", params={
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "page": 3,
            "page_size": 2,
        })
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert data3["total"] == 5
        assert len(data3["history"]) == 1

    def test_period_empty_data(self, client):
        resp = client.get("/api/history/period", params={
            "start_date": "2099-01-01",
            "end_date": "2099-12-31",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["total_pages"] == 0
        assert data["history"] == []

    def test_period_status_filter(self, client):
        now = datetime.datetime(2026, 3, 1, 10, 0, 0)
        _insert_rows(
            DownloadRequest(url="u1", status=StatusEnum.done, requested_at=now, total_size=10),
            DownloadRequest(url="u2", status=StatusEnum.failed, requested_at=now, total_size=20),
            DownloadRequest(url="u3", status=StatusEnum.done, requested_at=now, total_size=30),
        )

        resp = client.get("/api/history/period", params={
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "status": "done",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert all(h["status"] == "done" for h in data["history"])

    def test_period_invalid_date_format(self, client):
        resp = client.get("/api/history/period", params={
            "start_date": "not-a-date",
        })
        assert resp.status_code == 400
        assert "YYYY-MM-DD" in resp.json()["detail"]

    def test_period_invalid_status(self, client):
        resp = client.get("/api/history/period", params={
            "start_date": "2026-01-01",
            "status": "nonexistent",
        })
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "Invalid status" in detail
        assert "done" in detail


class TestHistoryStats:

    def test_stats_empty_data(self, client):
        resp = client.get("/api/history/stats", params={
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["success_rate"] == 0.0
        assert data["total_bytes"] == 0
        assert data["proxy_count"] == 0
        assert data["local_count"] == 0
        assert data["by_status"]["done"] == 0
        assert data["daily_trend"] == []

    # The xfail this carried described a cast(Date) bug that no longer exists —
    # the route uses func.date(). It had been passing (reported as xpassed) for
    # long enough that its assertions on totals, byte sums and the proxy split
    # were guarding nothing.
    def test_stats_mixed_statuses_proxy_local_bytes(self, client):
        now = datetime.datetime(2026, 2, 10, 14, 0, 0)
        _insert_rows(
            DownloadRequest(
                url="u1", status=StatusEnum.done, use_proxy=True,
                requested_at=now, total_size=1000, downloaded_size=1000,
            ),
            DownloadRequest(
                url="u2", status=StatusEnum.done, use_proxy=False,
                requested_at=now, total_size=2000, downloaded_size=2000,
            ),
            DownloadRequest(
                url="u3", status=StatusEnum.failed, use_proxy=True,
                requested_at=now, total_size=500, downloaded_size=0,
            ),
            DownloadRequest(
                url="u4", status=StatusEnum.stopped, use_proxy=False,
                requested_at=now, total_size=300, downloaded_size=100,
            ),
        )

        resp = client.get("/api/history/stats", params={
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        })
        assert resp.status_code == 200
        data = resp.json()

        assert data["total"] == 4
        assert data["by_status"]["done"] == 2
        assert data["by_status"]["failed"] == 1
        assert data["by_status"]["stopped"] == 1
        assert data["total_bytes"] == 3800
        assert data["proxy_count"] == 2
        assert data["local_count"] == 2
        assert data["success_rate"] == 50.0
        assert len(data["daily_trend"]) == 1
        trend = data["daily_trend"][0]
        assert trend["date"] == "2026-02-10"
        assert trend["count"] == 4
        assert trend["bytes"] == 3800

    def test_stats_does_not_scan_once_per_status(self, client):
        """The tab badges refresh off every SSE status update, so this endpoint
        runs while downloads are committing progress. It used to issue a COUNT
        per StatusEnum member plus two for the proxy split — a dozen full scans
        competing with the writer, per refresh. One grouped pass replaces them."""
        now = datetime.datetime(2026, 3, 3, 9, 0, 0)
        _insert_rows(
            DownloadRequest(url="q1", status=StatusEnum.done, use_proxy=True,
                            requested_at=now, total_size=10),
            DownloadRequest(url="q2", status=StatusEnum.failed, use_proxy=False,
                            requested_at=now, total_size=20),
        )

        statements = []
        listener = lambda conn, cursor, stmt, *a: statements.append(stmt)
        event.listen(engine, "before_cursor_execute", listener)
        try:
            resp = client.get("/api/history/stats")
        finally:
            event.remove(engine, "before_cursor_execute", listener)

        assert resp.status_code == 200
        selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
        assert len(selects) <= 3, (
            f"{len(selects)} queries for one stats call — a per-status COUNT is back:\n"
            + "\n".join(selects)
        )

    def test_stats_counts_a_row_whose_status_was_never_migrated(self, client):
        """A NULL status belongs in the total, but must not become a badge key
        the UI would then render as an unknown tab count."""
        now = datetime.datetime(2026, 3, 4, 9, 0, 0)
        _insert_rows(
            DownloadRequest(url="n1", status=None, use_proxy=False,
                            requested_at=now, total_size=100),
            DownloadRequest(url="n2", status=StatusEnum.done, use_proxy=False,
                            requested_at=now, total_size=200),
        )

        data = client.get("/api/history/stats").json()

        assert data["total"] == 2
        assert data["total_bytes"] == 300
        assert data["by_status"]["done"] == 1
        assert set(data["by_status"]) == {s.value for s in StatusEnum}

    def test_stats_invalid_date(self, client):
        resp = client.get("/api/history/stats", params={
            "start_date": "bad",
        })
        assert resp.status_code == 400
        assert "YYYY-MM-DD" in resp.json()["detail"]


class TestCleanupNoOp:

    @pytest.mark.skipif(
        True,
        reason="download_service import chain requires aiofiles (not installed in test env)"
    )
    def test_cleanup_is_noop(self):
        from services.download_service import download_service

        old_time = datetime.datetime(2020, 1, 1, 0, 0, 0)
        row = DownloadRequest(
            url="https://1fichier.com/?old",
            file_name="old_file.zip",
            status=StatusEnum.done,
            requested_at=old_time,
            total_size=999,
            downloaded_size=999,
        )
        _insert_rows(row)

        result = asyncio.get_event_loop().run_until_complete(
            download_service.cleanup_completed_downloads(older_than_hours=24)
        )
        assert result == 0

        session = SessionLocal()
        try:
            count = session.query(DownloadRequest).filter(
                DownloadRequest.url == "https://1fichier.com/?old"
            ).count()
            assert count == 1
        finally:
            session.close()


class TestFailureKindSource:
    """The stored verdict wins over re-reading the error text."""

    def test_a_pinned_kind_is_not_re_derived_from_the_text(self, client):
        """A probe pins `dead` in the column. Re-classifying the text on every
        response would let a reworded regex silently overturn that verdict, and
        the retry guard reads this field."""
        now = datetime.datetime(2026, 4, 1, 10, 0, 0)
        _insert_rows(DownloadRequest(
            url="https://1fichier.com/?pinned", status=StatusEnum.failed,
            requested_at=now, error="일시적인 네트워크 오류로 보이는 문구",
            failure_kind="dead",
        ))

        rows = client.get("/api/downloads/working").json()["downloads"]

        assert [r["failure_kind"] for r in rows] == ["dead"]

    def test_a_row_without_a_stored_kind_still_falls_back_to_the_text(self, client):
        """Pre-migration rows have a NULL column and must keep classifying."""
        now = datetime.datetime(2026, 4, 2, 10, 0, 0)
        _insert_rows(DownloadRequest(
            url="https://1fichier.com/?legacy", status=StatusEnum.failed,
            requested_at=now, error="페이지 로드 실패: HTTP 404", failure_kind=None,
        ))

        rows = client.get("/api/downloads/working").json()["downloads"]

        assert rows[0]["failure_kind"] not in (None, "")
