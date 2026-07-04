# -*- coding: utf-8 -*-
"""Registry + dispatch for special file hosts (everything but 1fichier).

Routes a host page to its resolver in ``core.hoster_sites`` via a data-driven
registry, and exposes the public entry points the download core imports. Shared
primitives live in ``core.hoster_common``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import cloudscraper  # noqa: F401 -- re-exported so tests can patch hp.cloudscraper
import requests  # noqa: F401 -- re-exported so tests can patch hp.requests
from bs4 import BeautifulSoup

# Primitives used here, plus names re-exported to external importers
# (simple_parser, ouo_unwrap_service, download_core) and to tests via ``hp.<name>``.
from core.hoster_common import (
    HosterParseError,
    _cloudflare_challenge_seen,
    _extract_title_filename,  # noqa: F401 -- re-exported for tests
    _flaresolverr_request_get,  # noqa: F401 -- re-exported for tests
    _get_page_with_flaresolverr,
    _host,
    _response_text,
    _scraper,
    get_flaresolverr_context_for_url,  # noqa: F401 -- re-exported (external + tests)
    get_flaresolverr_cookies_for_url,  # noqa: F401 -- re-exported for tests
    resolve_flaresolverr_url,  # noqa: F401 -- re-exported (ouo_unwrap_service)
)
# parse_* resolvers land in this module's globals() so the registry can dispatch
# to them by name (late binding); the __all__ in hoster_sites limits the star.
from core.hoster_sites import *  # noqa: F403
from core.hoster_sites import BUNKR_HOSTS, _extract_megaup_file_info
# info_extract targets are also resolved via globals() by HOSTER_REGISTRY:
from core.hoster_sites import (  # noqa: F401
    _extract_datanodes_file_info,
    _extract_mediafire_file_info,
)


def is_special_hoster_url(url: str) -> bool:
    # SPECIAL_HOSTS is derived from HOSTER_REGISTRY near the bottom of this module;
    # resolved at call time, so the forward reference is fine.
    return _host(url) in SPECIAL_HOSTS


def should_preserve_original_url(url: str) -> bool:
    """Whether retry/debug flows should keep the original page URL."""
    return is_special_hoster_url(url)


# ---------------------------------------------------------------------------
# Registry — the single source of truth for special-host dispatch
# ---------------------------------------------------------------------------

def _megaup_info_from_page(url: str, html_text: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    return _extract_megaup_file_info(soup, url, html_text)


@dataclass(frozen=True)
class HosterSpec:
    """One resolvable file host.

    ``parse`` / ``info_extract`` are the *names* of module-level functions, not
    the objects — they are resolved via ``globals()`` at dispatch time so that
    tests (and callers) can monkeypatch the module-level parser and still have
    the registry pick up the replacement (late binding).

    ``parse(url, proxies)`` resolves the real download link. ``info_extract``,
    when set, reads just the name/size from a single page GET's HTML — used for
    the lightweight queue-time prefetch. Leave it ``None`` for hosts whose info
    cannot be read from a plain server-side GET (IP-gated APIs, per-request
    tokens, etc.); the full parser is always the source of truth.
    """

    name: str
    hostnames: tuple
    parse: str
    info_extract: Optional[str] = None


HOSTER_REGISTRY = (
    HosterSpec("MegaUp", ("megaup.net",), "parse_megaup_sync", "_megaup_info_from_page"),
    HosterSpec("DataNodes", ("datanodes.to",), "parse_datanodes_sync", "_extract_datanodes_file_info"),
    HosterSpec("Rapidgator", ("rapidgator.net",), "parse_rapidgator_constraints_sync"),
    HosterSpec("GoFile", ("gofile.io",), "parse_gofile_sync"),
    HosterSpec("Send.now", ("send.now",), "parse_blocked_hoster_sync"),
    HosterSpec("MediaFire", ("mediafire.com",), "parse_mediafire_sync", "_extract_mediafire_file_info"),
    HosterSpec("Pixeldrain", ("pixeldrain.com",), "parse_pixeldrain_sync"),
    HosterSpec("Bunkr", BUNKR_HOSTS, "parse_bunkr_sync"),
)


def _expand_www(hostnames: tuple) -> set:
    """A host and its www. alias both route to the same spec."""
    expanded = set()
    for host in hostnames:
        expanded.add(host)
        expanded.add(f"www.{host}")
    return expanded


_HOST_TO_SPEC = {
    host: spec for spec in HOSTER_REGISTRY for host in _expand_www(spec.hostnames)
}
SPECIAL_HOSTS = frozenset(_HOST_TO_SPEC)
# Hosts whose name/size can be read from a single page GET (see HosterSpec).
_INFO_ONLY_HOSTS = frozenset(
    host for host, spec in _HOST_TO_SPEC.items() if spec.info_extract is not None
)


def parse_special_hoster_sync(
    url: str, password: Optional[str] = None, proxies: Optional[Dict[str, str]] = None
) -> Dict[str, object]:
    """Resolve a special host page into the download-core parse_result shape."""
    spec = _HOST_TO_SPEC.get(_host(url))
    if spec is None:
        raise HosterParseError("지원하지 않는 호스팅 사이트")
    return globals()[spec.parse](url, proxies=proxies)


def fetch_special_hoster_file_info_sync(
    url: str, proxies: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """Fetch only the filename/size of a special-host page (no link resolution).

    A lightweight, idempotent GET used to fill in a queued item's name/size
    while it waits for a download slot. Returns ``{}`` (never raises) when the
    host is unsupported for info-only reads or anything goes wrong — the full
    parser still runs at download time and is the source of truth.
    """
    spec = _HOST_TO_SPEC.get(_host(url))
    if spec is None or spec.info_extract is None:
        return {}
    try:
        scraper = _scraper(proxies)
        response = scraper.get(url, timeout=30)
        text = _response_text(response)
        if _cloudflare_challenge_seen(response, text):
            fs_page = _get_page_with_flaresolverr(url, proxies=proxies)
            if fs_page:
                text, _, url = fs_page
        return globals()[spec.info_extract](url, text)
    except Exception as exc:
        print(f"[WARNING] 특수 호스터 정보 사전조회 실패({_host(url)}): {exc}")
        return {}
