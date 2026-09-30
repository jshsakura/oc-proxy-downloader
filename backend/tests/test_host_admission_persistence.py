"""Real SQLite and local HTTP regressions for durable host admission."""

import asyncio
import datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp import web
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from core import download_core as module
from core.download_core import DownloadCore
from core.error_messages import KIND_RATE_LIMITED
from core.models import Base, DownloadRequest, HostAdmissionState, StatusEnum


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'admission.db'}",
        connect_args={"check_same_thread": False}, poolclass=NullPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def core(monkeypatch):
    monkeypatch.setattr(module, "_read_concurrency_limits", lambda: (8, 3))
    result = DownloadCore()
    result.send_download_update = AsyncMock()
    monkeypatch.setattr(module, "send_telegram_notification", lambda *a, **k: None)
    return result


def refusal(raw, until):
    return SimpleNamespace(
        failure_kind=KIND_RATE_LIMITED, next_retry_at=until,
        attempts_json=json.dumps([{"raw": raw}]),
    )


@pytest.mark.asyncio
async def test_confirmed_cap_and_wait_survive_restart_without_download_history(core, sessions):
    until = datetime.datetime.now() + datetime.timedelta(hours=2)
    with sessions() as db:
        await core._record_host_refusal(
            refusal("Only one file at a time", until), db,
            "akirabox.com", "akirabox.com@direct",
        )
    # The new instance has no per-download attempts or rows to learn from.
    restarted = DownloadCore()
    with sessions() as db:
        assert db.query(DownloadRequest).count() == 0
        await restarted.restore_host_admission(db)
    assert restarted._resolve_host_limit("https://akirabox.to/a") == ("akirabox.com", 1)
    assert restarted._host_cooldown_until["akirabox.com@direct"] == until
    assert restarted.total_download_semaphore._value == 8


@pytest.mark.asyncio
async def test_concurrent_refusals_keep_longest_wait_and_only_one_record(core, sessions):
    now = datetime.datetime.now()
    short, long = now + datetime.timedelta(minutes=10), now + datetime.timedelta(hours=2)

    async def record(until):
        with sessions() as db:
            await core._record_host_refusal(refusal("HTTP 429", until), db,
                                            "gofile.io", "gofile.io@direct")

    await asyncio.gather(record(long), record(short), record(long))
    with sessions() as db:
        row = db.query(HostAdmissionState).one()
        assert row.cooldown_until == long
        assert row.max_downloads is None


@pytest.mark.asyncio
async def test_generic_429_does_not_erase_a_previously_confirmed_cap(core, sessions):
    now = datetime.datetime.now()
    with sessions() as db:
        await core._record_host_refusal(refusal("Only one download", now), db,
                                        "gofile.io", "gofile.io@direct")
    fresh = DownloadCore()
    with sessions() as db:
        await fresh._record_host_refusal(refusal("HTTP 429", now), db,
                                         "gofile.io", "gofile.io@direct")
    restored = DownloadCore()
    with sessions() as db:
        await restored.restore_host_admission(db)
    assert restored._resolve_host_limit("https://gofile.io/d/a") == ("gofile.io", 1)
    assert restored._host_cooldown_until  # even a past supplied deadline gets a fresh safety wait


def test_new_safety_table_preserves_existing_downloads(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    try:
        DownloadRequest.__table__.create(engine)
        factory = sessionmaker(bind=engine)
        with factory() as db:
            db.add(DownloadRequest(url="https://example.test/file", file_name="existing.rar"))
            db.commit()
        Base.metadata.create_all(engine)
        Base.metadata.create_all(engine)  # repeated startup is harmless
        with factory() as db:
            assert db.query(DownloadRequest).one().file_name == "existing.rar"
            assert db.query(HostAdmissionState).count() == 0
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 200])
async def test_actual_429_is_not_retried_and_restart_queue_waits_before_http(
    core, sessions, monkeypatch, tmp_path, status,
):
    requests = []

    async def limited(request):
        requests.append(request.path)
        return web.Response(status=status, text="Only one file at a time", content_type="text/html",
                            headers={"Retry-After": "1800"})

    app = web.Application()
    app.router.add_get("/file", limited)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}/file"
    try:
        with sessions() as db:
            req = DownloadRequest(
                url=url, original_url="https://gofile.io/d/a", use_proxy=False,
                file_name="file.rar", file_size="1 MB", total_size=0,
                save_path=str(tmp_path / "file.rar.part"),
                status=StatusEnum.downloading, started_at=datetime.datetime.now(),
            )
            db.add(req)
            db.commit()
            with pytest.raises(Exception, match="HTTP 429" if status == 429 else "only one file"):
                await core._download_file_directly(req, db, url, max_reparse=0)
            assert requests == ["/file"]
            assert req.failure_kind == KIND_RATE_LIMITED
            assert req.next_retry_at is None  # refusal is never automatically probed again
            assert not (tmp_path / "file.rar.part").exists()
            await core._record_host_refusal(req, db, "gofile.io", "gofile.io@direct")
            assert core._host_cooldown_until["gofile.io@direct"] >= (
                datetime.datetime.now() + datetime.timedelta(seconds=1799)
            )
            db.delete(req)
            db.commit()

        restarted = DownloadCore()
        waiting = asyncio.Event()

        async def update(req_id, data):
            if data.get("status") == "pending" and data.get("next_retry_at"):
                waiting.set()

        restarted.send_download_update = AsyncMock(side_effect=update)
        monkeypatch.setattr(module, "SessionLocal", sessions)
        with sessions() as db:
            await restarted.restore_host_admission(db)
            queued = DownloadRequest(
                url=url, original_url="https://gofile.io/d/b", use_proxy=False,
                status=StatusEnum.pending, file_name="second.rar", file_size="1 MB",
            )
            db.add(queued)
            db.commit()
            queued_id = queued.id
        task = asyncio.create_task(restarted._download_task(queued_id))
        try:
            await asyncio.wait_for(waiting.wait(), 1)
            assert requests == ["/file"], "restart must not bypass the stored host wait"
            assert restarted.total_download_semaphore._value == 8
            assert restarted._resolve_host_limit("https://gofile.io/d/b") == ("gofile.io", 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        with sessions() as db:
            assert db.get(DownloadRequest, queued_id).status == StatusEnum.stopped
    finally:
        await runner.cleanup()
