# -*- coding: utf-8 -*-
"""1fichier 계정 로그인 — 인증된 cloudscraper 세션 발급.

1fichier 무료 계정으로 로그인하면 ``Free download is temporarily limited
due to high demand`` 같은 게스트 슬롯 부족 케이스를 우회할 수 있다
(등록 사용자 슬롯이 별도로 보장되어 있음).

설계:
- 모듈 전역에 인증된 ``cloudscraper`` 인스턴스 하나를 캐시.
- 세션 만료가 의심되면 자동 재로그인.
- ``parse_1fichier_simple_sync`` 가 이 scraper 의 cookies 를 가져다
  자기 scraper 에 적용해서 사용.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional

import cloudscraper


_LOGIN_URL = "https://1fichier.com/login.pl"
_HOME_URL = "https://1fichier.com/"
# 로그인 성공 후 redirect 되는 콘솔 페이지 — 세션 검증용
_CONSOLE_URL = "https://1fichier.com/console/index.pl"

# 세션 캐시 만료 (초). 1fichier 의 lt=on 토큰 수명은 길지만 안전하게 1시간마다 갱신.
_SESSION_TTL_SECONDS = 60 * 60


@dataclass
class _Cached:
    scraper: cloudscraper.CloudScraper
    email: str
    obtained_at: float


_lock = threading.Lock()
_cache: Optional[_Cached] = None


class FichierLoginError(Exception):
    """1fichier 로그인 실패 (자격증명 오류, 차단, 네트워크 등)."""


def _new_scraper() -> cloudscraper.CloudScraper:
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )


def _looks_logged_in(text: str) -> bool:
    """``console`` 메뉴가 보이거나 logout 링크가 있으면 로그인된 상태로 간주."""
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
    """실제 로그인 흐름 — 성공 시 세션이 살아있는 scraper 반환, 실패 시 raise."""
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

    # 1) 로그인 페이지 GET 으로 cookie 초기화 / Cloudflare 우회 토큰 확보
    try:
        r0 = scraper.get(_LOGIN_URL, headers=headers, timeout=(10, 30))
    except Exception as exc:
        raise FichierLoginError(f"로그인 페이지 접근 실패: {exc}") from exc

    if r0.status_code != 200:
        raise FichierLoginError(f"로그인 페이지 응답 코드 {r0.status_code}")

    # 2) 자격증명 POST. 1fichier 의 표준 필드명: mail / pass / lt / purge / Login
    form = {
        "mail": email,
        "pass": password,
        "lt": "on",        # long-term: 쿠키를 길게 유지
        "purge": "on",     # 다른 세션 모두 종료
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

    # 3) 명백한 실패 케이스
    text_lower = (r.text or "").lower()
    if "invalid" in text_lower and ("email" in text_lower or "password" in text_lower):
        raise FichierLoginError("이메일 또는 비밀번호가 올바르지 않음")
    if "captcha" in text_lower and "recaptcha" not in text_lower:
        raise FichierLoginError("1fichier 가 캡차를 요구함 — 브라우저로 한 번 로그인 후 재시도")

    # 4) 콘솔 페이지로 검증
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
    """캐시된 세션이 있으면 반환, 없거나 만료/계정 변경됐으면 새로 로그인."""
    global _cache

    with _lock:
        if (
            not force_refresh
            and _cache is not None
            and _cache.email == email
            and (time.time() - _cache.obtained_at) < _SESSION_TTL_SECONDS
        ):
            return _cache.scraper

        # 새 로그인
        scraper = _do_login(email, password)
        _cache = _Cached(scraper=scraper, email=email, obtained_at=time.time())
        return scraper


def get_session_cookies(email: str, password: str) -> Dict[str, str]:
    """파서/다운로더가 쓸 수 있는 ``{name: value}`` dict 형태의 쿠키 반환."""
    scraper = get_authenticated_scraper(email, password)
    try:
        return {c.name: c.value for c in scraper.cookies}
    except Exception:
        return {}


def clear_cached_session() -> None:
    """ID/PW 가 바뀌었거나 강제 로그아웃 후 호출."""
    global _cache
    with _lock:
        _cache = None


def test_login(email: str, password: str) -> bool:
    """설정 화면에서 ``테스트 로그인`` 버튼 용. 성공/실패만 boolean 으로."""
    try:
        get_authenticated_scraper(email, password, force_refresh=True)
        return True
    except FichierLoginError:
        return False
