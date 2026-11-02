# -*- coding: utf-8 -*-
"""TeraBox QR sign-in, producing the server-side ``ndus`` account cookie."""

from __future__ import annotations

import base64
import binascii
import json
import secrets
import threading
import time
from typing import Dict, Optional
from urllib.parse import urlparse

import requests

from core.hoster_common import HosterParseError
from core.terabox_sdk import TeraboxUnreachable, extract_js_token, first_cookie, regional_origin, verify_ndus

LOGIN_PAGE = "https://www.terabox.com/ai/index"
_LOGIN_HOSTS = ("terabox.com", "terabox.app", "1024terabox.com", "nephobox.com")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
_TIMEOUT = 30


def _trusted_origin(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    ok = any(host == d or host.endswith("." + d) for d in _LOGIN_HOSTS)
    if parsed.scheme != "https" or not ok:
        raise HosterParseError("TeraBox 로그인 서버가 공식 주소가 아닙니다")
    return f"https://{host}"


def _page_token(html: str, key: str) -> str:
    marker = f'"{key}"'
    at = html.find(marker)
    while at >= 0:
        rest = html[at + len(marker):].lstrip()
        if rest.startswith(":"):
            rest = rest[1:].lstrip()
            if rest.startswith('"'):
                end = rest.find('"', 1)
                if end > 1:
                    return rest[1:end]
        at = html.find(marker, at + len(marker))
    return ""


def _decode(response: requests.Response):
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise HosterParseError("TeraBox 로그인 서버가 정상적인 응답을 주지 않았습니다")
    raw = payload.get("code", payload.get("errno"))
    try:
        return int(raw), payload
    except (TypeError, ValueError):
        raise HosterParseError("TeraBox 로그인 응답 형식이 변경되었습니다") from None


def _fail(code: int):
    raise HosterParseError(
        f"TeraBox QR 로그인 실패 (오류 {code}): TeraBox 앱에서 다시 승인하거나 계정 쿠키를 입력하세요"
    )


def _reply(response: requests.Response) -> dict:
    code, payload = _decode(response)
    if code:
        _fail(code)
    return payload


def _open_login_page(proxies: Optional[Dict[str, str]]):
    """A session on the official login page: ``(session, origin, form)``."""
    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})
    if proxies:
        session.proxies.update(proxies)
    page = session.get(LOGIN_PAGE, timeout=_TIMEOUT)
    origin = _trusted_origin(page.url)
    pcf = _page_token(page.text, "pcftoken")
    browser_id = first_cookie(session.cookies, "browserid", urlparse(origin).hostname)
    if not pcf or not browser_id:
        raise HosterParseError("TeraBox 로그인 준비 정보를 받지 못했습니다 (접근 가능 지역을 확인하세요)")
    session.headers.update({
        "Referer": page.url, "Origin": origin,
        "X-Requested-With": "XMLHttpRequest", "Accept-Language": "en-US,en;q=0.9",
    })
    form = {
        "client": "web", "clientfrom": "h5", "lang": "en", "pass_version": "2.8",
        "pcftoken": pcf, "browserid": browser_id, "psign": "0",
    }
    token = extract_js_token(page.text)
    session.params.update({
        "app_id": "250528", "web": "1", "channel": "dubox", "clienttype": "0",
        "version": "0", "devuid": "0", "cuid": "0", "lang": "en",
    })
    if token:
        session.params["jsToken"] = token
    return session, origin, form


_QR_TTL = 600
_QR_MAX = 8
_qr_lock = threading.Lock()
_qr_sessions: Dict[str, dict] = {}


def _qr_data(payload: dict) -> dict:
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _is_png(image: str) -> bool:
    try:
        return base64.b64decode(image, validate=True).startswith(b"\x89PNG\r\n\x1a\n")
    except (binascii.Error, ValueError):
        return False


