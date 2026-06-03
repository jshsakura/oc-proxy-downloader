# -*- coding: utf-8 -*-
"""Site-specific parsers for file-hosting pages other than 1fichier.

The download core can fetch plain direct links by itself.  Hosts in this module
serve an HTML/API page first and require a short resolution step to obtain the
real download URL, or they have constraints that should be reported explicitly
instead of saving the HTML page as if it were the file.
"""

from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import unquote, urljoin, urlparse

import cloudscraper
import requests
from bs4 import BeautifulSoup

from core.config import get_config


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

GOFILE_API_BASE = "https://api.gofile.io"
_GOFILE_ID_RE = re.compile(r"/(?:d/)?([A-Za-z0-9]+)/?$")
# The listing API requires the site's "website token" (wt). The web client reads
# it from /dist/js/config.js; we fetch it live and fall back to the last-known
# value if the format changes. Without wt the API returns error-notPremium even
# from a residential IP — which previously looked like a datacenter-IP block.
GOFILE_CONFIG_JS_URL = "https://gofile.io/dist/js/config.js"
GOFILE_FALLBACK_WT = "4fd6sg89d7s6"
_GOFILE_WT_RE = re.compile(r"""wt\s*[:=]\s*["']([A-Za-z0-9_\-]{6,})["']""")
# Query params the GoFile web client sends for a folder listing (captured live).
# Note: even with wt, the listing API is also gated by datacenter IP — it returns
# error-notPremium from cloud/VPS IPs but works from residential IPs (home NAS).
_GOFILE_CONTENTS_PARAMS = {
    "contentFilter": "",
    "page": "1",
    "pageSize": "1000",
    "sortField": "name",
    "sortDirection": "1",
}


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


SPECIAL_HOSTS = {
    "megaup.net",
    "www.megaup.net",
    "datanodes.to",
    "www.datanodes.to",
    "rapidgator.net",
    "www.rapidgator.net",
    "gofile.io",
    "www.gofile.io",
    "send.now",
    "www.send.now",
}


_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)", re.IGNORECASE)


def _host(url: str) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def is_special_hoster_url(url: str) -> bool:
    return _host(url) in SPECIAL_HOSTS


