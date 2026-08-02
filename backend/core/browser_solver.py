# -*- coding: utf-8 -*-
"""Headful-browser fallback for hosters guarded by an in-page Turnstile widget.

cloudscraper and FlareSolverr both clear Cloudflare's interstitial challenge, but
neither can solve a Cloudflare Turnstile widget embedded *inside* a host's own
download page. This module drives a patched Chromium through that page and hands
back the direct link the browser was about to fetch.

Headless mode does not work: Turnstile silently withholds the token no matter how
long it is polled. The browser therefore runs headful against an X display, which
the container provides through Xvfb.
"""

from __future__ import annotations

import os
import string
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional
from urllib.parse import urlparse

from patchright.sync_api import Page, sync_playwright

from core.hoster_common import HosterParseError


__all__ = [
    'BrowserFlow',
    'BrowserSolveResult',
    'flow_for_host',
    'solve_download_page',
]


VIEWPORT = {"width": 1280, "height": 1200}
PAGE_LOAD_TIMEOUT_MS = 60_000
CLICK_TIMEOUT_MS = 20_000
POLL_INTERVAL_MS = 1_000

READY_TEXT_TIMEOUT_S = 60
# Popunder ad scripts swallow the first click on the step-1 button, so the click
# is repeated until the captcha step actually appears.
SUBMIT_ATTEMPTS = 4
SUBMIT_SETTLE_MS = 4_000
WIDGET_TIMEOUT_S = 15
TOKEN_TIMEOUT_S = 60
# The countdown button needs more than one press: the first arms the host's timer,
# a later one fires the request that yields the file URL.
ACTION_ROUNDS = 8
ACTION_ROUND_WAIT_MS = 6_000

# Wall-clock budget for one solve, deliberately under download_core's 300s
# SPECIAL_HOSTER_PARSE_TIMEOUT_SEC. That outer cap runs on asyncio.wait_for, which
# abandons the await but cannot stop this thread — so without a budget of its own a
# slow solve would keep holding _SOLVE_LOCK after its download was already failed,
# and every queued link behind it would stall. The step timeouts below can sum past
# this; the deadline is what actually bounds the run.
SOLVE_BUDGET_SEC = 270
# Longest a queued solve waits for the lock. What is left afterwards still has to be
# enough to finish, hence the floor below.
LOCK_WAIT_SEC = 150
# Starting a browser with less than this remaining only burns the slot: the host's
# own countdown alone is ~15s and the click rounds add ~50s more.
MIN_SOLVE_BUDGET_SEC = 90

TURNSTILE_CONTAINER = ".cf-turnstile"
# The checkbox sits this far in from the widget container's left edge, vertically centred.
CHECKBOX_OFFSET_X = 30
MIN_WIDGET_HEIGHT = 10

# The character set http.cookies accepts in a cookie name; anything else raises
# CookieError when aiohttp builds the jar for the download.
LEGAL_COOKIE_NAME_CHARS = frozenset(
    string.ascii_letters + string.digits + "!#$%&'*+-.^_`|~:"
)

# One browser at a time, process-wide. Parses run on a thread pool sized by
# "parse_concurrency" (default 3), so bulk-adding links would otherwise start that
# many headful Chromium instances at once — several hundred MB of RAM each on a
# NAS, and a burst of near-simultaneous hits that pushes the host into serving
# harder challenges. Downloads stay parallel; only the captcha step is serialised.
# Each solve already spans the host's countdown (~40-60s), so this also keeps the
# request rate to roughly one per minute without an artificial sleep.
_SOLVE_LOCK = threading.Lock()

TOKEN_JS = (
    "() => {const e = document.querySelector('[name=\"cf-turnstile-response\"]');"
    " return e ? e.value : '';}"
)
USER_AGENT_JS = "() => navigator.userAgent"


@dataclass(frozen=True)
class BrowserFlow:
    """The click path through one host's captcha-guarded download page.

    ready_text       text that marks the page as interactive (host pre-check animation)
    submit_selector  step-1 button that reveals the captcha, retried on popunder theft
    action_selector  the countdown / start button, pressed until the download begins
    """

    ready_text: Optional[str] = None
    submit_selector: Optional[str] = None
    action_selector: str = 'button:has-text("Download"), button:has-text("Start")'


@dataclass(frozen=True)
class BrowserSolveResult:
    download_link: str
    cookies: Dict[str, str]
    user_agent: str


DATANODES_FLOW = BrowserFlow(
    ready_text="File Ready",
    submit_selector='button[name="method_free"]',
    action_selector='button:has-text("Free Download"), button:has-text("Start Download")',
)
SEND_NOW_FLOW = BrowserFlow(
    action_selector='button:has-text("Download"), a:has-text("Download")',
)
DEFAULT_FLOW = BrowserFlow()

