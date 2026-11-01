# -*- coding: utf-8 -*-
"""TeraBox's PC SDK download servers for a logged-in account, ported from TeraBox-NX.

The web ``dlink`` lands on a server that holds a free account to under 0.1 MiB/s.
``locatedownload`` returns the other servers holding the same file, and their
speeds differ by orders of magnitude, so a bounded measurement picks the server.
Connection count made no difference when measured: four ranges on the web link
shared the same total.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import http.client
import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, urlparse

import requests
import urllib3

from core.hoster_common import HosterParseError

SDK_USER_AGENT = "terabox;1.49.5.183;PC;PC-Windows;10.0.22631;WindowsTeraBox"
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
_WEB_PARAMS = {"app_id": "250528", "channel": "dubox", "web": "1", "clienttype": "0"}
_LOCATE_PARAMS = {
    "app_id": "250528", "method": "locatedownload", "check_blue": "1", "es": "1", "esl": "1",
    "ant": "1", "ver": "4.0", "dtype": "1", "err_ver": "1.0", "ehps": "1", "eck": "1", "vip": "2",
    "open_pflag": "0", "clienttype": "9", "version": "1.0.0.19", "channel": "0",
}
# The dlink's query is the signed grant, but it must not overrule our own request.
_DLINK_FIELDS_NOT_COPIED = frozenset(_LOCATE_PARAMS) | {"path", "time", "rand", "devuid", "psign"}
_ENCRYPTION_FIELDS = ("encrypt_key", "encrypt_key_list", "algorithm_bit", "slice_size")

_TIMEOUT = 30
MIN_MEASURED_FILE_BYTES = 64 * 1024 * 1024
MAX_MEASURED_SERVERS = 4
PROBE_BYTES = 4 * 1024 * 1024
PROBE_SECONDS = 4
_MIN_PROBE_BYTES = 512 * 1024
_REQUIRED_GAIN = 1.25

_JS_TOKEN_MARKERS = (("fn%28%22", "%22%29"), ('fn("', '")'))
_JS_TOKEN_JSON_RE = re.compile(r'"jsToken"\s*:\s*"((?:[^"\\]|\\.)*)"')
_HEX_RE = re.compile(r"^[0-9a-fA-F]{32,512}$")
_REGION_PREFIX_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,30}[A-Za-z0-9])?")
_MAX_REGION_HOPS = 3
_ERRNO_WRONG_REGION = -6
_TRANSFER_ERRORS = (requests.RequestException, urllib3.exceptions.HTTPError, http.client.HTTPException, OSError)


class TeraboxUnreachable(HosterParseError):
    """TeraBox could not be asked, which says nothing about the cookie or the file."""


@dataclass(frozen=True)
class ShareGrant:
    owner: str
    share_id: str
    fs_id: str
    md5: str
    sekey: str
    dlink: str


def extract_js_token(html_text: str) -> str:
    for opening, closing in _JS_TOKEN_MARKERS:
        begin = (html_text or "").find(opening)
        if begin < 0:
            continue
        begin += len(opening)
        end = html_text.find(closing, begin)
        if end > begin and _HEX_RE.match(html_text[begin:end]):
            return html_text[begin:end]
    match = _JS_TOKEN_JSON_RE.search(html_text or "")
    if not match:
        return ""
    try:
        return json.loads('"' + match.group(1) + '"')
    except ValueError:
        return ""


def first_cookie(jar: Iterable, name: str, host: str) -> str:
    """The cookie for ``host``. A jar can hold one name on several domains, where ``jar.get`` raises."""
    for cookie in jar:
        domain = (cookie.domain or "").lstrip(".")
        if cookie.name == name and (not domain or host == domain or host.endswith("." + domain)):
            return cookie.value or ""
    return ""


def _rc4(data: bytes, key: bytes) -> bytes:
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) & 255
        state[i], state[j] = state[j], state[i]
    i = j = 0
    output = bytearray()
    for byte in data:
        i = (i + 1) & 255
        j = (j + state[i]) & 255
        state[i], state[j] = state[j], state[i]
        output.append(byte ^ state[(state[i] + state[j]) & 255])
    return bytes(output)


def runtime_key(encoded: str, account: str) -> bytes:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise HosterParseError("TeraBox 다운로드 인증 토큰을 읽지 못했습니다") from None
    if not raw or len(raw) > 256:
        raise HosterParseError("TeraBox 다운로드 인증 토큰을 읽지 못했습니다")
    return _rc4(raw, account.encode())


def request_nonce(ndus: str, account: str, key: bytes, seconds: int, device: str) -> str:
    cookie_digest = hashlib.sha1(ndus.encode()).hexdigest()
    return hashlib.sha1(
        cookie_digest.encode() + account.encode() + key + str(seconds).encode() + device.encode()
    ).hexdigest()


def _is_encrypted(entry: dict) -> bool:
    return bool(entry.get("is_encrypt")) or any(entry.get(field) for field in _ENCRYPTION_FIELDS)


def _usable_link(url) -> bool:
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    try:
        return bool(urlparse(url).hostname)
    except ValueError:
        return False


def parse_candidates(payload: dict) -> List[str]:
    """The server's ordered links this receiver can use: plain, HTTPS, unique."""
    if not isinstance(payload, dict):
        raise HosterParseError("TeraBox 다운로드 서버 응답 형식이 올바르지 않습니다")
    for field in ("errno", "error_code"):
        if payload.get(field):
            raise HosterParseError(f"TeraBox 다운로드 주소 발급 거절 (오류 {payload[field]})")
    if _is_encrypted(payload):
        raise HosterParseError("TeraBox가 암호화 전송 형식을 지정했습니다")
    links: List[str] = []
    for group in ("urls", "bakurls"):
        entries = payload.get(group)
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or _is_encrypted(entry):
                continue
            url = entry.get("url")
            if _usable_link(url) and url not in links:
                links.append(url)
    if not links:
        raise HosterParseError("TeraBox가 HTTPS 다운로드 서버를 주지 않았습니다")
    return links


