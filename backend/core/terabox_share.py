# -*- coding: utf-8 -*-
"""TeraBox public share links, resolved over the site's own web API.

The flow follows what the official web app does for a visitor: the share page
hands out a ``jsToken``, an optional password is verified for a ``randsk``,
``shorturlinfo`` names the share and lists its root, and ``share/download``
returns the signed ``dlink``. No browser is involved, so it also works on the
Windows build.

A share that holds several files becomes one download row per file. A row for
one file carries its ``fs_id`` in the ``fid`` query, which only this app reads.

With an account cookie the dlink is only the grant: ``core.terabox_sdk`` trades
it for the faster download servers, and the dlink stays as the fallback.
"""

from __future__ import annotations

import json
import re
from typing import Dict, Iterator, List, Optional
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

import requests

from core import terabox_sdk
from core.config import get_config
from core.hoster_common import (
    DEFAULT_HOSTER_USER_AGENT,
    HosterParseError,
    HosterParseResult,
    _format_size_bytes,
)
from core.terabox_sdk import extract_js_token, first_cookie

TERABOX_SHARE_HOSTS = frozenset({
    "terabox.com", "teraboxapp.com", "terabox.app", "1024terabox.com",
    "1024tera.com", "nephobox.com", "terasharelink.com",
})

_APP_PARAMS = {"app_id": "250528", "web": "1", "clienttype": "0", "channel": "dubox"}
_TIMEOUT = 30
_MAX_DIRECTORIES = 50
_MAX_SHARE_FILES = 200
_MAX_REGION_HOPS = 2
_FILE_ID_PARAM = "fid"
_LIST_PAGE_SIZE = 100
_MAX_LIST_PAGES = 100

# errno values the share API answers with, as the official web app reads them.
_ERRNO_WRONG_PASSWORD = {-9, -12}
_ERRNO_GONE = {-7, 2, 12}
_ERRNO_LOGIN_REQUIRED = {-6}
_REFUSED = "익명 다운로드 요청을 거절"

_SURL_PATH_RE = re.compile(r"^/s/1([A-Za-z0-9_-]+)")
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_NDUS_IN_HEADER_RE = re.compile(r"(?:^|[;\s])ndus=([^;\s]+)")
_MAX_NDUS_LENGTH = 8192


def is_terabox_share_host(host: str) -> bool:
    host = (host or "").lower()
    return any(host == known or host.endswith("." + known) for known in TERABOX_SHARE_HOSTS)


def terabox_cookie_domain(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return ""
    host = (parsed.hostname or "").lower()
    return next((domain for domain in TERABOX_SHARE_HOSTS
                 if host == domain or host.endswith("." + domain)), "")


def terabox_download_error(status: int, preview: bytes) -> str:
    if status != 403:
        return ""
    try:
        payload = json.loads(preview)
    except (ValueError, UnicodeDecodeError):
        return ""
    if isinstance(payload, dict) and payload.get("error_code") == 31045:
        return "TeraBox 다운로드 인증 세션이 없거나 만료되었습니다 (오류 31045)"
    return ""


def parse_share_link(url: str):
    """``(origin, code, password)`` for a ``/s/1<code>`` link or any page that carries ``?surl=``."""
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not is_terabox_share_host(host):
        raise HosterParseError("TeraBox 공유 주소가 아닙니다")
    query = parse_qs(parsed.query)
    password = (query.get("pwd") or [""])[0]
    match = _SURL_PATH_RE.match(parsed.path)
    if match:
        code = match.group(1)
    else:
        code = (query.get("surl") or [""])[0]
    if not _CODE_RE.match(code):
        raise HosterParseError("TeraBox 공유 주소에서 공유 번호를 찾지 못했습니다")
    origin = "https://" + ("www." + host if host.count(".") == 1 else host)
    return origin, code, password


def with_password(url: str, password: str) -> str:
    """``url`` with its ``pwd`` query replaced by ``password``."""
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qs(parsed.query, keep_blank_values=True).items() if k != "pwd"]
    flat = [(k, item) for k, values in query for item in values] + [("pwd", password)]
    return urlunparse(parsed._replace(query=urlencode(flat)))