_FLOWS = {
    "datanodes.to": DATANODES_FLOW,
    "send.now": SEND_NOW_FLOW,
}


def flow_for_host(host: str) -> BrowserFlow:
    """The flow registered for this host, or a generic click-the-download-button one."""
    normalised = (host or "").lower().removeprefix("www.")
    return _FLOWS.get(normalised, DEFAULT_FLOW)


def _usable_cookies(raw_cookies, url: str) -> Dict[str, str]:
    """Keep only the cookies the file server could plausibly want.

    The page loads popunder ad networks, which drop their own cookies into the
    same browser context. Those are useless to the download and dangerous to
    forward: a name that ``http.cookies`` rejects — an empty one in particular —
    makes aiohttp raise ``Illegal key ''`` the moment the transfer starts. So the
    set is narrowed to the host's own cookies with names that are legal to send.
    """
    host = (urlparse(url).hostname or "").lower()
    usable: Dict[str, str] = {}
    for cookie in raw_cookies:
        name = cookie.get("name") or ""
        domain = (cookie.get("domain") or "").lstrip(".").lower()
        if not name or not domain:
            continue
        if not set(name) <= LEGAL_COOKIE_NAME_CHARS:
            continue
        if host == domain or host.endswith(f".{domain}"):
            usable[name] = cookie.get("value") or ""
    return usable


