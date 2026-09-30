"""Exercise admission with overlapping downloads, reloads, and live parsers."""

import asyncio
import datetime
import json
import threading
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core import download_core as module
from core.download_core import DownloadCore
from core.error_messages import KIND_RATE_LIMITED, classify_error
from core.host_policy import host_key_for_url, http_failure_message
from core.models import StatusEnum
from core.slots import DownloadSlots


@pytest.fixture
def core(monkeypatch):
    monkeypatch.setattr(module, "_read_concurrency_limits", lambda: (8, 3))
    instance = DownloadCore()
    instance.send_download_update = AsyncMock()
    return instance


@pytest.mark.parametrize("url, key, limit", [
    ("https://1fichier.com/?a", "1fichier.com", 1),
    ("https://node.1fichier.com/a", "1fichier.com", 1),
    ("https://datanodes.to/a", "datanodes.to", 1),
    ("https://multiup.io/a", "multiup.io", 1),
    ("https://send.now/a", "send.now", 1),
    ("https://send.cm/a", "send.now", 1),
    ("https://tusfiles.com/a", "send.now", 1),
    ("https://drive.usercontent.google.com/download?id=a", "drive.google.com", 1),
    ("https://megaup.net/a", "megaup.net", 1),
    ("https://akirabox.to/a", "akirabox.com", 1),
    ("https://node.vik1ngfile.site/a", "vikingfile.com", 3),
    ("https://mxdrop.top/a", "mixdrop.ag", 1),
    ("https://mixdrop.top/a", "mixdrop.ag", 1),
    ("https://bunkrr.ru/f/a", "bunkr.si", 1),
    ("https://cdn.bunkr.fi/file.rar", "bunkr.si", 1),
    ("https://datanodes.to.evil.example/a", "datanodes.to.evil.example", 1),
    ("https://notgofile.io/a", "notgofile.io", 1),
])
def test_host_identity_and_transfer_limits(core, url, key, limit):
    assert core._resolve_host_limit(url) == (key, limit)


@pytest.mark.asyncio
@pytest.mark.parametrize("url, proxy_modes, expected_parallel", [
    ("https://1fichier.com/?file", (False, False), False),
    ("https://1fichier.com/?file", (True, True), False),
    ("https://datanodes.to/file", (False, True), False),
    ("https://gofile.io/d/file", (False, False), True),
    ("https://vikingfile.com/file", (False, False), True),
])
async def test_download_slot_covers_metadata_and_transfer(
    core, monkeypatch, url, proxy_modes, expected_parallel,
):
    requests = {
        i: SimpleNamespace(id=i, url=url, original_url=None, use_proxy=proxy,
                           status=StatusEnum.pending, file_name=None, file_size=None,
                           failure_kind=None, next_retry_at=None)
        for i, proxy in enumerate(proxy_modes, 1)
    }
    db = MagicMock()
    db.query.return_value.filter.side_effect = lambda condition: condition.right.value
    monkeypatch.setattr(module, "SessionLocal", lambda: db)
    monkeypatch.setattr(module.db_async, "first", AsyncMock(side_effect=lambda key: requests[key]))
    monkeypatch.setattr(module.db_async, "refresh", AsyncMock())
    monkeypatch.setattr(module.db_async, "commit", AsyncMock())
    metadata = []
    entered = asyncio.Event()
    release = asyncio.Event()
    second_entered = asyncio.Event()

    async def preparse(req, db):
        metadata.append(req.id)
        req.file_name, req.file_size = "file.rar", "1 MB"

    async def transfer(req, db, **kwargs):
        if module.is_special_hoster_url(req.url):
            # Metadata arrives with this single resolver's result, not from
            # a separate info-only GET before resolving the same page.
            await preparse(req, db)
        if req.id == 1:
            entered.set()
            await release.wait()
        else:
            second_entered.set()
        req.status = StatusEnum.done

    monkeypatch.setattr(core, "_perform_preparse", preparse)
    monkeypatch.setattr(core, "_perform_special_preparse", preparse)
    monkeypatch.setattr(core, "_download_with_proxy_async", transfer)
    monkeypatch.setattr(core, "_download_local_async", transfer)
    first = asyncio.create_task(core._download_task(1))
    await asyncio.wait_for(entered.wait(), 1)
    second = asyncio.create_task(core._download_task(2))
    try:
        if expected_parallel:
            await asyncio.wait_for(second_entered.wait(), 1)
            assert metadata == [1, 2]
        else:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(second_entered.wait(), 0.05)
            assert metadata == [1], "queued metadata must not contact a single-session host"
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 1)
        assert second_entered.is_set()
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)


@pytest.mark.asyncio
async def test_settings_reload_keeps_existing_holders_and_waiters(core, monkeypatch):
    host_slots = DownloadSlots(3)
    core._site_semaphores["gofile.io@direct"] = host_slots
    global_slots = core.total_download_semaphore
    await host_slots.acquire()
    await host_slots.acquire()
    monkeypatch.setattr(module, "_read_concurrency_limits", lambda: (4, 1))
    core.refresh_concurrency_settings()
    assert core.total_download_semaphore is global_slots
    assert core._site_semaphores["gofile.io@direct"] is host_slots
    waiter = asyncio.create_task(host_slots.acquire())
    await asyncio.sleep(0)
    host_slots.release()
    await asyncio.sleep(0)
    assert not waiter.done()
    host_slots.release()
    await asyncio.wait_for(waiter, 1)
    host_slots.release()


