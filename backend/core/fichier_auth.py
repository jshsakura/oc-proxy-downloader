# -*- coding: utf-8 -*-
"""1fichier account login — issues an authenticated cloudscraper session.

Logging in with a free 1fichier account lets you bypass guest-slot shortage
cases such as ``Free download is temporarily limited due to high demand``
(registered-user slots are guaranteed separately).

Design:
- Cache a single authenticated ``cloudscraper`` instance at module scope.
- Automatically re-login when session expiry is suspected.
- ``parse_1fichier_simple_sync`` takes this scraper's cookies and applies them to
  its own scraper for use.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

import cloudscraper


_LOGIN_URL = "https://1fichier.com/login.pl"
_HOME_URL = "https://1fichier.com/"
# Console page redirected to after a successful login — used for session verification
_CONSOLE_URL = "https://1fichier.com/console/index.pl"

# Session cache expiry (seconds). 1fichier's lt=on token is long-lived, but refresh every hour to be safe.
_SESSION_TTL_SECONDS = 60 * 60


@dataclass
class _Cached:
    scraper: cloudscraper.CloudScraper
    email: str
    obtained_at: float


_lock = threading.Lock()
_cache: Optional[_Cached] = None


class FichierLoginError(Exception):
    """1fichier login failure (credential error, block, network, etc.)."""


def _new_scraper() -> cloudscraper.CloudScraper:
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )


def _looks_logged_in(text: str) -> bool:
    """Consider it logged in if the ``console`` menu is visible or a logout link is present."""
    if not text:
        return False
    lowered = text.lower()
    return (
        "/console/" in lowered
        or "logout" in lowered
        or "déconnexion" in lowered
        or "logoff" in lowered
    )


def _do_login(email: str, password: str) -> cloudscraper.CloudScraper:
    """The actual login flow — returns a scraper with a live session on success, raises on failure."""
    if not email or not password:
        raise FichierLoginError("자격증명이 비어있음")

    scraper = _new_scraper()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Origin": "https://1fichier.com",
        "Referer": _LOGIN_URL,
    }

    # 1) GET the login page to initialize cookies / obtain the Cloudflare-bypass token
    try:
        r0 = scraper.get(_LOGIN_URL, headers=headers, timeout=(10, 30))
    except Exception as exc:
        raise FichierLoginError(f"로그인 페이지 접근 실패: {exc}") from exc

    if r0.status_code != 200:
        raise FichierLoginError(f"로그인 페이지 응답 코드 {r0.status_code}")

    # 2) POST the credentials. 1fichier's standard field names: mail / pass / lt / purge / Login
    form = {
        "mail": email,
        "pass": password,
        "lt": "on",        # long-term: keep the cookie alive for a long time
        "purge": "on",     # terminate all other sessions
        "Login": "Sign in",
    }
    try:
        r = scraper.post(
            _LOGIN_URL,
            data=form,
            headers=headers,
            timeout=(15, 45),
            allow_redirects=True,
        )
    except Exception as exc:
        raise FichierLoginError(f"로그인 요청 실패: {exc}") from exc

    # 3) Obvious failure cases
    text_lower = (r.text or "").lower()
    if "invalid" in text_lower and ("email" in text_lower or "password" in text_lower):
        raise FichierLoginError("이메일 또는 비밀번호가 올바르지 않음")
    if "captcha" in text_lower and "recaptcha" not in text_lower:
        raise FichierLoginError("1fichier 가 캡차를 요구함 — 브라우저로 한 번 로그인 후 재시도")

    # 4) Verify via the console page
    try:
        rc = scraper.get(_CONSOLE_URL, headers=headers, timeout=(10, 30))
    except Exception as exc:
        raise FichierLoginError(f"세션 검증 실패: {exc}") from exc

    if rc.status_code != 200 or not _looks_logged_in(rc.text):
        raise FichierLoginError("로그인 후 콘솔 페이지를 받지 못함 (자격증명 또는 차단)")

    return scraper


def get_authenticated_scraper(
    email: str,
    password: str,
    force_refresh: bool = False,
) -> cloudscraper.CloudScraper:
    """Return the cached session if present; otherwise log in anew if absent/expired/account changed."""
    global _cache

    with _lock:
        if (
            not force_refresh
            and _cache is not None
            and _cache.email == email
            and (time.time() - _cache.obtained_at) < _SESSION_TTL_SECONDS
        ):
            return _cache.scraper

        # New login
        scraper = _do_login(email, password)
        _cache = _Cached(scraper=scraper, email=email, obtained_at=time.time())
        return scraper


def get_session_cookies(email: str, password: str) -> Dict[str, str]:
    """Return cookies as a ``{name: value}`` dict that the parser/downloader can use."""
    scraper = get_authenticated_scraper(email, password)
    try:
        return {c.name: c.value for c in scraper.cookies}
    except Exception:
        return {}


def clear_cached_session() -> None:
    """Call when the ID/PW has changed or after a forced logout."""
    global _cache
    with _lock:
        _cache = None


def test_login(email: str, password: str) -> bool:
    """For the ``Test login`` button on the settings screen. Returns only success/failure as a boolean."""
    try:
        get_authenticated_scraper(email, password, force_refresh=True)
        return True
    except FichierLoginError:
        return False