def selected_file_id(url: str) -> str:
    """The share file a row stands for, or "" for the whole share."""
    return (parse_qs(urlparse(url).query).get(_FILE_ID_PARAM) or [""])[0]


def normalize_ndus(raw: Optional[str]) -> str:
    """The bare value from whatever was pasted: the value, ``ndus=value``, or a whole Cookie header."""
    text = (raw or "").strip()
    match = _NDUS_IN_HEADER_RE.search(text)
    value = match.group(1) if match else text
    if len(value) > _MAX_NDUS_LENGTH or re.search(r"[;\s]", value):
        raise HosterParseError("TeraBox 계정 쿠키 형식이 올바르지 않습니다. ndus 값만 입력하세요")
    return value


class _Share:
    def __init__(self, origin: str, code: str, password: str, proxies, ndus: str = ""):
        self.origin = origin
        self.code = code
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": DEFAULT_HOSTER_USER_AGENT,
            "Referer": f"{origin}/sharing/link?surl={code}",
        })
        if proxies:
            self.session.proxies.update(proxies)
        if ndus:
            for domain in TERABOX_SHARE_HOSTS:
                self.session.cookies.set("ndus", ndus, domain="." + domain, secure=True)
        self.token = ""
        self.sekey = ""
        self.sign = ""
        self.timestamp = ""
        self.owner = ""
        self.share_id = ""
        self.region_hops = 0

    def call(self, path: str, query: Dict[str, str], body: Optional[Dict[str, str]] = None) -> dict:
        params = {**_APP_PARAMS, "jsToken": self.token, **query}
        url = self.origin + path
        try:
            if body is None:
                response = self.session.get(url, params=params, timeout=_TIMEOUT)
            else:
                response = self.session.post(url, params=params, data=body, timeout=_TIMEOUT)
        except requests.RequestException as exc:
            # requests' message carries the query: jsToken and the share's sign.
            raise HosterParseError(f"TeraBox 공유 요청 실패 ({type(exc).__name__})") from None
        if response.status_code == 429:
            raise HosterParseError("TeraBox 요청이 너무 많음 (HTTP 429)")
        if response.status_code != 200:
            raise HosterParseError(f"TeraBox 공유 응답 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not isinstance(payload, dict) or not isinstance(payload.get("errno"), int):
            raise HosterParseError("TeraBox 공유 응답 형식이 올바르지 않습니다")
        code = payload["errno"]
        if code in _ERRNO_LOGIN_REQUIRED and self._moved_to_region(response.headers):
            return self.call(path, query, body)
        if code in _ERRNO_WRONG_PASSWORD:
            raise HosterParseError("TeraBox 공유 암호가 올바르지 않습니다 (주소 뒤에 ?pwd=암호 를 붙이세요)")
        if path == "/share/download" and code == 2:
            raise HosterParseError(
                "TeraBox가 익명 다운로드 요청을 거절했습니다 (오류 2). 로그인 계정이 필요할 수 있습니다"
            )
        if code in _ERRNO_GONE:
            raise HosterParseError("TeraBox 공유 링크가 만료되었거나 삭제되었습니다")
        if code in _ERRNO_LOGIN_REQUIRED:
            raise HosterParseError("TeraBox 공유 파일 다운로드에 로그인이 필요합니다")
        if code:
            raise HosterParseError(f"TeraBox 공유 요청 오류 {code}")
        return payload

    def _moved_to_region(self, headers) -> bool:
        """-6 with a regional host means this account lives there, not that it needs a login."""
        regional = terabox_sdk.regional_origin(self.origin, terabox_sdk.region_prefix(headers))
        if regional == self.origin or self.region_hops >= _MAX_REGION_HOPS:
            return False
        self.region_hops += 1
        self.origin = regional
        return True

    def open(self) -> List[dict]:
        try:
            page = self.session.get(
                f"{self.origin}/sharing/link", params={"surl": self.code}, timeout=_TIMEOUT
            )
        except requests.RequestException as exc:
            raise HosterParseError(f"TeraBox 공유 페이지 요청 실패 ({type(exc).__name__})") from None
        if page.status_code != 200:
            raise HosterParseError(f"TeraBox 공유 페이지 HTTP {page.status_code}")
        settled = urlparse(page.url).hostname or ""
        if not is_terabox_share_host(settled):
            raise HosterParseError("TeraBox 공유 페이지가 다른 사이트로 이동했습니다")
        # A redirected API call turns POST into GET and loses its body.
        self.origin = "https://" + settled
        self.token = extract_js_token(page.text)
        if not self.token:
            raise HosterParseError("TeraBox 공유 페이지 인증 정보를 읽지 못했습니다")
        if self.password:
            verified = self.call(
                "/share/verify", {"surl": self.code},
                {"pwd": self.password, "vcode": "", "vcode_str": ""},
            )
            self.sekey = verified.get("randsk") or ""
        info = self.call("/api/shorturlinfo", {"shorturl": "1" + self.code, "root": "1", "scene": ""})
        self.owner = str(info.get("uk_str") or info.get("uk") or "")
        self.share_id = str(info.get("shareid") or "")
        if not self.owner.isdigit() or not self.share_id.isdigit():
            raise HosterParseError("TeraBox 공유 링크의 소유자 정보를 읽지 못했습니다")
        self.sekey = unquote(
            self.sekey or info.get("randsk") or first_cookie(self.session.cookies, "BOXCLND", settled)
        )
        self.sign = info.get("sign") or ""
        self.timestamp = str(info.get("timestamp") or "")
        return list(info.get("list") or [])

    def list_directory(self, directory: str) -> List[dict]:
        rows: List[dict] = []
        for page in range(1, _MAX_LIST_PAGES + 1):
            reply = self.call("/share/list", {
                "shareid": self.share_id, "uk": self.owner, "dir": directory, "root": "0",
                "page": str(page), "num": str(_LIST_PAGE_SIZE), "order": "name", "desc": "0",
            })
            rows.extend(reply.get("list") or [])
            if not reply.get("has_more"):
                return rows
        raise HosterParseError("TeraBox 공유 폴더 목록이 너무 큽니다")

    def walk(self, roots: List[dict]) -> Iterator[dict]:
        """Every file in the share, opening folders only as far as the caller reads."""
        pending = list(roots)
        listed = 0
        while pending:
            row = pending.pop(0)
            if str(row.get("isdir")) != "1":
                yield row
                continue
            listed += 1
            if listed > _MAX_DIRECTORIES:
                raise HosterParseError("TeraBox 공유 폴더가 너무 많습니다")
            pending.extend(self.list_directory(row.get("path") or ""))

    def file_url(self, row: dict) -> str:
        """The row URL for one file. A fixed form, so two splits of a share compare equal."""
        query = [(_FILE_ID_PARAM, str(row["fs_id"]))] + ([("pwd", self.password)] if self.password else [])
        return f"{self.origin}/s/1{self.code}?{urlencode(query)}"

    def dlink(self, row: dict) -> str:
        reply = self.call(
            "/share/download",
            {"shareid": self.share_id, "sign": self.sign, "timestamp": self.timestamp, "type": "dlink"},
            {
                "product": "share", "uk": self.owner, "primaryid": self.share_id,
                "fid_list": f"[{row['fs_id']}]", "extra": json.dumps({"sekey": self.sekey}),
            },
        )
        link = reply.get("dlink")
        if isinstance(link, list) and len(link) == 1 and isinstance(link[0], dict):
            link = link[0].get("dlink")
        if not isinstance(link, str) or not link.startswith("https://") or len(link) > 16384:
            raise HosterParseError("TeraBox 공유 다운로드 HTTPS 주소를 받지 못했습니다")
        return link


def _sdk_link(share: _Share, row: dict, dlink: str, size: int, ndus: str, proxies) -> str:
    """The fastest SDK server, or "" to stay on the web link."""
    md5 = str(row.get("md5") or "")
    if not ndus or not md5 or size <= 0:
        return ""
    grant = terabox_sdk.ShareGrant(share.owner, share.share_id, str(row["fs_id"]), md5, share.sekey, dlink)
    try:
        candidates = terabox_sdk.locate_candidates(share.origin, ndus, grant, proxies)
        link = terabox_sdk.fastest_link(candidates, size, ndus, f"{share.origin}/", terabox_cookie_domain)
    except HosterParseError as exc:
        print(f"[LOG] TeraBox SDK 서버를 쓰지 못해 웹 주소로 받습니다: {exc}")
        return ""
    print(f"[LOG] TeraBox SDK 서버 선택: {urlparse(link).hostname} (후보 {len(candidates)}개)")
    return link


def _file_details(row: dict) -> Dict[str, str]:
    info: Dict[str, str] = {}
    if row.get("server_filename"):
        info["name"] = str(row["server_filename"])
    size = int(row.get("size") or 0)
    if size > 0:
        info["size"] = _format_size_bytes(size)
    return info


def _find_file(share: _Share, roots: List[dict], wanted: str) -> dict:
    for row in share.walk(roots):
        if str(row.get("fs_id")) == wanted:
            return row
    raise HosterParseError("TeraBox 공유에서 이 파일을 찾지 못했습니다")


def _list_files(share: _Share, roots: List[dict]) -> List[dict]:
    files: List[dict] = []
    for row in share.walk(roots):
        files.append(row)
        if len(files) > _MAX_SHARE_FILES:
            raise HosterParseError(f"TeraBox 공유 파일이 너무 많습니다 (최대 {_MAX_SHARE_FILES}개)")
    if not files:
        raise HosterParseError("TeraBox 공유에 받을 파일이 없습니다")
    return files


def _resolve(url: str, proxies, ndus: str) -> Dict[str, object]:
    origin, code, password = parse_share_link(url)
    share = _Share(origin, code, password, proxies, ndus)
    roots = share.open()
    wanted = selected_file_id(url)
    if wanted:
        row = _find_file(share, roots, wanted)
    else:
        files = _list_files(share, roots)
        if len(files) > 1:
            # No link yet: a failure on one file belongs to that file's row.
            return HosterParseResult(
                download_link="",
                split_into=[{"url": share.file_url(item), **_file_details(item)} for item in files],
            ).as_parse_result()
        row = files[0]
    info = _file_details(row)
    size = int(row.get("size") or 0)
    link = share.dlink(row)
    sdk_link = _sdk_link(share, row, link, size, ndus, proxies)
    if sdk_link:
        return HosterParseResult(
            download_link=sdk_link,
            file_info=info or None,
            cookies={"ndus": ndus} if terabox_cookie_domain(sdk_link) else {},
            user_agent=terabox_sdk.SDK_USER_AGENT,
            # Without one the transfer falls back to the request URL and its ?pwd=.
            referer=f"{share.origin}/",
        ).as_parse_result()
    return HosterParseResult(
        download_link=link,
        file_info=info or None,
        # File servers authenticate the dlink too. Preserve ndus only for a
        # TeraBox destination; the transfer builds a domain-scoped cookie jar.
        cookies={
            **{k: v for k, v in share.session.cookies.get_dict().items() if k != "ndus"},
            **({"ndus": ndus} if ndus and terabox_cookie_domain(link) else {}),
        },
        user_agent=DEFAULT_HOSTER_USER_AGENT,
        referer=f"{share.origin}/sharing/link?surl={code}",
    ).as_parse_result()


def parse_terabox_share_sync(url: str, proxies: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    return _resolve(url, proxies, normalize_ndus(get_config().get("terabox_ndus")))
