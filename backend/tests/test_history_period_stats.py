# -*- coding: utf-8 -*-
"""Tests for /api/history/period, /api/history/stats, and cleanup no-op."""

import asyncio
import datetime
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

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

    def test_stats_invalid_date(self, client):
        resp = client.get("/api/history/stats", params={
            "start_date": "bad",
        })
        assert resp.status_code == 400
        assert "YYYY-MM-DD" in resp.json()["detail"]


class TestCleanupNoOp:

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