def _json_reply(response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        raise HosterParseError("TeraBox 계정 응답 형식이 올바르지 않습니다") from None
    if not isinstance(payload, dict):
        raise HosterParseError("TeraBox 계정 응답 형식이 올바르지 않습니다")
    return payload


def regional_origin(origin: str, prefix: str) -> str:
    """``origin`` on the regional host TeraBox named; a malformed prefix changes nothing."""
    if not _REGION_PREFIX_RE.fullmatch(prefix or ""):
        return origin
    host = urlparse(origin).hostname or ""
    domain = host.split(".", 1)[1] if host.count(".") >= 2 else host
    return f"https://{prefix}.{domain}"


def region_prefix(headers) -> str:
    return headers.get("url-domain-prefix") or headers.get("region-domain-prefix") or ""


def _answered(response, what: str):
    if response.status_code != 200:
        raise TeraboxUnreachable(f"TeraBox {what} HTTP {response.status_code}")
    return response


def _open_account(session, origin: str, ndus: str, proxies) -> Dict[str, str]:
    """Log ``session`` in with ``ndus``: ``{"origin": ..., "token": ..., "uk": ...}``.

    An account lives on one regional host. Elsewhere its session is refused with
    -6 and a header naming the right host, which is not an expired login, and the
    page there may not carry a token, so the check runs either way.
    """
    session.headers["User-Agent"] = _BROWSER_USER_AGENT
    if proxies:
        session.proxies.update(proxies)
    for _ in range(_MAX_REGION_HOPS):
        session.headers["Referer"] = origin + "/"
        session.cookies.set("ndus", ndus, domain="." + urlparse(origin).hostname.removeprefix("www."), secure=True)
        page = _answered(session.get(origin + "/main?category=all&path=%2F", timeout=_TIMEOUT), "계정 페이지")
        token = extract_js_token(page.text)
        params = {**_WEB_PARAMS, **({"jsToken": token} if token else {})}
        reply = _answered(session.get(origin + "/api/check/login", params=params, timeout=_TIMEOUT), "계정 확인")
        check = _json_reply(reply)
        regional = regional_origin(origin, region_prefix(reply.headers))
        if check.get("errno") != _ERRNO_WRONG_REGION or regional == origin:
            break
        origin = regional
    if check.get("errno"):
        raise HosterParseError(f"TeraBox 계정 쿠키 확인 실패 (오류 {check['errno']})")
    if not token:
        raise HosterParseError("TeraBox 계정 페이지 인증 정보를 읽지 못했습니다")
    uk = str(check.get("uk") or "")
    if not uk.isdigit():
        raise HosterParseError("TeraBox 계정 번호를 읽지 못했습니다")
    return {"origin": origin, "token": token, "uk": uk}


def verify_ndus(origin: str, ndus: str, proxies: Optional[Dict[str, str]] = None) -> None:
    """Raise unless TeraBox itself accepts ``ndus`` as logged in."""
    try:
        _open_account(requests.Session(), origin, ndus, proxies)
    except requests.RequestException as exc:
        raise TeraboxUnreachable(f"TeraBox 계정 쿠키 확인 실패 ({type(exc).__name__})") from None


def _locate_query(ndus: str, uk: str, key: bytes, grant: ShareGrant) -> Dict[str, str]:
    now = int(time.time())
    device = uuid.uuid4().hex
    query = {
        **_LOCATE_PARAMS, "path": grant.md5, "time": str(now), "devuid": device,
        "rand": request_nonce(ndus, uk, key, now, device),
        "product": "share", "uk": grant.owner, "primaryid": grant.share_id,
        "fid_list": f"[{grant.fs_id}]", "extra": json.dumps({"sekey": grant.sekey}),
    }
    for name, value in parse_qsl(urlparse(grant.dlink).query, keep_blank_values=True):
        if name not in _DLINK_FIELDS_NOT_COPIED:
            query[name] = value
    return query


def locate_candidates(origin: str, ndus: str, grant: ShareGrant, proxies: Optional[Dict[str, str]]) -> List[str]:
    session = requests.Session()
    try:
        account = _open_account(session, origin, ndus, proxies)
        origin = account["origin"]
        session.headers.update({
            "User-Agent": SDK_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
        })
        report = _json_reply(session.post(
            origin + "/api/report/user",
            params={**_WEB_PARAMS, "jsToken": account["token"]},
            data={"action": "pc_uniyunguanjia_login", "timestamp": str(int(time.time()))},
            timeout=_TIMEOUT,
        ))
        if not isinstance(report.get("uinfo"), str):
            raise HosterParseError("TeraBox 다운로드 인증 토큰이 없습니다")
        key = runtime_key(report["uinfo"], account["uk"])
        query = _locate_query(ndus, account["uk"], key, grant)
        return parse_candidates(_json_reply(session.get(origin + "/rest/2.0/pcs/file", params=query, timeout=_TIMEOUT)))
    except requests.RequestException as exc:
        raise TeraboxUnreachable(f"TeraBox 다운로드 서버 조회 실패 ({type(exc).__name__})") from None


def choose_fastest(candidates: List[str], measure: Callable[[str], float]) -> str:
    """The server order is a hint: a later server wins only by a clear margin."""
    best = ""
    best_rate = 0.0
    for candidate in candidates[:MAX_MEASURED_SERVERS]:
        rate = measure(candidate)
        if rate and (not best_rate or rate > best_rate * _REQUIRED_GAIN):
            best, best_rate = candidate, rate
    if not best:
        raise HosterParseError("TeraBox 다운로드 서버가 응답하지 않습니다")
    return best


def _first_answering(candidates: List[str], measure: Callable[[str], float]) -> str:
    for candidate in candidates[:MAX_MEASURED_SERVERS]:
        if measure(candidate):
            return candidate
    raise HosterParseError("TeraBox 다운로드 서버가 응답하지 않습니다")


def _measure_rate(url: str, offset: int, length: int, ndus: str, cookie_domain: str, referer: str) -> float:
    """Bytes per second over a bounded range; 0 for a refusal or too little data to judge."""
    session = requests.Session()
    if ndus and cookie_domain:
        session.cookies.set("ndus", ndus, domain="." + cookie_domain, secure=True)
    headers = {
        "User-Agent": SDK_USER_AGENT,
        "Accept-Encoding": "identity",
        "Range": f"bytes={offset}-{offset + length - 1}",
        "Referer": referer,
    }
    started = time.monotonic()
    received = 0
    try:
        with session.get(url, headers=headers, stream=True, timeout=(PROBE_SECONDS, PROBE_SECONDS)) as response:
            if response.status_code != 206:
                return 0.0
            # read1 returns whatever has arrived, so a dribbling server cannot outlast the deadline.
            while received < length and time.monotonic() - started < PROBE_SECONDS:
                chunk = response.raw.read1(64 * 1024)
                if not chunk:
                    break
                received += len(chunk)
    except _TRANSFER_ERRORS:
        pass  # A stalled server still reports what it managed before the timeout.
    finally:
        session.close()
    if received < min(_MIN_PROBE_BYTES, length):
        return 0.0
    return received / max(time.monotonic() - started, 0.001)


def fastest_link(
    candidates: List[str], size: int, ndus: str, referer: str, cookie_domain_of: Callable[[str], str],
) -> str:
    """A server that actually serves the file, measured mid-file because the start may be cached."""
    offset = size // 2
    length = min(PROBE_BYTES, size - offset)

    def measure(url: str) -> float:
        return _measure_rate(url, offset, length, ndus, cookie_domain_of(url), referer)

    if size < MIN_MEASURED_FILE_BYTES:
        return _first_answering(candidates, measure)
    return choose_fastest(candidates, measure)
