# -*- coding: utf-8 -*-
"""Per-host download-link resolvers.

Each parser turns a specific host's HTML/API page into the download-core
parse_result shape. Host-agnostic primitives come from ``core.hoster_common``;
the registry that routes to these parsers lives in ``core.hoster_parsers``.
"""

from __future__ import annotations

import base64
import html
import json
import re
import time
from typing import Dict, Optional
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from core.browser_solver import flow_for_host, solve_download_page
from core.hoster_common import (
    DEFAULT_HOSTER_USER_AGENT,
    HosterParseError,
    HosterParseResult,
    _cloudflare_challenge_seen,
    _cookies_dict,
    _extract_download_link_from_html,
    _extract_hidden_inputs,
    _extract_largest_size_from_text,
    _extract_size_from_text,
    _extract_submit_values,
    _extract_title_filename,
    _format_size_bytes,
    _get_page_with_flaresolverr,
    _host,
    _json_or_raise,
    _raise_for_dead_page,
    _requires_turnstile,
    _response_text,
    _scraper,
    get_flaresolverr_context_for_url,
    size_to_bytes,
)


__all__ = [
    'parse_megaup_sync',
    'parse_datanodes_sync',
    'parse_rapidgator_constraints_sync',
    'parse_gofile_sync',
    'parse_blocked_hoster_sync',
    'parse_pixeldrain_sync',
    'parse_mediafire_sync',
    'parse_bunkr_sync',
]


# MegaUp arms its ``?pt=`` hop behind a countdown (6s in the page's own script,
# but the server releases it sooner). Poll it instead of sleeping out the whole
# countdown: the first attempt usually already gets the 302. 3회 — 폴링이라도
# 호스터에는 요청 3개이고, 어차피 첫 번째에서 대부분 302 가 온다.
MEGAUP_CONTINUE_DELAY_SEC = 2
MEGAUP_CONTINUE_ATTEMPTS = 3

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


