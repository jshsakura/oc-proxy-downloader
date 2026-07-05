# -*- coding: utf-8 -*-
"""Shared primitives for the site-specific hoster parsers.

This is the leaf layer: scraping/session helpers, FlareSolverr access, size and
title/filename extraction, and generic HTML link extraction. It has no knowledge
of any specific host. ``hoster_parsers`` (the registry + per-host parsers) imports
from here; nothing here imports back, so there is no import cycle.
"""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import unquote, urljoin, urlparse

import cloudscraper
import requests
from bs4 import BeautifulSoup

from core.config import get_config


__all__ = [
    'DEFAULT_FLARESOLVERR_URL',
    'DEFAULT_HOSTER_USER_AGENT',
    'FLARESOLVERR_MAX_TIMEOUT_MS',
    'FLARESOLVERR_REQUEST_TIMEOUT_S',
    'HosterParseError',
    'HosterParseResult',
    '_KNOWN_FILE_EXTENSIONS',
    '_SIZE_RE',
    '_TITLE_PREFIX_RE',
    '_TITLE_SITE_SUFFIX_RE',
    '_cloudflare_challenge_seen',
    '_cookies_dict',
    '_extract_download_link_from_html',
    '_extract_hidden_inputs',
    '_extract_largest_size_from_text',
    '_extract_size_from_text',
    '_extract_submit_values',
    '_extract_title_filename',
    '_flaresolverr_request_get',
    '_format_size_bytes',
    '_get_page_with_flaresolverr',
    '_has_known_extension',
    '_host',
    '_json_or_raise',
    '_raise_for_dead_page',
    '_requires_turnstile',
    '_response_text',
    '_scraper',
    '_solution_cookies',
    'get_flaresolverr_context_for_url',
    'get_flaresolverr_cookies_for_url',
    'resolve_flaresolverr_url',
    'size_to_bytes',
]


DEFAULT_HOSTER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
DEFAULT_FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191")


def resolve_flaresolverr_url() -> str:
    """FlareSolverr endpoint, in priority order: settings → env var → default.

    Resolved at call time so the in-app Settings value takes effect without a
    restart (and so the Windows app can point at a separately-run FlareSolverr).
    """
    configured = (get_config().get("flaresolverr_url") or "").strip()
    return configured or DEFAULT_FLARESOLVERR_URL


FLARESOLVERR_MAX_TIMEOUT_MS = int(os.environ.get("FLARESOLVERR_MAX_TIMEOUT_MS", "60000"))
FLARESOLVERR_REQUEST_TIMEOUT_S = int(os.environ.get("FLARESOLVERR_REQUEST_TIMEOUT_S", "80"))


class HosterParseError(Exception):
    """A host page could not be resolved into a downloadable file URL."""


@dataclass
class HosterParseResult:
    download_link: str
    file_info: Optional[Dict[str, str]] = None
    wait_time: Optional[int] = None
    cookies: Optional[Dict[str, str]] = None
    user_agent: Optional[str] = None
    referer: Optional[str] = None

    def as_parse_result(self) -> Dict[str, object]:
        return {
            "download_link": self.download_link,
            "file_info": self.file_info,
            "wait_time": self.wait_time,
            "cookies": self.cookies or {},
            "user_agent": self.user_agent,
            "referer": self.referer,
        }


_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)", re.IGNORECASE)


def _host(url: str) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def size_to_bytes(size_text: Optional[str]) -> int:
    if not size_text:
        return 0
    match = _SIZE_RE.search(size_text)
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).upper()
    multipliers = {
        "KB": 1024,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3,
        "TB": 1024 ** 4,
    }
    return int(value * multipliers.get(unit, 1))


