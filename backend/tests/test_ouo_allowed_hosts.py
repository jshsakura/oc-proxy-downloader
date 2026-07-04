# -*- coding: utf-8 -*-
"""Tests that the ouo resolver accepts every hoster the app can download.

Regression: ``is_valid_final_url`` only allowed ``1fichier.com`` by default, so
an ouo link that unwrapped to a mega / gofile / mediafire / pixeldrain / datanodes
URL was rejected as "no valid URL" and put on an exponential failure cooldown —
even though the downloader supports those hosts.
"""

import pytest

from core.ouo_resolver import (
    OuoResolver,
    OuoResolverConfig,
    SUPPORTED_DOWNLOAD_HOSTS,
)


@pytest.fixture
def resolver():
    return OuoResolver(OuoResolverConfig())


@pytest.mark.parametrize(
    "url",
    [
        "https://1fichier.com/?abc123",
        "https://mega.nz/file/AbCdEf#key",
        "https://www.mediafire.com/file/xyz/name",
        "https://pixeldrain.com/u/abcd",
        "https://gofile.io/d/AbCd",
        "https://datanodes.to/download/xyz",
    ],
)
def test_supported_final_urls_are_valid(resolver, url):
    assert resolver.is_valid_final_url(url) is True


def test_ouo_landing_still_rejected(resolver):
    assert resolver.is_valid_final_url("https://ouo.io/go/abcd") is False
    assert resolver.is_valid_final_url("https://ouo.press/xreallcygo/abcd") is False


def test_unsupported_host_rejected(resolver):
    assert resolver.is_valid_final_url("https://example.com/file/1") is False


def test_from_config_defaults_to_supported_hosts():
    cfg = OuoResolverConfig.from_crawling_dict(
        crawling_config={}, flaresolverr_url="http://localhost:8191"
    )
    # Every supported host is present in the config-loaded allow-list.
    for host in SUPPORTED_DOWNLOAD_HOSTS:
        assert any(host in allowed for allowed in cfg.allowed_download_hosts)