@pytest.mark.asyncio
async def test_cancelled_waiter_does_not_leak_slots():
    slots = DownloadSlots(1)
    await slots.acquire()
    waiter = asyncio.create_task(slots.acquire())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    slots.release()
    assert slots._value == 1
    slots.set_limit(2)
    await slots.acquire()
    await slots.acquire()
    assert slots.locked()
    slots.release()
    slots.release()


@pytest.mark.asyncio
async def test_settings_thread_can_wake_existing_waiters():
    slots = DownloadSlots(1)
    await slots.acquire()
    waiter = asyncio.create_task(slots.acquire())
    await asyncio.sleep(0)
    await asyncio.to_thread(slots.set_limit, 2)
    await asyncio.wait_for(waiter, 1)
    assert slots._value == 0
    slots.release()
    slots.release()


@pytest.mark.asyncio
async def test_timeout_keeps_alias_parser_locked_until_thread_finishes(core, monkeypatch):
    monkeypatch.setattr(module, "SPECIAL_HOSTER_PARSE_TIMEOUT_SEC", 0.02)
    release = threading.Event()
    second_started = threading.Event()

    def slow_parse():
        assert release.wait(2)

    with pytest.raises(asyncio.TimeoutError):
        await core._run_special_parser("https://akirabox.com/a", slow_parse)
    second = asyncio.create_task(core._run_special_parser(
        "https://akirabox.to/b", lambda: second_started.set()
    ))
    try:
        await asyncio.sleep(0.05)  # longer than the network timeout, still waiting
        assert not second_started.is_set()
        assert not second.done()
        release.set()
        await asyncio.wait_for(second, 1)
        assert second_started.is_set()
    finally:
        release.set()
        await asyncio.gather(second, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelling_fichier_parse_keeps_next_parse_queued(core):
    started = threading.Event()
    release = threading.Event()
    second_started = threading.Event()

    def first_parse():
        started.set()
        assert release.wait(2)

    first = asyncio.create_task(core._run_parser("https://1fichier.com/?a", first_parse))
    assert await asyncio.to_thread(started.wait, 1)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(core._run_parser(
        "https://1fichier.com/?b", lambda: second_started.set()
    ))
    try:
        await asyncio.sleep(0.05)
        assert not second_started.is_set()
        release.set()
        await asyncio.wait_for(second, 1)
        assert second_started.is_set()
    finally:
        release.set()
        await asyncio.gather(second, return_exceptions=True)


def test_explicit_single_download_refusal_lowers_all_alias_queues(core):
    slots = DownloadSlots(3)
    core._site_semaphores["akirabox.com@direct"] = slots
    until = datetime.datetime.now() + datetime.timedelta(hours=2)
    raw = "You can download only one file at a time"
    req = SimpleNamespace(failure_kind=classify_error("다운로드", raw).kind,
                          next_retry_at=until, attempts_json=json.dumps([{"raw": raw}]))
    core._register_host_refusal(req, "akirabox.com", "akirabox.com@direct")
    assert core._resolve_host_limit("https://akirabox.to/b") == ("akirabox.com", 1)
    assert slots.limit == 1
    assert core._host_cooldown_until["akirabox.com@direct"] == until
    assert core._resolve_host_limit("https://gofile.io/d/b") == ("gofile.io", 3)


def test_generic_rate_limit_preserves_parallel_transfer_policy(core):
    req = SimpleNamespace(failure_kind=KIND_RATE_LIMITED, next_retry_at=None,
                          attempts_json=json.dumps([{"raw": "HTTP 429: Too Many Requests"}]))
    core._register_host_refusal(req, "vikingfile.com", "vikingfile.com@direct")
    assert core._resolve_host_limit("https://vikingfile.com/a") == ("vikingfile.com", 3)
    assert "vikingfile.com@direct" in core._host_cooldown_until


def test_retry_after_is_kept_in_classification():
    raw = http_failure_message(429, "Too Many Requests", {"Retry-After": "3600"})
    assert classify_error("다운로드", raw).retry_after_seconds == 3600
    assert "1fichier" not in classify_error("다운로드", raw).summary


def test_http_date_retry_after_is_supported():
    target = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    raw = http_failure_message(429, "Too Many Requests", {"Retry-After": format_datetime(target)})
    assert 3598 <= classify_error("다운로드", raw).retry_after_seconds <= 3601


@pytest.mark.asyncio
async def test_metadata_rate_limit_pauses_host_before_full_parse(core, monkeypatch):
    from core.hoster_common import HosterParseError
    req = SimpleNamespace(id=991, url="https://datanodes.to/file", original_url=None,
                          file_name=None, file_size=None, status=StatusEnum.pending,
                          failure_kind=None, next_retry_at=None, attempt_count=0,
                          attempts_json=None, error=None)
    monkeypatch.setattr(module.db_async, "refresh", AsyncMock())
    monkeypatch.setattr(module.db_async, "commit", AsyncMock())
    monkeypatch.setattr(module, "fetch_special_hoster_file_info_sync", MagicMock(
        side_effect=HosterParseError("HTTP 429: Too Many Requests; you must wait 1800 seconds")
    ))
    with pytest.raises(HosterParseError):
        await core._perform_special_preparse(req, MagicMock())
    assert req.failure_kind == KIND_RATE_LIMITED
    assert core._host_cooldown_until["datanodes.to@direct"] >= (
        datetime.datetime.now() + datetime.timedelta(seconds=1800)
    )


def test_browser_aliases_share_one_resolution_lock():
    from core.browser_solver import _host_lock
    assert _host_lock("mixdrop.ag") is _host_lock("www.mxdrop.top")
    assert host_key_for_url("https://WWW.AKIRABOX.TO./a") == "akirabox.com"
