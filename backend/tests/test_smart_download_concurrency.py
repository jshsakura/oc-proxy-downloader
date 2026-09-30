# -*- coding: utf-8 -*-
"""Tests for smart-download admission control.

The core guarantee: every host gets its OWN concurrency queue, so a few big
files on one host can never starve a small file on a different host. Limits are
read from config and clamped, and a global ceiling bounds total downloads.
"""

import asyncio

import pytest

from core import download_core as dc_module
from core.download_core import DownloadCore, _read_concurrency_limits, SITE_DOWNLOAD_LIMITS


def _write_config(values):
    """Overwrite the (test-isolated) config.json with the given dict."""
    import json
    from core.config import CONFIG_FILE

    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(values, f)


def test_read_concurrency_limits_uses_defaults_when_unset():
    _write_config({})
    ceiling, per_host = _read_concurrency_limits()
    assert ceiling == dc_module.DEFAULT_MAX_CONCURRENT_DOWNLOADS
    assert per_host == dc_module.DEFAULT_MAX_PER_HOST_DOWNLOADS


def test_read_concurrency_limits_clamps_out_of_range():
    _write_config({"max_concurrent_downloads": 999, "max_per_host_downloads": 0})
    ceiling, per_host = _read_concurrency_limits()
    assert ceiling == dc_module.CONCURRENCY_MAX  # 999 -> 32
    assert per_host == dc_module.CONCURRENCY_MIN  # 0 -> 1


def test_read_concurrency_limits_falls_back_on_non_numeric():
    _write_config({"max_concurrent_downloads": "lots", "max_per_host_downloads": None})
    ceiling, per_host = _read_concurrency_limits()
    assert ceiling == dc_module.DEFAULT_MAX_CONCURRENT_DOWNLOADS
    assert per_host == dc_module.DEFAULT_MAX_PER_HOST_DOWNLOADS


def test_per_host_never_exceeds_global_ceiling():
    _write_config({"max_concurrent_downloads": 2, "max_per_host_downloads": 9})
    ceiling, per_host = _read_concurrency_limits()
    assert ceiling == 2
    assert per_host == 2  # capped down to the ceiling


def test_listed_host_uses_its_tuned_limit():
    _write_config({})
    dc = DownloadCore()
    key, limit = dc._resolve_host_limit("https://gofile.io/d/abc123")
    assert key == "gofile.io"
    assert limit == SITE_DOWNLOAD_LIMITS["gofile.io"]


def test_datanodes_browser_flow_allows_only_one_download_even_with_default_cap():
    _write_config({"max_concurrent_downloads": 8, "max_per_host_downloads": 3})
    dc = DownloadCore()
    assert dc._resolve_host_limit("https://datanodes.to/file/code") == ("datanodes.to", 1)
    assert dc._resolve_host_limit("https://multiup.io/download/code/file.rar") == ("multiup.io", 1)


def test_new_host_aliases_share_three_download_slots():
    _write_config({"max_concurrent_downloads": 8, "max_per_host_downloads": 3})
    dc = DownloadCore()
    assert dc._resolve_host_limit("https://vikingfile.com/f/a") == ("vikingfile.com", 3)
    assert dc._resolve_host_limit("https://vik1ngfile.site/f/b") == ("vikingfile.com", 3)
    assert dc._resolve_host_limit("https://akirabox.com/a/file") == ("akirabox.com", 1)
    assert dc._resolve_host_limit("https://akirabox.to/b/file") == ("akirabox.com", 1)
    assert dc._resolve_host_limit("https://www.rootz.so/d/a") == ("rootz.so", 1)


@pytest.mark.parametrize("host", ["datanodes.to", "gofile.io", "megaup.net", "send.now"])
def test_operator_one_per_host_caps_listed_hosts_too(host):
    _write_config({"max_concurrent_downloads": 8, "max_per_host_downloads": 1})
    dc = DownloadCore()
    key, limit = dc._resolve_host_limit(f"https://{host}/file")
    assert key == host
    assert limit == 1


def test_unlisted_host_uses_default_per_host_cap():
    _write_config({})
    dc = DownloadCore()
    key, limit = dc._resolve_host_limit("https://some-random-host.example/file/9")
    assert key == "some-random-host.example"
    assert limit == 1


def test_different_unlisted_hosts_get_distinct_keys():
    """The whole point: host A and host B must not share a queue."""
    _write_config({})
    dc = DownloadCore()
    key_a, _ = dc._resolve_host_limit("https://big-files.example/a")
    key_b, _ = dc._resolve_host_limit("https://small-files.example/b")
    assert key_a != key_b


def test_missing_or_empty_url_falls_back_to_default_key():
    _write_config({})
    dc = DownloadCore()
    assert dc._resolve_host_limit(None) == ("_default", 1)
    assert dc._resolve_host_limit("") == ("_default", 1)


def test_refresh_concurrency_settings_reapplies_config():
    _write_config({"max_concurrent_downloads": 8, "max_per_host_downloads": 3})
    dc = DownloadCore()
    assert dc.MAX_CONCURRENT_DOWNLOADS == 8

    _write_config({"max_concurrent_downloads": 4, "max_per_host_downloads": 2})
    dc.refresh_concurrency_settings()
    assert dc.MAX_CONCURRENT_DOWNLOADS == 4
    assert dc.MAX_PER_HOST_DOWNLOADS == 2
    assert dc.total_download_semaphore._value == 4
    assert dc._site_semaphores == {}  # rebuilt lazily


@pytest.mark.asyncio
async def test_busy_host_does_not_block_a_different_host():
    """Saturate host A's queue; a host-B download must still acquire its slot."""
    _write_config({"max_concurrent_downloads": 8, "max_per_host_downloads": 2})
    dc = DownloadCore()

    key_a, limit_a = dc._resolve_host_limit("https://host-a.example/x")
    sem_a = asyncio.Semaphore(limit_a)
    dc._site_semaphores[key_a] = sem_a
    # Fill host A completely.
    for _ in range(limit_a):
        await sem_a.acquire()
    assert sem_a._value == 0

    # Host B is independent — its slot is free.
    key_b, limit_b = dc._resolve_host_limit("https://host-b.example/y")
    sem_b = dc._site_semaphores.get(key_b) or asyncio.Semaphore(limit_b)
    acquired = sem_b.locked() is False and sem_b._value > 0
    assert acquired, "host B should not be blocked by a saturated host A"