def _format_size_bytes(num_bytes: int) -> str:
    units = (("TB", 1024 ** 4), ("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024))
    for label, factor in units:
        if num_bytes >= factor:
            return f"{num_bytes / factor:.2f} {label}"
    return f"{num_bytes} B"


def _scraper(proxies: Optional[Dict[str, str]] = None):
    scraper = cloudscraper.create_scraper()
    scraper.headers.update({
        "User-Agent": DEFAULT_HOSTER_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    if proxies:
        scraper.proxies.update(proxies)
    return scraper


def _cookies_dict(scraper) -> Dict[str, str]:
    try:
        return scraper.cookies.get_dict()
    except Exception:
        return {}


def _cloudflare_challenge_seen(response=None, text: str = "") -> bool:
    body = (text or getattr(response, "text", "") or "").lower()
    headers = getattr(response, "headers", {}) or {}
    if str(headers.get("cf-mitigated", "")).lower() == "challenge":
        return True
    status = getattr(response, "status_code", None)
    return bool(
        status in (403, 503)
        and (
            "just a moment" in body
            or "checking your browser" in body
            or "challenge-platform" in body
            or "cf_chl" in body
            or "cloudflare" in body
        )
    )


def _flaresolverr_request_get(
    url: str,
    *,
    session_id: str = "",
    referer: str = "",
    max_timeout_ms: int = FLARESOLVERR_MAX_TIMEOUT_MS,
    proxies: Optional[Dict[str, str]] = None,
) -> Optional[dict]:
    payload = {
        "cmd": "request.get",
        "url": url,
        "maxTimeout": max_timeout_ms,
    }
    if proxies:
        proxy_url = proxies.get("https") or proxies.get("http")
        if proxy_url:
            payload["proxy"] = {"url": proxy_url}
    if session_id:
        payload["session"] = session_id
    if referer:
        payload["headers"] = {
            "Referer": referer,
            "User-Agent": DEFAULT_HOSTER_USER_AGENT,
        }
    try:
        response = requests.post(
            f"{resolve_flaresolverr_url().rstrip('/')}/v1",
            json=payload,
            timeout=FLARESOLVERR_REQUEST_TIMEOUT_S,
        )
        response.raise_for_status()
        result = response.json()
    except Exception as exc:
        print(f"[WARNING] FlareSolverr request.get 실패: {exc}")
        return None
    if result.get("status") != "ok":
        print(f"[WARNING] FlareSolverr request.get status={result.get('status')}")
        return None
    return result.get("solution") or {}


def _solution_cookies(solution: Optional[dict]) -> Dict[str, str]:
    cookies = {}
    for item in (solution or {}).get("cookies") or []:
        name = item.get("name")
        value = item.get("value")
        if name and value is not None:
            cookies[name] = value
    return cookies


def get_flaresolverr_context_for_url(
    url: str, referer: str = "", proxies: Optional[Dict[str, str]] = None
) -> Dict[str, object]:
    """Use FlareSolverr to obtain Cloudflare cookies and browser context.

    Important: this visits only the origin root, not the large file URL itself,
    so FlareSolverr does not buffer a multi-GB file in memory.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return {"cookies": {}, "user_agent": None}
    origin = f"{parsed.scheme}://{parsed.netloc}/"
    solution = _flaresolverr_request_get(origin, referer=referer, proxies=proxies)
    if not solution:
        return {"cookies": {}, "user_agent": None}
    return {
        "cookies": _solution_cookies(solution),
        "user_agent": solution.get("userAgent") or None,
    }


def get_flaresolverr_cookies_for_url(url: str, referer: str = "") -> Dict[str, str]:
    """Backward-compatible cookie-only wrapper."""
    context = get_flaresolverr_context_for_url(url, referer=referer)
    return context.get("cookies") or {}


def _response_text(response) -> str:
    return getattr(response, "text", "") or ""


def _json_or_raise(response, host_label: str) -> dict:
    """Parse a JSON API response, converting a non-JSON body into a classifiable
    ``HosterParseError`` instead of a raw ``JSONDecodeError``.

    A hoster behind Cloudflare (or hitting a 5xx) returns an HTML challenge/error
    page; calling ``.json()`` on it raises ``ValueError`` that escapes as an
    opaque "Expecting value" failure and, in proxy mode, wrongly marks a healthy
    proxy as failed. Routing it through a HosterParseError keeps it classifiable.
    """
    try:
        return response.json() or {}
    except ValueError:
        raise HosterParseError(
            f"{host_label} API가 JSON이 아닌 응답 반환 (Cloudflare 차단/오류 페이지 가능성)"
        )


def _get_page_with_flaresolverr(
    url: str, referer: str = "", proxies: Optional[Dict[str, str]] = None
) -> Optional[tuple[str, Dict[str, str], str]]:
    solution = _flaresolverr_request_get(url, referer=referer, proxies=proxies)
    if not solution:
        return None
    return (
        solution.get("response") or "",
        _solution_cookies(solution),
        solution.get("url") or url,
    )


def _requires_turnstile(html_text: str) -> bool:
    lowered = (html_text or "").lower()
    return (
        "cf-turnstile-response" in lowered
        or "turnstile" in lowered
        or "download challenge" in lowered
    )


def _raise_for_dead_page(host_label: str, text: str, status_code: int) -> None:
    lowered = (text or "").lower()
    # Specific phrases only. A bare "not found" is too broad — it appears in i18n
    # strings and inline JS bundles (MediaFire/Bunkr ship them), which would flag a
    # live page as deleted and hand it to the retry sweeper as a dead file.
    dead_markers = (
        "file not found",
        "could not be found",
        "file was deleted",
        "file has been deleted",
        "file expired",
        "deleted by",
        "no longer available",
    )
    if status_code == 404 or any(marker in lowered for marker in dead_markers):
        raise HosterParseError(f"{host_label} 파일 없음 또는 삭제됨")


# Real download filenames end in one of these. A bare "." (e.g. the version tag
# "[1.0.1]" inside an SEO page title) must NOT qualify, otherwise a truncated
# page <title> like "Game [1.0.1][UPD]… by NxBrew" gets saved as the filename.
_KNOWN_FILE_EXTENSIONS = (
    ".nsp", ".xci", ".nsz", ".xcz", ".zip", ".rar", ".7z", ".tar", ".gz",
    ".iso", ".wbfs", ".rvz", ".bin", ".exe", ".apk", ".mkv", ".mp4", ".avi",
    ".pdf", ".cia", ".3ds", ".wad", ".rom",
)
# Strip a leading "Download:" label and a trailing site tag (" - MegaUp",
# "| Rapidgator", "… by NxBrew", "- NxBrew", etc.) including any leading
# separator/ellipsis run, so what remains is just the filename.
_TITLE_PREFIX_RE = re.compile(r"^\s*Download(?:ing)?(?: file)?\s*:?\s*", re.I)
_TITLE_SITE_SUFFIX_RE = re.compile(
    r"\s*[-|–·•…\s]*(?:by\s+)?(?:MegaUp|Rapidgator|NxBrew)\b.*$", re.I
)


def _has_known_extension(text: str) -> bool:
    """True when the cleaned title ends in a real download extension."""
    lowered = text.lower()
    return any(lowered.endswith(ext) for ext in _KNOWN_FILE_EXTENSIONS)


def _extract_title_filename(soup: BeautifulSoup, fallback_url: str) -> str:
    for selector in ("h1", "h2", "title"):
        node = soup.select_one(selector)
        if not node:
            continue
        text = node.get_text(" ", strip=True)
        text = _TITLE_PREFIX_RE.sub("", text)
        text = _TITLE_SITE_SUFFIX_RE.sub("", text)
        text = text.rstrip(" .…").strip()
        # Only accept a page title as the filename when it actually ends in a
        # real extension; otherwise it's an SEO/heading string, not the file.
        if text and _has_known_extension(text):
            return text

    parsed = urlparse(fallback_url)
    filename = unquote((parsed.path or "").rstrip("/").rsplit("/", 1)[-1])
    return filename if filename else ""


def _extract_size_from_text(text: str) -> str:
    match = _SIZE_RE.search(text or "")
    return match.group(0) if match else ""


def _extract_largest_size_from_text(text: str) -> str:
    best_text = ""
    best_bytes = 0
    for match in _SIZE_RE.finditer(text or ""):
        size_text = match.group(0)
        size_bytes = size_to_bytes(size_text)
        if size_bytes > best_bytes:
            best_text = size_text
            best_bytes = size_bytes
    return best_text


def _extract_hidden_inputs(html_text: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    values: Dict[str, str] = {}
    for node in soup.find_all("input"):
        name = (node.get("name") or "").strip()
        if not name:
            continue
        values[name] = node.get("value") or ""
    return values


def _extract_submit_values(html_text: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    values: Dict[str, str] = {}
    for node in soup.find_all(["button", "input"]):
        name = (node.get("name") or "").strip()
        if not name:
            continue
        values[name] = node.get("value") or node.get_text(" ", strip=True)
    return values


def _extract_download_link_from_html(html_text: str, base_url: str) -> str:
    soup = BeautifulSoup(html_text or "", "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = html.unescape(anchor.get("href", "").strip())
        if not href or href == "#":
            continue
        lowered = href.lower()
        text = anchor.get_text(" ", strip=True).lower()
        if "download" in lowered or "datanodes" in lowered or "download" in text:
            return urljoin(base_url, href)

    match = re.search(
        r"""https?://[^'"\s<>]+(?:download|datanodes)[^'"\s<>]*""",
        html_text or "",
        re.IGNORECASE,
    )
    return html.unescape(match.group(0)) if match else ""