def _extract_megaup_continue_link(html_text: str, base_url: str) -> str:
    """The ``?pt=`` hop MegaUp's download page hides behind its countdown.

    Since 2026-08 the intermediate page no longer renders the tokenized file URL.
    It runs a countdown and then sends the browser to ``megaup.net/<code>?pt=…``,
    which 302s to the storage node. The page keeps the same link in its
    "if the download doesn't start, click here" fallback anchor, so the hop is
    readable without executing the page's (obfuscated) script.
    """
    soup = BeautifulSoup(html_text or "", "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = html.unescape((anchor.get("href") or "").strip())
        if "?pt=" in href or "&pt=" in href:
            return urljoin(base_url, href)
    match = re.search(
        r"""https?://[^'"\s<>]+[?&]pt=[^'"\s<>]+""",
        html_text or "",
        re.IGNORECASE,
    )
    return html.unescape(match.group(0)) if match else ""


def _follow_megaup_continue_link(
    continue_link: str,
    *,
    referer: str,
    cookies: Dict[str, str],
    user_agent: str,
    proxies: Optional[Dict[str, str]] = None,
) -> str:
    """Redeem the ``?pt=`` hop for the storage-node URL it redirects to.

    The hop is armed by a server-side countdown: asked too early it answers 200
    with the file page instead of a 302, so it is polled rather than waited out
    in full. Only the redirect target is wanted — the body is never downloaded.
    """
    headers = {
        "User-Agent": user_agent,
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "identity",
    }
    for _ in range(MEGAUP_CONTINUE_ATTEMPTS):
        time.sleep(MEGAUP_CONTINUE_DELAY_SEC)
        try:
            response = requests.get(
                continue_link,
                headers=headers,
                cookies=cookies,
                timeout=30,
                allow_redirects=False,
                stream=True,
                proxies=proxies,
            )
        except Exception as exc:
            print(f"[WARNING] MegaUp 대기 링크 확인 실패: {exc}")
            return ""
        try:
            location = response.headers.get("Location") or response.headers.get("location")
        finally:
            response.close()
        if location:
            return urljoin(continue_link, html.unescape(location.strip()))
    return ""


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

    page_url = response.url or download_link
    final_link = _extract_megaup_token_link(text, page_url)
    if not final_link:
        continue_link = _extract_megaup_continue_link(text, page_url)
        if continue_link:
            final_link = _follow_megaup_continue_link(
                continue_link,
                referer=page_url,
                cookies=merged_cookies,
                user_agent=browser_ua,
                proxies=proxies,
            )
    if not final_link:
        return download_link, merged_cookies, browser_ua, referer
    return final_link, merged_cookies, browser_ua, page_url


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


def _solve_via_browser(
    url: str,
    file_info: Optional[Dict[str, str]],
    referer: str,
    proxies: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    """Resolve a Turnstile-guarded page with the headful browser fallback.

    Only reached once the cheap cloudscraper path has proven that the host is
    sitting behind an in-page captcha, so the browser cost is paid at most once
    per link instead of on every parse.
    """
    result = solve_download_page(url, flow_for_host(_host(url)), proxies)
    return HosterParseResult(
        download_link=result.download_link,
        file_info=file_info or None,
        cookies=result.cookies,
        user_agent=result.user_agent,
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


def _extract_datanodes_filename(soup: BeautifulSoup) -> str:
    """The real filename, from the step-1 form the page submits.

    A bare ``datanodes.to/<code>`` link carries no name, and the page title is
    just the code — which is what the download used to be saved as: a name with
    no extension. The form that posts step 1 does know it, in a hidden ``fname``.
    The page header carries a decoy input of the same name (value "Download"),
    so the form is addressed directly and a value without a dot is never taken.
    """
    for selector in ('form#downloadForm input[name="fname"]', 'input[name="fname"]'):
        for node in soup.select(selector):
            value = html.unescape((node.get("value") or "").strip())
            if "." in value:
                return value
    return ""


def _extract_datanodes_file_info(url: str, html_text: str) -> Dict[str, str]:
    _, filename = _parse_datanodes_url(url)
    soup = BeautifulSoup(html_text or "", "html.parser")
    if not filename:
        filename = _extract_datanodes_filename(soup) or _extract_title_filename(soup, url)
    size = _extract_largest_size_from_text(html_text or "")
    info: Dict[str, str] = {}
    if filename:
        info["name"] = filename
    if size:
        info["size"] = size
    return info


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
    # The browser fallback has to start from the file page, not from whatever the
    # Cloudflare fallback below may rewrite ``url`` to.
    source_url = url
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

    # Since 2026-07 DataNodes gates the countdown step behind a Turnstile widget.
    # No amount of form replay clears it, so hand the page straight to the browser.
    if _requires_turnstile(page_text):
        return _solve_via_browser(source_url, file_info, "https://datanodes.to/download", proxies)

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
        if _requires_turnstile(body):
            return _solve_via_browser(source_url, file_info, "https://datanodes.to/download", proxies)
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
    payload = _json_or_raise(response, "Gofile")
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
    return _json_or_raise(response, "Gofile")


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
        file_info = _extract_datanodes_file_info(final_url or url, text)
        # FlareSolverr clears Cloudflare's interstitial but not the site's own
        # Turnstile widget; that one needs a real browser session.
        if _requires_turnstile(text):
            return _solve_via_browser(url, file_info, final_url or url, proxies)
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


# ---------------------------------------------------------------------------
# Pixeldrain — clean public API, no wait/captcha/token
# ---------------------------------------------------------------------------

PIXELDRAIN_API_BASE = "https://pixeldrain.com/api"
# /u/{id} = single file, /l/{id} = list; the id also appears in /api/file/{id}.
_PIXELDRAIN_ID_RE = re.compile(r"/(?:u|l|api/file)/([A-Za-z0-9]+)")


def _pixeldrain_file_id(url: str) -> str:
    match = _PIXELDRAIN_ID_RE.search(urlparse(url or "").path or "")
    return match.group(1) if match else ""


def parse_pixeldrain_sync(url: str, proxies: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    # A /l/ URL is a *list* (album), not a single file — the file API can't resolve
    # it, so say so clearly instead of returning a false "deleted" error.
    if "/l/" in (urlparse(url or "").path or ""):
        raise HosterParseError(
            "Pixeldrain 리스트(앨범) 링크는 지원하지 않음 — 개별 파일(/u/) 링크를 사용하세요"
        )

    file_id = _pixeldrain_file_id(url)
    if not file_id:
        raise HosterParseError("Pixeldrain 링크에서 파일 ID를 찾을 수 없음")

    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_HOSTER_USER_AGENT})
    if proxies:
        session.proxies.update(proxies)

    info_response = session.get(f"{PIXELDRAIN_API_BASE}/file/{file_id}/info", timeout=30)
    info_json = _json_or_raise(info_response, "Pixeldrain")
    if info_response.status_code == 404 or info_json.get("success") is False:
        raise HosterParseError("Pixeldrain 파일 없음 또는 삭제됨")

    file_info: Dict[str, str] = {}
    name = info_json.get("name")
    if name:
        file_info["name"] = str(name)
    size = info_json.get("size")
    if isinstance(size, (int, float)) and size > 0:
        file_info["size"] = _format_size_bytes(int(size))

    return HosterParseResult(
        download_link=f"{PIXELDRAIN_API_BASE}/file/{file_id}?download",
        file_info=file_info or None,
        user_agent=DEFAULT_HOSTER_USER_AGENT,
        referer="https://pixeldrain.com/",
    ).as_parse_result()


# ---------------------------------------------------------------------------
# MediaFire — HTML page with a (sometimes base64-scrambled) direct link
# ---------------------------------------------------------------------------

def _extract_mediafire_link(html_text: str) -> str:
    soup = BeautifulSoup(html_text or "", "html.parser")
    button = soup.select_one("a#downloadButton, a[aria-label='Download file']")
    if button:
        # Newer pages hide the real link in a base64 data-scrambled-url attribute.
        scrambled = (button.get("data-scrambled-url") or "").strip()
        if scrambled:
            try:
                decoded = base64.b64decode(scrambled).decode("utf-8", "ignore")
            except (ValueError, UnicodeDecodeError):
                decoded = ""
            if decoded.startswith("http"):
                return decoded
        href = html.unescape((button.get("href") or "").strip())
        if href.startswith("http"):
            return href

    match = re.search(
        r'https?://download[^\s"\'<>]*\.mediafire\.com[^\s"\'<>]*',
        html_text or "",
        re.IGNORECASE,
    )
    return html.unescape(match.group(0)) if match else ""


def _extract_mediafire_file_info(url: str, html_text: str) -> Dict[str, str]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    name_node = soup.select_one("div.filename, .dl-btn-label")
    filename = name_node.get_text(" ", strip=True) if name_node else ""
    if not filename:
        filename = _extract_title_filename(soup, url)
    size = _extract_size_from_text(html_text)
    info: Dict[str, str] = {}
    if filename:
        info["name"] = filename
    if size:
        info["size"] = size
    return info


def parse_mediafire_sync(url: str, proxies: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    scraper = _scraper(proxies)
    response = scraper.get(url, timeout=30, allow_redirects=True)
    text = _response_text(response)
    fs_cookies: Dict[str, str] = {}
    if _cloudflare_challenge_seen(response, text):
        fs_page = _get_page_with_flaresolverr(url, proxies=proxies)
        if fs_page:
            text, fs_cookies, url = fs_page
    _raise_for_dead_page("MediaFire", text, getattr(response, "status_code", 0))

    download_link = _extract_mediafire_link(text)
    if not download_link:
        raise HosterParseError("MediaFire 다운로드 링크를 찾을 수 없음")

    return HosterParseResult(
        download_link=download_link,
        file_info=_extract_mediafire_file_info(url, text) or None,
        cookies={**_cookies_dict(scraper), **fs_cookies},
        user_agent=DEFAULT_HOSTER_USER_AGENT,
        referer="https://www.mediafire.com/",
    ).as_parse_result()


# ---------------------------------------------------------------------------
# Bunkr — best-effort scrape. Bunkr rotates domains and now often serves an
# encrypted CDN link; when the page does not expose a plain file URL we fail
# loudly (per this module's contract) instead of saving a wrong asset.
# ---------------------------------------------------------------------------

BUNKR_HOSTS = (
    "bunkr.si", "bunkr.ru", "bunkr.la", "bunkr.is", "bunkr.to", "bunkr.ax",
    "bunkr.black", "bunkr.cr", "bunkr.fi", "bunkr.pk", "bunkr.ph", "bunkr.sk",
    "bunkr.ci", "bunkr.ws", "bunkr.site", "bunkr.media", "bunkrr.su", "bunkrr.ru",
)
_BUNKR_ASSET_EXT = (".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".woff", ".woff2")
_BUNKR_CDN_RE = re.compile(r'https?://[^\s"\'<>]+', re.IGNORECASE)
# Bunkr *page* routes (the HTML album/file/video pages) — never the actual file,
# so we must reject them, including the page's own og:url / canonical link.
_BUNKR_PAGE_ROUTES = ("/f/", "/v/", "/i/", "/d/", "/a/")


def _is_bunkr_file_link(candidate: str, page_url: str = "") -> bool:
    if not candidate:
        return False
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    # Must be a Bunkr-family host (cdn.bunkr.*, get.bunkrr.*, a bunkr.* mirror). A
    # bare "get.*" on some unrelated domain is an ad/redirect anchor, not the file.
    if "bunkr" not in host:
        return False
    if path.endswith(_BUNKR_ASSET_EXT):
        return False
    # A /f/, /v/, /i/, /d/, /a/ path is a Bunkr HTML page, not the file — reject it
    # (this is what stops the page's own URL being saved as the "download").
    if any(path.startswith(route) for route in _BUNKR_PAGE_ROUTES):
        return False
    if page_url and candidate.rstrip("/") == page_url.rstrip("/"):
        return False
    # A real file link: a CDN/download route, or a last segment with an extension.
    last_segment = path.rstrip("/").rsplit("/", 1)[-1]
    return "/file/" in path or "/download" in path or "." in last_segment


def _extract_bunkr_link(html_text: str, base_url: str) -> str:
    soup = BeautifulSoup(html_text or "", "html.parser")
    # 1) an explicit download button / CDN anchor
    for anchor in soup.select("a[href]"):
        href = html.unescape((anchor.get("href") or "").strip())
        if not href or href.startswith("#"):
            continue
        text = anchor.get_text(" ", strip=True).lower()
        looks_like_download = (
            "download" in text
            or "/download" in href.lower()
            or "/file/" in href.lower()
            or "get." in (urlparse(href).netloc or "").lower()
        )
        candidate = urljoin(base_url, href)
        if looks_like_download and _is_bunkr_file_link(candidate, base_url):
            return candidate

    # 2) a direct media element
    source = soup.select_one("source[src], video[src], img#image[src]")
    if source and source.get("src"):
        candidate = urljoin(base_url, html.unescape((source.get("src") or "").strip()))
        if _is_bunkr_file_link(candidate, base_url):
            return candidate

    # 3) last resort: any Bunkr CDN URL in the raw HTML (the validator excludes the
    # page's own URL, assets, and page routes, so this can't return the HTML page).
    for match in _BUNKR_CDN_RE.finditer(html_text or ""):
        candidate = html.unescape(match.group(0))
        if _is_bunkr_file_link(candidate, base_url):
            return candidate
    return ""


def parse_bunkr_sync(url: str, proxies: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    scraper = _scraper(proxies)
    response = scraper.get(url, timeout=30, allow_redirects=True)
    text = _response_text(response)
    fs_cookies: Dict[str, str] = {}
    if _cloudflare_challenge_seen(response, text):
        fs_page = _get_page_with_flaresolverr(url, proxies=proxies)
        if fs_page:
            text, fs_cookies, url = fs_page
    _raise_for_dead_page("Bunkr", text, getattr(response, "status_code", 0))

    download_link = _extract_bunkr_link(text, url)
    if not download_link:
        raise HosterParseError(
            "Bunkr 다운로드 링크를 찾을 수 없음 (암호화된 CDN 링크일 수 있음 — 다른 미러 사용 권장)"
        )

    soup = BeautifulSoup(text, "html.parser")
    file_info: Dict[str, str] = {}
    filename = _extract_title_filename(soup, download_link)
    if filename:
        file_info["name"] = filename
    size = _extract_largest_size_from_text(text)
    if size:
        file_info["size"] = size

    return HosterParseResult(
        download_link=download_link,
        file_info=file_info or None,
        cookies={**_cookies_dict(scraper), **fs_cookies},
        user_agent=DEFAULT_HOSTER_USER_AGENT,
        referer=url,
    ).as_parse_result()
