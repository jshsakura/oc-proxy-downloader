"""ouo.io URL unwrap service.

Lazy-instantiated singleton wrapping ``core.ouo_resolver.OuoResolver`` for the
download pipeline. Auto-detects whether FlareSolverr is reachable; when it
isn't (Windows standalone build, no docker compose stack, etc.), the resolver
is configured with the curl_impersonate backend only — which is fully
self-contained (curl_cffi + Google reCAPTCHA anchor API, no extra services).

Usage:
    from services.ouo_unwrap_service import unwrap_if_ouo

    real_url = unwrap_if_ouo(url) or url   # falls back to original on failure
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

import requests

from core.ouo_resolver import OuoResolver, OuoResolverConfig


logger = logging.getLogger(__name__)

_DEFAULT_FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191")
_HEALTH_CHECK_TIMEOUT_S = 3

# Allowed final destinations after unwrap. Mirrors core/common.is_valid_link
# plus the additional hosts ouo links empirically resolve to.
_ALLOWED_HOSTS = (
    "1fichier.com",
    "afterupload.com",
    "cjoint.net",
    "desfichiers.com",
    "megadl.fr",
    "mesfichiers.org",
    "piecejointe.net",
    "pjointe.com",
    "tenvoi.com",
    "dl4free.com",
    "mega.nz",
    "mediafire",
    "pixeldrain",
    "katfile",
    "datanodes",
    "send.now",
    "rapidgator",
    "gofile",
    "megaup",
)

_resolver_lock = threading.Lock()
_resolver: Optional[OuoResolver] = None


def _flaresolverr_reachable(url: str) -> bool:
    try:
        resp = requests.get(f"{url.rstrip('/')}/", timeout=_HEALTH_CHECK_TIMEOUT_S)
        return resp.status_code < 500
    except Exception:
        return False


def _build_resolver() -> OuoResolver:
    has_flaresolverr = _flaresolverr_reachable(_DEFAULT_FLARESOLVERR_URL)
    if has_flaresolverr:
        backend_order = (
            "curl_impersonate",
            "flaresolverr_form",
            "undetected_chromedriver",
            "ouo_bypass_legacy",
        )
        logger.info(f"OuoResolver: FlareSolverr reachable at {_DEFAULT_FLARESOLVERR_URL}, using full backend chain")
    else:
        # Standalone (e.g. Windows binary without docker stack) — curl_impersonate
        # is the only backend that doesn't need FlareSolverr.
        backend_order = ("curl_impersonate",)
        logger.info("OuoResolver: FlareSolverr unreachable, standalone mode (curl_impersonate only)")

    config = OuoResolverConfig(
        flaresolverr_url=_DEFAULT_FLARESOLVERR_URL,
        allowed_download_hosts=_ALLOWED_HOSTS,
        accept_intermediate_hosts=False,
        preserve_unresolved_ouo_links=False,
        cache_enabled=False,  # downloads are user-initiated and rare; no DB cache yet
        backend_order=backend_order,
        # Skip the FlareSolverr session bootstrap in standalone mode — it just
        # logs a connection-refused warning every call.
        auto_session=has_flaresolverr,
    )
    return OuoResolver(config)


def get_resolver() -> OuoResolver:
    global _resolver
    if _resolver is not None:
        return _resolver
    with _resolver_lock:
        if _resolver is None:
            _resolver = _build_resolver()
    return _resolver


def is_ouo_url(url: str) -> bool:
    return OuoResolver.is_ouo_url(url)


def unwrap_if_ouo(url: str) -> Optional[str]:
    """If ``url`` is an ouo.io / ouo.press shortlink, resolve it. Returns the
    real download URL on success, None on failure or if the URL isn't ouo.
    Callers should fall back to the original URL on None.
    """
    if not is_ouo_url(url):
        return None
    try:
        return get_resolver().resolve(url, phase="user_request", link_tier="base")
    except Exception as exc:
        logger.warning(f"ouo unwrap failed for {url}: {exc}")
        return None