def _proxy_settings(proxies: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Translate a requests-style proxy mapping into Playwright's proxy option.

    Credentials embedded in the URL (``http://user:pass@host:port``) have to be
    split out, because Chromium ignores userinfo in a --proxy-server value.
    """
    if not proxies:
        return None
    raw = proxies.get("https") or proxies.get("http")
    if not raw:
        return None

    parsed = urlparse(raw)
    if not parsed.hostname:
        return None

    port = f":{parsed.port}" if parsed.port else ""
    settings = {"server": f"{parsed.scheme or 'http'}://{parsed.hostname}{port}"}
    if parsed.username:
        settings["username"] = parsed.username
    if parsed.password:
        settings["password"] = parsed.password
    return settings


def _require_display() -> None:
    """Refuse early anywhere the fallback cannot actually run.

    Turnstile never issues a token to a headless browser, so a real display is
    mandatory. Only the Docker image provides one (Xvfb) and ships Chromium; the
    standalone builds bundle neither, so they must fail with a reason the user can
    act on instead of a missing-executable crash from deep inside Playwright.
    """
    if not os.environ.get("DISPLAY"):
        raise HosterParseError(
            "이 호스터는 브라우저 캡차 우회가 필요하며 Docker 버전에서만 지원됩니다 "
            "(standalone 빌드에는 브라우저가 포함되어 있지 않습니다)"
        )


class Deadline:
    """A shared wall-clock budget for one solve.

    Every wait in the flow is drawn from the same pot, so a page that is slow in
    several places cannot add its step timeouts together and outlive the run.
    """

    def __init__(self, budget_seconds: float) -> None:
        self._expires_at = time.monotonic() + budget_seconds

    def remaining(self) -> float:
        return max(0.0, self._expires_at - time.monotonic())

    def expired(self) -> bool:
        return self.remaining() <= 0

    def check(self, stage: str) -> None:
        if self.expired():
            raise HosterParseError(
                f"브라우저 캡차 우회 제한시간({SOLVE_BUDGET_SEC}초)을 초과했습니다 (중단 지점: {stage})"
            )

    def budget_ms(self, wanted_ms: int) -> int:
        """``wanted_ms`` clipped to what is left, so no single call outlives the budget."""
        return max(1, int(min(wanted_ms, self.remaining() * 1000)))


def _poll(page: Page, probe: Callable[[], object], seconds: int, deadline: Deadline):
    """Call probe once a second until it returns something truthy or time runs out."""
    for _ in range(seconds):
        if deadline.expired():
            return None
        value = probe()
        if value:
            return value
        page.wait_for_timeout(POLL_INTERVAL_MS)
    return None


def _turnstile_box(page: Page) -> Optional[dict]:
    """Bounding box of the Turnstile widget once it has actually been laid out."""
    if not page.locator(TURNSTILE_CONTAINER).count():
        return None
    box = page.locator(TURNSTILE_CONTAINER).first.bounding_box()
    if box and box["height"] > MIN_WIDGET_HEIGHT:
        return box
    return None


def _await_page_ready(page: Page, flow: BrowserFlow, deadline: Deadline) -> None:
    """Wait out the host's pre-check animation; clicking through it is ignored."""
    if not flow.ready_text:
        return
    _poll(page, lambda: page.locator(f"text={flow.ready_text}").count(),
          READY_TEXT_TIMEOUT_S, deadline)
    page.wait_for_timeout(SUBMIT_SETTLE_MS // 2)


def _reach_captcha(page: Page, flow: BrowserFlow, deadline: Deadline) -> Optional[dict]:
    """Advance to the captcha step, re-clicking when a popunder eats the click."""
    if not flow.submit_selector:
        return _poll(page, lambda: _turnstile_box(page), WIDGET_TIMEOUT_S, deadline)

    for _ in range(SUBMIT_ATTEMPTS):
        deadline.check("1단계 버튼")
        submit = page.locator(flow.submit_selector).first
        if not submit.count():
            break
        submit.click(timeout=deadline.budget_ms(CLICK_TIMEOUT_MS))
        page.wait_for_timeout(SUBMIT_SETTLE_MS)
        box = _poll(page, lambda: _turnstile_box(page), WIDGET_TIMEOUT_S, deadline)
        if box:
            return box
    return None


def _solve_turnstile(page: Page, box: dict, deadline: Deadline) -> str:
    """Tick the Turnstile checkbox and wait for the token to be written back."""
    page.mouse.click(box["x"] + CHECKBOX_OFFSET_X, box["y"] + box["height"] / 2)
    token = _poll(page, lambda: page.evaluate(TOKEN_JS), TOKEN_TIMEOUT_S, deadline)
    if not token:
        deadline.check("Turnstile 토큰 대기")
        raise HosterParseError(
            "Turnstile 캡차를 통과하지 못했습니다 (토큰 미발급)"
        )
    return str(token)


def _drive_to_download(
    page: Page,
    flow: BrowserFlow,
    captured: Dict[str, str],
    deadline: Deadline,
) -> str:
    """Press the action button until the browser starts fetching the file."""
    for _ in range(ACTION_ROUNDS):
        deadline.check("다운로드 시작 버튼")
        action = page.locator(flow.action_selector).first
        if action.count():
            action.click(timeout=deadline.budget_ms(CLICK_TIMEOUT_MS))
        page.wait_for_timeout(min(ACTION_ROUND_WAIT_MS, deadline.budget_ms(ACTION_ROUND_WAIT_MS)))
        if captured.get("url"):
            return captured["url"]
    raise HosterParseError(
        "캡차는 통과했지만 다운로드 링크가 발급되지 않았습니다"
    )


def solve_download_page(
    url: str,
    flow: BrowserFlow,
    proxies: Optional[Dict[str, str]] = None,
) -> BrowserSolveResult:
    """Walk a Turnstile-guarded download page and return the direct file link.

    The link is read from the download the browser itself kicks off, which is the
    only place the host exposes it — the page never renders it as an anchor.

    ``proxies`` routes the browser through the same proxy the rest of the parse
    uses, so the captcha is solved from the address that will fetch the file.

    Solves are serialised process-wide and bounded by ``SOLVE_BUDGET_SEC``; see
    ``_SOLVE_LOCK``.
    """
    _require_display()
    deadline = Deadline(SOLVE_BUDGET_SEC)
    proxy = _proxy_settings(proxies)
    captured: Dict[str, str] = {}

    def on_download(download) -> None:
        captured.setdefault("url", download.url)
        # Only the URL is wanted; the real transfer is done by the app's downloader.
        download.cancel()

    if not _SOLVE_LOCK.acquire(timeout=LOCK_WAIT_SEC):
        raise HosterParseError(
            "다른 링크의 캡차를 처리 중이라 대기열에서 시간이 초과되었습니다"
        )
    try:
        # Waiting for the lock spends the same budget, so a solve that could no
        # longer finish is dropped here instead of occupying the slot to no end.
        if deadline.remaining() < MIN_SOLVE_BUDGET_SEC:
            raise HosterParseError(
                "다른 링크의 캡차를 처리 중이라 대기열에서 시간이 초과되었습니다"
            )
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            try:
                context = browser.new_context(
                    viewport=VIEWPORT,
                    accept_downloads=True,
                    proxy=proxy,
                )
                page = context.new_page()
                page.on("download", on_download)

                page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=deadline.budget_ms(PAGE_LOAD_TIMEOUT_MS),
                )
                _await_page_ready(page, flow, deadline)

                box = _reach_captcha(page, flow, deadline)
                if box:
                    _solve_turnstile(page, box, deadline)

                link = _drive_to_download(page, flow, captured, deadline)
                cookies = _usable_cookies(context.cookies(), url)
                user_agent = str(page.evaluate(USER_AGENT_JS))
                return BrowserSolveResult(
                    download_link=link,
                    cookies=cookies,
                    user_agent=user_agent,
                )
            finally:
                browser.close()
    finally:
        _SOLVE_LOCK.release()