def should_preserve_original_url(url: str) -> bool:
    """Whether retry/debug flows should keep the original page URL."""
    return is_special_hoster_url(url)


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
    dead_markers = (
        "file not found",
        "could not be found",
        "file was deleted",
        "file expired",
        "not found",
        "deleted by",
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


def _extract_megaup_file_info(soup: BeautifulSoup, url: str, html_text: str) -> Dict[str, str]:
    filename = _extract_title_filename(soup, url)
    size = ""

    strong_texts = [node.get_text(" ", strip=True) for node in soup.find_all("strong")]
    for text in strong_texts:
        if filename and filename in text:
            size = _extract_size_from_text(text)
            break
    if not size:
        size = _extract_size_from_text(html_text)

    info: Dict[str, str] = {}
    if filename:
        info["name"] = filename
    if size:
        info["size"] = size
    return info


def _extract_megaup_download_link(soup: BeautifulSoup, html_text: str) -> str:
    for anchor in soup.select("div.download-timer a[href], a.btn[href]"):
        href = html.unescape((anchor.get("href") or "").strip())
        if href.startswith("https://download.megaup.net/"):
            return href

    match = re.search(
        r"""href=['"](?P<link>https://download\.megaup\.net/\?url=[^'"]+)['"]""",
        html_text or "",
        re.IGNORECASE,
    )
    if match:
        return html.unescape(match.group("link"))
    return ""


def _extract_megaup_token_link(html_text: str, base_url: str) -> str:
    soup = BeautifulSoup(html_text or "", "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = html.unescape((anchor.get("href") or "").strip())
        if "download_token=" in href:
            return urljoin(base_url, href)
    match = re.search(
        r"""https?://[^'"\s<>]+/download/[^'"\s<>?]+[?][^'"\s<>]*download_token=[^'"\s<>]+""",
        html_text or "",
        re.IGNORECASE,
    )
    return html.unescape(match.group(0)) if match else ""


def _resolve_megaup_final_link(
    download_link: str,
    *,
    referer: str,
    cookies: Dict[str, str],
    user_agent: str,
    proxies: Optional[Dict[str, str]] = None,
) -> tuple[str, Dict[str, str], str, str]:
    """Follow MegaUp's intermediate download page to the tokenized file URL."""
    fs_context = get_flaresolverr_context_for_url(download_link, referer=referer, proxies=proxies)
    merged_cookies = {**cookies, **(fs_context.get("cookies") or {})}
    browser_ua = fs_context.get("user_agent") or user_agent
    headers = {
        "User-Agent": browser_ua,
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "identity",
    }
    try:
        response = requests.get(
            download_link,
            headers=headers,
            cookies=merged_cookies,
            timeout=30,
            allow_redirects=True,
            stream=True,
            proxies=proxies,
        )
    except Exception as exc:
        print(f"[WARNING] MegaUp 최종 링크 확인 실패: {exc}")
        return download_link, merged_cookies, browser_ua, referer

    try:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "text/html" not in content_type:
            return download_link, merged_cookies, browser_ua, referer
        text = response.text
    finally:
        response.close()

    final_link = _extract_megaup_token_link(text, response.url or download_link)
    if not final_link:
        return download_link, merged_cookies, browser_ua, referer
    return final_link, merged_cookies, browser_ua, response.url or download_link


def parse_megaup_sync(url: str, proxies: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    scraper = _scraper(proxies)
    response = scraper.get(url, timeout=30)
    text = _response_text(response)
    fs_cookies: Dict[str, str] = {}
    if _cloudflare_challenge_seen(response, text):
        fs_page = _get_page_with_flaresolverr(url, proxies=proxies)
        if fs_page:
            text, fs_cookies, url = fs_page
    _raise_for_dead_page("MegaUp", text, getattr(response, "status_code", 0))

    soup = BeautifulSoup(text, "html.parser")
    file_info = _extract_megaup_file_info(soup, url, text)
    download_link = _extract_megaup_download_link(soup, text)
    if not download_link:
        raise HosterParseError("MegaUp 다운로드 링크를 찾을 수 없음")
    cookies = {**_cookies_dict(scraper), **fs_cookies}
    user_agent = DEFAULT_HOSTER_USER_AGENT
    referer = url
    download_link, cookies, user_agent, referer = _resolve_megaup_final_link(
        download_link,
        referer=referer,
        cookies=cookies,
        user_agent=user_agent,
        proxies=proxies,
    )

    return HosterParseResult(
        download_link=download_link,
        file_info=file_info or None,
        wait_time=2,
        cookies=cookies,
        user_agent=user_agent,
        referer=referer,
    ).as_parse_result()


def _parse_datanodes_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    parts = [p for p in (parsed.path or "").split("/") if p]
    if not parts:
        raise HosterParseError("DataNodes 파일 코드를 찾을 수 없음")
    file_code = unquote(parts[0])
    filename = unquote(parts[-1]) if len(parts) > 1 else ""
    return file_code, filename


def _extract_datanodes_file_info(url: str, html_text: str) -> Dict[str, str]:
    _, filename = _parse_datanodes_url(url)
    soup = BeautifulSoup(html_text or "", "html.parser")
    if not filename:
        filename = _extract_title_filename(soup, url)
    size = _extract_largest_size_from_text(html_text or "")
    info: Dict[str, str] = {}
    if filename:
        info["name"] = filename
    if size:
        info["size"] = size
    return info


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


def _is_datanodes_download_link(candidate: str) -> bool:
    if not candidate:
        return False
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").rstrip("/")
    if host in {"datanodes.to", "www.datanodes.to"} and path in {"", "/download"}:
        return False
    if path.lower().endswith((".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg")):
        return False
    return bool(parsed.scheme in {"http", "https"} and host)


def _extract_datanodes_countdown_payload(html_text: str, file_code: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    node = soup.find("download-countdown")
    payload = {
        "op": "download2",
        "id": file_code,
        "rand": "",
        "referer": "https://datanodes.to/download",
        "method_free": "Free Download >>",
        "method_premium": "",
        "g_captch__a": "1",
    }
    if node:
        payload.update({
            "id": node.get("code") or file_code,
            "rand": node.get("rand") or "",
            "referer": node.get("referer") or payload["referer"],
            "method_free": html.unescape(node.get("free-method") or payload["method_free"]),
            "method_premium": html.unescape(node.get("premium-method") or ""),
        })
    else:
        payload.update({
            key: value
            for key, value in _extract_hidden_inputs(html_text).items()
            if key in payload
        })
        payload["op"] = "download2"
        payload["id"] = file_code
    return payload


def parse_datanodes_sync(url: str, proxies: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    file_code, filename = _parse_datanodes_url(url)
    scraper = _scraper(proxies)

    page_response = scraper.get(url, timeout=30, allow_redirects=True)
    page_text = _response_text(page_response)
    fs_cookies: Dict[str, str] = {}
    if _cloudflare_challenge_seen(page_response, page_text):
        fs_page = _get_page_with_flaresolverr(url, proxies=proxies)
        if fs_page:
            page_text, fs_cookies, url = fs_page
    _raise_for_dead_page("DataNodes", page_text, getattr(page_response, "status_code", 0))
    file_info = _extract_datanodes_file_info(url, page_text)

    hidden_values = _extract_hidden_inputs(page_text)
    headers = {
        "Host": "datanodes.to",
        "Origin": "https://datanodes.to",
        "Referer": "https://datanodes.to/download",
        "User-Agent": DEFAULT_HOSTER_USER_AGENT,
        "Cookie": f"lang=english; file_name={filename}; file_code={file_code};",
    }
    if hidden_values.get("op") == "download1":
        first_payload = {**hidden_values, **_extract_submit_values(page_text)}
        first_payload["op"] = "download1"
        first_payload["id"] = file_code
        first_response = scraper.post(
            "https://datanodes.to/download",
            data=first_payload,
            headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
            allow_redirects=True,
        )
        page_text = _response_text(first_response)

    payload = _extract_datanodes_countdown_payload(page_text, file_code)
    response = scraper.post(
        "https://datanodes.to/download",
        files={key: (None, value) for key, value in payload.items()},
        headers={**headers, "Accept": "application/json, text/plain, */*"},
        timeout=30,
        allow_redirects=False,
    )

    location = response.headers.get("Location") or response.headers.get("location")
    if location:
        download_link = urljoin("https://datanodes.to/download", location)
    else:
        body = _response_text(response)
        download_link = ""
        try:
            data = response.json()
        except Exception:
            try:
                data = json.loads(body)
            except Exception:
                data = {}
        if isinstance(data, dict) and data.get("url"):
            download_link = unquote(str(data["url"]))
        if not download_link:
            download_link = _extract_download_link_from_html(body, "https://datanodes.to/download")

    if not _is_datanodes_download_link(download_link):
        body = _response_text(response)
        _raise_for_dead_page("DataNodes", body, getattr(response, "status_code", 0))
        raise HosterParseError("DataNodes 다운로드 링크를 찾을 수 없음")

    return HosterParseResult(
        download_link=download_link,
        file_info=file_info or None,
        cookies={**_cookies_dict(scraper), **fs_cookies},
        user_agent=DEFAULT_HOSTER_USER_AGENT,
        referer="https://datanodes.to/download",
    ).as_parse_result()


def parse_rapidgator_constraints_sync(url: str, proxies: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    scraper = _scraper(proxies)
    response = scraper.get(url, timeout=30)
    text = _response_text(response)
    if _cloudflare_challenge_seen(response, text):
        fs_page = _get_page_with_flaresolverr(url, proxies=proxies)
        if fs_page:
            text, _, url = fs_page
    _raise_for_dead_page("Rapidgator", text, getattr(response, "status_code", 0))

    soup = BeautifulSoup(text, "html.parser")
    file_info = {
        "name": _extract_title_filename(soup, url),
        "size": _extract_size_from_text(text),
    }
    file_info = {k: v for k, v in file_info.items() if v}
    size_bytes = size_to_bytes(file_info.get("size"))
    free_limit = 500 * 1024 * 1024
    if size_bytes and size_bytes > free_limit:
        raise HosterParseError(
            "Rapidgator 무료 모드는 500 MB 초과 파일 다운로드 불가 (프리미엄 필요)"
        )
    raise HosterParseError(
        "Rapidgator는 대기시간/captcha/계정 제약이 있어 현재 자동 다운로드를 지원하지 않음"
    )


def _gofile_content_id(url: str) -> str:
    path = urlparse(url or "").path or ""
    match = _GOFILE_ID_RE.search(path)
    return match.group(1) if match else ""


def _gofile_session(proxies: Optional[Dict[str, str]] = None) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_HOSTER_USER_AGENT})
    if proxies:
        session.proxies.update(proxies)
    return session


def _gofile_guest_token(session: requests.Session) -> str:
    response = session.post(f"{GOFILE_API_BASE}/accounts", timeout=30)
    payload = response.json() or {}
    if payload.get("status") != "ok":
        return ""
    return (payload.get("data") or {}).get("token") or ""


def _gofile_website_token(session: requests.Session) -> str:
    """Read the site's website token (wt) from config.js, with a static fallback."""
    response = session.get(GOFILE_CONFIG_JS_URL, timeout=30)
    match = _GOFILE_WT_RE.search(response.text or "")
    return match.group(1) if match else GOFILE_FALLBACK_WT


def _gofile_fetch_contents(
    session: requests.Session, content_id: str, token: str, wt: str
) -> Dict[str, object]:
    response = session.get(
        f"{GOFILE_API_BASE}/contents/{content_id}",
        params={**_GOFILE_CONTENTS_PARAMS, "wt": wt},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    return response.json() or {}


def _gofile_pick_file_node(data: Dict[str, object]) -> Dict[str, object]:
    if data.get("type") == "file":
        return data
    children = data.get("children") or {}
    files = [
        child for child in children.values()
        if isinstance(child, dict) and child.get("type") == "file"
    ]
    if not files:
        raise HosterParseError("Gofile 폴더에 다운로드할 파일이 없음")
    if len(files) > 1:
        raise HosterParseError(
            f"Gofile 폴더에 파일이 여러 개({len(files)}개) 있어 자동 다운로드 대상을 특정할 수 없음"
        )
    return files[0]


def _gofile_result(node: Dict[str, object], token: str) -> Dict[str, object]:
    link = node.get("link") or ""
    if not link:
        raise HosterParseError("Gofile 다운로드 링크를 찾을 수 없음")

    file_info: Dict[str, str] = {}
    name = node.get("name")
    if name:
        file_info["name"] = str(name)
    size = node.get("size")
    if isinstance(size, (int, float)) and size > 0:
        file_info["size"] = _format_size_bytes(int(size))

    return HosterParseResult(
        download_link=str(link),
        file_info=file_info or None,
        cookies={"accountToken": token},
        user_agent=DEFAULT_HOSTER_USER_AGENT,
        referer="https://gofile.io/",
    ).as_parse_result()


def parse_gofile_sync(url: str, proxies: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    content_id = _gofile_content_id(url)
    if not content_id:
        raise HosterParseError("Gofile 링크에서 콘텐츠 ID를 찾을 수 없음")

    session = _gofile_session(proxies)
    token = _gofile_guest_token(session)
    if not token:
        raise HosterParseError("Gofile 게스트 토큰 발급 실패")

    wt = _gofile_website_token(session)
    payload = _gofile_fetch_contents(session, content_id, token, wt)
    status = str(payload.get("status") or "")
    if status == "error-notPremium":
        raise HosterParseError(
            "Gofile 목록 조회 차단 (데이터센터 IP) — 가정용 IP/NAS에서 실행 시 정상 동작"
        )
    if status in {"error-notFound", "error-notExist"}:
        raise HosterParseError("Gofile 파일 없음 또는 삭제됨")
    if status != "ok":
        raise HosterParseError(f"Gofile 콘텐츠 조회 실패 (status={status or 'unknown'})")

    node = _gofile_pick_file_node(payload.get("data") or {})
    return _gofile_result(node, token)


def parse_blocked_hoster_sync(url: str, proxies: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    host = _host(url)
    if "send.now" in host:
        fs_page = _get_page_with_flaresolverr(url, proxies=proxies)
        if not fs_page:
            raise HosterParseError(
                "Send.now는 Cloudflare 챌린지로 인해 브라우저 세션 없이 자동 다운로드를 지원하지 않음"
            )
        text, cookies, final_url = fs_page
        _raise_for_dead_page("Send.now", text, 200)
        if _requires_turnstile(text):
            raise HosterParseError(
                "Send.now Turnstile 검증 필요 (FlareSolverr Cloudflare 통과 후 사이트 내부 캡차에서 중단)"
            )
        file_info = _extract_datanodes_file_info(final_url or url, text)
        download_link = _extract_download_link_from_html(text, final_url or url)
        if not download_link:
            raise HosterParseError("Send.now 다운로드 링크를 찾을 수 없음")
        return HosterParseResult(
            download_link=download_link,
            file_info=file_info or None,
            cookies=cookies,
            user_agent=DEFAULT_HOSTER_USER_AGENT,
            referer=final_url or url,
        ).as_parse_result()
    raise HosterParseError("지원하지 않는 호스팅 사이트")


def parse_special_hoster_sync(
    url: str, password: Optional[str] = None, proxies: Optional[Dict[str, str]] = None
) -> Dict[str, object]:
    """Resolve a special host page into the download-core parse_result shape."""
    host = _host(url)
    if host in {"megaup.net", "www.megaup.net"}:
        return parse_megaup_sync(url, proxies=proxies)
    if host in {"datanodes.to", "www.datanodes.to"}:
        return parse_datanodes_sync(url, proxies=proxies)
    if host in {"rapidgator.net", "www.rapidgator.net"}:
        return parse_rapidgator_constraints_sync(url, proxies=proxies)
    if host in {"gofile.io", "www.gofile.io"}:
        return parse_gofile_sync(url, proxies=proxies)
    if host in {"send.now", "www.send.now"}:
        return parse_blocked_hoster_sync(url, proxies=proxies)
    raise HosterParseError("지원하지 않는 호스팅 사이트")


# Hosts whose name/size can be read from a single page GET, without resolving
# the (per-request, expiring) download link. GoFile is excluded — its listing
# API is datacenter-IP gated, so a server-side info fetch returns nothing.
_INFO_ONLY_HOSTS = {
    "megaup.net", "www.megaup.net", "datanodes.to", "www.datanodes.to",
}


def fetch_special_hoster_file_info_sync(
    url: str, proxies: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """Fetch only the filename/size of a special-host page (no link resolution).

    A lightweight, idempotent GET used to fill in a queued item's name/size
    while it waits for a download slot. Returns ``{}`` (never raises) when the
    host is unsupported for info-only reads or anything goes wrong — the full
    parser still runs at download time and is the source of truth.
    """
    host = _host(url)
    if host not in _INFO_ONLY_HOSTS:
        return {}
    try:
        scraper = _scraper(proxies)
        response = scraper.get(url, timeout=30)
        text = _response_text(response)
        if _cloudflare_challenge_seen(response, text):
            fs_page = _get_page_with_flaresolverr(url, proxies=proxies)
            if fs_page:
                text, _, url = fs_page
        if host in {"megaup.net", "www.megaup.net"}:
            soup = BeautifulSoup(text, "html.parser")
            return _extract_megaup_file_info(soup, url, text)
        return _extract_datanodes_file_info(url, text)
    except Exception as exc:
        print(f"[WARNING] 특수 호스터 정보 사전조회 실패({_host(url)}): {exc}")
        return {}