def qr_start(proxies: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    """Begin a QR sign-in: the image to scan with the TeraBox app and a handle to poll."""
    try:
        session, origin, form = _open_login_page(proxies)
        payload = _reply(session.post(origin + "/passport/qrcode/get", data=form, timeout=_TIMEOUT))
    except requests.RequestException as exc:
        raise HosterParseError(f"TeraBox 로그인 서버에 연결하지 못했습니다 ({type(exc).__name__})") from None
    data = _qr_data(payload)
    uuid, seq = str(data.get("uuid") or ""), str(data.get("seq") or "")
    image = str(data.get("qrcode") or "").removeprefix("data:image/png;base64,")
    if not uuid or not seq.isdigit() or not image or len(image) > 1024 * 1024:
        raise HosterParseError("TeraBox QR 로그인 응답에 필요한 정보가 없습니다")
    if not _is_png(image):
        raise HosterParseError("TeraBox가 정상적인 QR 이미지를 주지 않았습니다")
    try:
        ttl = min(max(int(data.get("expires_in") or 300), 1), _QR_TTL)
    except (TypeError, ValueError):
        ttl = 300
    handle = secrets.token_urlsafe(16)
    now = time.monotonic()
    with _qr_lock:
        for key in [k for k, v in _qr_sessions.items() if v["deadline"] <= now]:
            del _qr_sessions[key]
        while len(_qr_sessions) >= _QR_MAX:
            del _qr_sessions[min(_qr_sessions, key=lambda k: _qr_sessions[k]["deadline"])]
        _qr_sessions[handle] = {
            "session": session, "origin": origin, "form": form, "uuid": uuid,
            "seq": seq, "step": 0, "verification": "", "deadline": now + ttl,
        }
    return {"handle": handle, "png_base64": image, "expires_in": ttl}


def _finish(handle: str, state: dict, ndus: str) -> Dict[str, object]:
    """TeraBox hands the session out once, so a failed check must not lose it."""
    state["ndus"] = ndus
    try:
        verify_ndus(state["origin"], ndus, state["session"].proxies)
    except TeraboxUnreachable:
        return {"status": "waiting_confirm"}
    except HosterParseError:
        with _qr_lock:
            _qr_sessions.pop(handle, None)
        raise
    with _qr_lock:
        _qr_sessions.pop(handle, None)
    return {"status": "done", "ndus": ndus}


def qr_poll(handle: str) -> Dict[str, object]:
    """``{"status": "waiting_scan" | "waiting_confirm" | "done", "ndus": ...}``."""
    with _qr_lock:
        state = _qr_sessions.get(handle)
    if state is None or time.monotonic() >= state["deadline"]:
        with _qr_lock:
            _qr_sessions.pop(handle, None)
        raise HosterParseError("TeraBox QR 코드가 만료되었습니다. QR 로그인을 다시 시작하세요")
    if state.get("ndus"):
        return _finish(handle, state, state["ndus"])
    state["seq"] = str(int(state["seq"]) + 1)
    values = {
        **state["form"], "uuid": state["uuid"], "seq": state["seq"],
        "step": str(state["step"]), "reg_source": "web", "first_referer": "",
        # A browser gets the session from Set-Cookie; the official PC client,
        # which is what a server-side session resembles, asks for it in the body.
        "need_extra": json.dumps(["ndus", "uid"]),
    }
    if state["verification"]:
        values["v"] = state["verification"]
    waiting = {"status": "waiting_confirm" if state["step"] else "waiting_scan"}
    try:
        response = state["session"].post(state["origin"] + "/passport/qrcode/login", data=values, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        print(f"[LOG] TeraBox QR 폴링 재시도: step={state['step']} {type(exc).__name__}")
        return waiting
    code, payload = _decode(response)
    print(f"[LOG] TeraBox QR 폴링: step={state['step']} code={code}")
    if code == 39:
        return waiting
    if code:
        _fail(code)
    data = _qr_data(payload)
    for source in (payload, data):
        for key in ("v", "vcode"):
            if source.get(key):
                state["verification"] = str(source[key])
    ndus = str(data.get("ndus") or "") or first_cookie(
        state["session"].cookies, "ndus", urlparse(state["origin"]).hostname
    )
    if ndus:
        prefix = data.get("region_domain_prefix") or data.get("url_domain_prefix")
        state["origin"] = regional_origin(state["origin"], str(prefix or ""))
        return _finish(handle, state, ndus)
    if state["step"]:
        raise HosterParseError("TeraBox 휴대폰 승인은 끝났지만 로그인 세션을 받지 못했습니다. QR 로그인을 다시 시도하세요")
    state["step"] = 1
    return {"status": "waiting_confirm"}
