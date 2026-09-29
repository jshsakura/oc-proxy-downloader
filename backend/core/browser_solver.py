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
import re
import string
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Dict, Optional
from urllib.parse import unquote, urlparse

from patchright.sync_api import Page, sync_playwright

from core.hoster_common import HosterParseError, _format_size_bytes


__all__ = [
    'BROWSER_FLOW_HOSTS',
    'BROWSER_REQUIRED_HOSTS',
    'BROWSER_UNSUPPORTED_MESSAGE',
    'BrowserFlow',
    'BrowserSolveResult',
    'flow_for_host',
    'is_browser_supported',
    'solve_download_page',
    'resolve_rootz_page',
]


VIEWPORT = {"width": 1280, "height": 1200}
PAGE_LOAD_TIMEOUT_MS = 60_000
CLICK_TIMEOUT_MS = 20_000
POLL_INTERVAL_MS = 1_000

READY_TEXT_TIMEOUT_S = 60
# Popunder ad scripts swallow the first click on the step-1 button, so the click
# is repeated until the captcha step actually appears. 3회 — 이미 열린 페이지
# 안의 클릭이라 호스터로 나가는 요청은 아니지만, 재시도는 어디서든 3회로 맞춘다.
SUBMIT_ATTEMPTS = 3
SUBMIT_SETTLE_MS = 4_000
# How long the step-1 button gets to show up before the flow gives up on it.
SUBMIT_TIMEOUT_S = 20
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
# How briefly a solve waits for its turn before handing the link back to the queue.
# Deliberately tiny: this call runs on the asyncio default executor, which the whole
# app shares, so a thread parked here is a thread the API cannot use. Waiting long
# also buys nothing — KIND_QUEUED reschedules without spending the retry budget, so
# coming back in a minute costs the link nothing and costs the backend nothing.
LOCK_WAIT_SEC = 3
# Starting a browser with less than this remaining only burns the slot: the host's
# own countdown alone is ~15s and the click rounds add ~50s more.
MIN_SOLVE_BUDGET_SEC = 90

# The host hands the file over by navigating the tab at its storage node. Chromium
# turns that into a download event only when the node actually answers; when the
# node is unreachable the navigation dies as a network error and the link — which
# the host DID issue — is lost. So navigations are watched too, and a file-looking
# one on the host's own domain counts as the answer. The app's downloader then
# either fetches it or fails with the node's real reason ("node unreachable"),
# which beats reporting "captcha passed but no link was issued".
_PAGE_EXTENSIONS = frozenset({
    "htm", "html", "php", "asp", "aspx", "jsp", "js", "css", "json", "xml",
})
_FILE_PATH_RE = re.compile(r"\.([A-Za-z0-9]{2,5})$")

TURNSTILE_CONTAINER = ".cf-turnstile"
# The checkbox sits this far in from the widget container's left edge, vertically centred.
CHECKBOX_OFFSET_X = 30
MIN_WIDGET_HEIGHT = 10

# The character set http.cookies accepts in a cookie name; anything else raises
# CookieError when aiohttp builds the jar for the download.
LEGAL_COOKIE_NAME_CHARS = frozenset(
    string.ascii_letters + string.digits + "!#$%&'*+-.^_`|~:"
)

# Captcha solving is gated on two axes.
#
# Per host: one solve at a time for a given site. A site is never hit
# concurrently, so its rate stays near one request per solve (~40-60s, the
# countdown dominates) and it has no reason to serve harder challenges. Two
# different sites do not queue behind each other.
#
# Across hosts: a ceiling on how many browsers exist at once, because each headful
# Chromium costs several hundred MB and parses run on a thread pool
# ("parse_concurrency", default 3) that would otherwise start one per link.
DEFAULT_MAX_CONCURRENT_BROWSERS = 2

_HOST_LOCKS: Dict[str, threading.Lock] = {}
_HOST_LOCKS_GUARD = threading.Lock()
_BROWSER_SLOTS = threading.BoundedSemaphore(DEFAULT_MAX_CONCURRENT_BROWSERS)


# Matched by the error classifier as KIND_QUEUED, which retries on a short delay
# without spending the retry budget a real failure needs.
QUEUE_WAIT_MESSAGE = "같은 사이트의 다른 링크를 처리하는 중이라 대기열에서 시간이 초과되었습니다"

# Classified by error_messages as a terminal, clearly-explained failure rather than
# something the user could fix by retrying.
BROWSER_UNSUPPORTED_MESSAGE = (
    "이 호스터는 브라우저 캡차 우회가 필요하며 Docker 버전에서만 지원됩니다 "
    "(standalone 빌드에는 브라우저가 포함되어 있지 않습니다)"
)


def _host_lock(host: str) -> threading.Lock:
    """The queue for one site, created on first use."""
    host = {"vik1ngfile.site": "vikingfile.com", "akirabox.to": "akirabox.com"}.get(host.removeprefix("www."), host.removeprefix("www."))
    with _HOST_LOCKS_GUARD:
        lock = _HOST_LOCKS.get(host)
        if lock is None:
            lock = threading.Lock()
            _HOST_LOCKS[host] = lock
        return lock

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
    direct_link_selector: Optional[str] = None
    widget_selector: str = TURNSTILE_CONTAINER
    token_required: bool = True


@dataclass(frozen=True)
class BrowserSolveResult:
    download_link: str
    cookies: Dict[str, str]
    user_agent: str
    page_html: str = ""


# The 2026-08 redesign dropped the "File Ready" pre-check banner: step 1 now
# renders its button straight away and merely keeps it disabled until the page is
# interactive. Waiting for text that never appears burnt a minute of the budget,
# so readiness is left to the click's own actionability wait.
DATANODES_FLOW = BrowserFlow(
    submit_selector='button[name="method_free"]',
    action_selector='button:has-text("Free Download"), button:has-text("Start Download")',
)
SEND_NOW_FLOW = BrowserFlow(
    # Send.now's current challenge page does not render a button.  After the
    # Turnstile token is issued it exposes a form submit input named
    # ``download_a``; pressing that POSTs the verification form and only then
    # opens the real file page.  Keep the ordinary selectors too because the
    # next page still uses a Download button/link.
    action_selector=(
        'input[type="submit"][name="download_a"], '
        'button:has-text("Download"), a:has-text("Download")'
    ),
)
MIXDROP_FLOW = BrowserFlow(
    # MixDrop runs reCAPTCHA v3 itself after the click and changes this anchor
    # into the final download link after a short countdown.
    action_selector="a.download-btn",
)
MIXDROP_DOMAINS = frozenset({"mixdrop.ag", "mixdrop.top", "mxdrop.top"})
VIKING_FLOW = BrowserFlow(
    direct_link_selector='a#download-link[href^="http"]',
    widget_selector="#captcha",
    token_required=False,
)
AKIRABOX_FLOW = BrowserFlow(direct_link_selector='a#download[href^="http"]')
DEFAULT_FLOW = BrowserFlow()

_FLOWS = {
    "datanodes.to": DATANODES_FLOW,
    "send.now": SEND_NOW_FLOW,
    "mixdrop.ag": MIXDROP_FLOW,
    "mixdrop.top": MIXDROP_FLOW,
    "mxdrop.top": MIXDROP_FLOW,
    "vikingfile.com": VIKING_FLOW,
    "vik1ngfile.site": VIKING_FLOW,
    "akirabox.com": AKIRABOX_FLOW,
    "akirabox.to": AKIRABOX_FLOW,
}

# Hosts that have a browser flow at all. Used to route their parses onto the
# dedicated pool in core.executors, so a minutes-long solve never occupies a
# shared worker.
BROWSER_FLOW_HOSTS = frozenset({*_FLOWS, "rootz.so"})

# The subset where the browser is unavoidable: every free download ends at a
# captcha, so a build without one can refuse the link immediately. Send.now is
# deliberately absent — it only shows a captcha sometimes, and FlareSolverr still
# resolves the rest, so gating it up front would break links that do work.
BROWSER_REQUIRED_HOSTS = frozenset({"datanodes.to", *MIXDROP_DOMAINS, "vikingfile.com", "vik1ngfile.site", "akirabox.com", "akirabox.to", "rootz.so"})


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


def _same_site(candidate_host: str, page_host: str) -> bool:
    """Whether both hosts sit under the same two-label domain.

    Storage nodes are subdomains of the host's own domain (``stor03.datanodes.to``),
    while the popunder ad networks are not — which is exactly the line that has to
    be drawn when deciding whether a navigation is the file or an ad.
    """
    def tail(host: str) -> str:
        return ".".join((host or "").lower().split(".")[-2:])

    return bool(candidate_host) and tail(candidate_host) == tail(page_host)


def _is_file_navigation(candidate: str, page_url: str) -> bool:
    """Whether this navigation is the host handing over the file itself.

    Narrow on purpose: a storage node on the host's own domain, under a hostname
    that is not the page's own. The host's site also links file-named pages
    (``datanodes.to/<code>/<name>.rar`` re-renders the download page), and taking
    one of those for the file would hand the downloader an HTML page to save.
    """
    parsed = urlparse(candidate or "")
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    page_host = (urlparse(page_url).hostname or "").lower()
    if host == page_host or not _same_site(host, page_host):
        return False
    match = _FILE_PATH_RE.search((parsed.path or "").rstrip("/"))
    return bool(match) and match.group(1).lower() not in _PAGE_EXTENSIONS


def _guard_hoster_navigation(route, page: Page, source_url: str,
                             captured: Optional[Dict[str, str]] = None) -> None:
    """Keep an external top-level redirect from replacing the download page.

    Some hosts open third-party ads during the free-download clicks. If one
    replaces the main tab, the old flow keeps clicking on that unrelated page
    and eventually reports a fictitious captcha success. Subframes, including
    Turnstile, must still load normally.
    """
    request = route.request
    try:
        main_navigation = request.is_navigation_request() and request.frame == page.main_frame
    except Exception:
        main_navigation = False
    target_host = (urlparse(request.url).hostname or "").lower()
    source_host = (urlparse(source_url).hostname or "").lower()
    current_host = (urlparse(page.url).hostname or "").lower()
    if (main_navigation and source_host in MIXDROP_DOMAINS
            and target_host.endswith(".mxcontent.net")
            and urlparse(request.url).path.startswith("/d/")):
        # MixDrop's free button goes straight to its delivery domain. Keep the
        # signed URL before Chromium attempts the large browser download.
        if captured is not None:
            captured.setdefault("url", request.url)
        route.fulfill(status=204, body="")
        return
    allowed_host = (
        _same_site(target_host, source_host)
        or _same_site(target_host, current_host)
        or (target_host in MIXDROP_DOMAINS and source_host in MIXDROP_DOMAINS)
    )
    if main_navigation and target_host and not allowed_host:
        print(f"[DEBUG] 호스터 외부 페이지 이동 억제: {target_host}")
        # A rejected top-level navigation turns Chromium's original tab into
        # chrome-error://. HTTP 204 cancels the navigation but keeps its page.
        route.fulfill(status=204, body="")
    else:
        route.continue_()


def _capture_download_response(response, page_url: str, captured: Dict[str, str]) -> None:
    """Read the host's final ``download2`` JSON response directly.

    DataNodes' Vue component obtains the storage URL with ``fetch`` and only
    afterwards assigns it to ``document.location``. Watching that later
    navigation alone is lossy: Chromium can reject an unreachable storage node
    before Playwright exposes a useful navigation/download event. The JSON is
    the authoritative hand-off and also carries the host's real error when it
    refuses to mint a link.
    """
    try:
        request = response.request
        headers = {str(k).lower(): str(v) for k, v in request.headers.items()}
        if request.method.upper() != "POST" or headers.get("x-dn-dl") != "1":
            return
        response_host = (urlparse(getattr(response, "url", "") or getattr(request, "url", "")).hostname or "").lower()
        page_host = (urlparse(page_url).hostname or "").lower()
        if response_host and not _same_site(response_host, page_host):
            return
        data = response.json()
        if not isinstance(data, dict):
            return
        candidate = unquote(str(data.get("url") or ""))
        parsed = urlparse(candidate)
        # The host's signed download2 response can point to a storage domain
        # outside datanodes.to. Unlike arbitrary page navigations, this JSON is
        # the host's own hand-off, so accept its absolute HTTP(S) link.
        page_path = (parsed.path or "").rstrip("/")
        if (parsed.scheme in {"http", "https"} and parsed.hostname
                and not parsed.username and not parsed.password
                and (parsed.hostname.lower() != page_host or page_path not in {"", "/download"})):
            captured.setdefault("url", candidate)
        error = str(data.get("error") or "").strip()
        if error:
            captured["error"] = error[:500]
    except Exception:
        # A non-JSON challenge page is handled by the page flow/retry loop. An
        # event listener must never abort the browser solve itself.
        return


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


@contextmanager
def _queued_browser_slot(host: str, deadline: "Deadline"):
    """Take this site's turn, then one of the shared browser slots.

    Both waits draw on the solve's own budget, and running out of either yields a
    "queued" error rather than a failure: the link goes back to the queue with its
    retry budget intact instead of being spent on standing in line.

    The site queue is taken first so that a link waiting for a busy browser pool
    still holds its site's turn — two links for one site can never overlap.
    """
    site_queue = _host_lock(host)
    if not site_queue.acquire(timeout=min(LOCK_WAIT_SEC, deadline.remaining())):
        raise HosterParseError(QUEUE_WAIT_MESSAGE)
    try:
        if deadline.remaining() < MIN_SOLVE_BUDGET_SEC:
            raise HosterParseError(QUEUE_WAIT_MESSAGE)
        slot_wait = max(1.0, deadline.remaining() - MIN_SOLVE_BUDGET_SEC)
        if not _BROWSER_SLOTS.acquire(timeout=slot_wait):
            raise HosterParseError(QUEUE_WAIT_MESSAGE)
        try:
            yield
        finally:
            _BROWSER_SLOTS.release()
    finally:
        site_queue.release()


def is_browser_supported() -> bool:
    """Whether this build can actually drive a browser.

    Turnstile never issues a token to a headless browser, so a real display is
    required. Only the Docker image provides one (Xvfb) and ships Chromium.
    """
    return bool(os.environ.get("DISPLAY"))


def _require_display() -> None:
    """Refuse anywhere the fallback cannot run, with a reason the user can act on.

    Without this the standalone build would crash deep inside Playwright with a
    missing-executable error, because the import that pulls Playwright in happens
    long before anything checks whether a browser exists.
    """
    if not is_browser_supported():
        raise HosterParseError(BROWSER_UNSUPPORTED_MESSAGE)


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
        try:
            value = probe()
        except Exception as exc:
            # The host navigates the tab when issuing a download. A locator
            # attached to the old document can briefly lose its JS context.
            # Retry the probe after navigation instead of failing the item.
            if not _is_navigation_race(exc):
                raise
            value = None
        if value:
            return value
        page.wait_for_timeout(POLL_INTERVAL_MS)
    return None


def _is_navigation_race(exc: Exception) -> bool:
    message = str(exc).lower()
    return "execution context was destroyed" in message and "navigation" in message


def _turnstile_box(page: Page, selector: str = TURNSTILE_CONTAINER) -> Optional[dict]:
    """Bounding box of the Turnstile widget once it has actually been laid out."""
    if not page.locator(selector).count():
        return None
    box = page.locator(selector).first.bounding_box()
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
        return _poll(page, lambda: _turnstile_box(page, flow.widget_selector), WIDGET_TIMEOUT_S, deadline)

    submit = page.locator(flow.submit_selector).first
    # The step-1 button is rendered by the page's own script, so it is not in the
    # DOM the instant the navigation settles.
    if not _poll(page, lambda: submit.count(), SUBMIT_TIMEOUT_S, deadline):
        return None

    for _ in range(SUBMIT_ATTEMPTS):
        deadline.check("1단계 버튼")
        try:
            present = bool(submit.count())
        except Exception as exc:
            if not _is_navigation_race(exc):
                raise
            page.wait_for_timeout(POLL_INTERVAL_MS)
            continue
        if not present:
            break
        # The button is disabled until the page finishes arming itself, so this
        # click waits for it. A wait that runs out is one lost attempt, not a
        # failed solve — falling out of here with a raw Playwright timeout would
        # reach the user as an unclassifiable error instead of a named one.
        try:
            submit.click(timeout=deadline.budget_ms(CLICK_TIMEOUT_MS))
        except Exception as exc:
            print(f"[DEBUG] 1단계 버튼 클릭 재시도: {type(exc).__name__}")
            continue
        page.wait_for_timeout(SUBMIT_SETTLE_MS)
        box = _poll(page, lambda: _turnstile_box(page, flow.widget_selector), WIDGET_TIMEOUT_S, deadline)
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
    click_timeouts = 0
    for _ in range(ACTION_ROUNDS):
        deadline.check("다운로드 시작 버튼")
        if captured.get("url"):
            return captured["url"]
        action = page.locator(flow.action_selector).first
        try:
            present = bool(action.count())
        except Exception as exc:
            if not _is_navigation_race(exc):
                raise
            page.wait_for_timeout(POLL_INTERVAL_MS)
            continue
        if present:
            # The button relabels itself through the countdown ("Free Download" →
            # "Ready in 4s" → "Start Download"), and a click landing on the frame
            # that re-renders it times out. That is one lost press, not a failed
            # solve — the next round presses the settled button.
            try:
                action.click(timeout=deadline.budget_ms(CLICK_TIMEOUT_MS))
                click_timeouts = 0
            except Exception as exc:
                print(f"[DEBUG] 다운로드 버튼 클릭 재시도: {type(exc).__name__}")
                click_timeouts += 1
                if click_timeouts >= 3:
                    raise HosterParseError(
                        "다운로드 버튼 처리 후 링크를 받지 못했습니다 (버튼 클릭 3회 연속 시간 초과)"
                    ) from exc
        page.wait_for_timeout(min(ACTION_ROUND_WAIT_MS, deadline.budget_ms(ACTION_ROUND_WAIT_MS)))
        if captured.get("url"):
            return captured["url"]
    detail = captured.get("error")
    suffix = f" (호스터 응답: {detail})" if detail else ""
    raise HosterParseError(
        f"다운로드 버튼 처리 후 링크를 받지 못했습니다{suffix}"
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

    Solves queue per site and are bounded by ``SOLVE_BUDGET_SEC``; see
    ``_host_lock`` and ``_BROWSER_SLOTS``.
    """
    _require_display()
    deadline = Deadline(SOLVE_BUDGET_SEC)
    proxy = _proxy_settings(proxies)
    captured: Dict[str, str] = {}

    def on_download(download) -> None:
        captured.setdefault("url", download.url)
        # Only the URL is wanted; the real transfer is done by the app's downloader.
        download.cancel()

    def on_request(request) -> None:
        if request.is_navigation_request() and _is_file_navigation(request.url, page.url or url):
            captured.setdefault("url", request.url)

    def on_response(response) -> None:
        _capture_download_response(response, url, captured)

    host = (urlparse(url).hostname or "").lower()
    with _queued_browser_slot(host, deadline):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            try:
                context = browser.new_context(
                    viewport=VIEWPORT,
                    accept_downloads=True,
                    proxy=proxy,
                )
                page = context.new_page()
                page.route(
                    "**/*",
                    lambda route: _guard_hoster_navigation(route, page, url, captured),
                )
                page.on("download", on_download)
                page.on("request", on_request)
                page.on("response", on_response)

                page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=deadline.budget_ms(PAGE_LOAD_TIMEOUT_MS),
                )
                _await_page_ready(page, flow, deadline)

                def direct_link() -> Optional[str]:
                    if not flow.direct_link_selector:
                        return None
                    anchor = page.locator(flow.direct_link_selector).first
                    return anchor.get_attribute("href") if anchor.count() else None

                link = direct_link()
                if link:
                    return BrowserSolveResult(link, _usable_cookies(context.cookies(), url), str(page.evaluate(USER_AGENT_JS)), page.content())

                box = _reach_captcha(page, flow, deadline)
                if box:
                    if flow.token_required:
                        _solve_turnstile(page, box, deadline)
                    else:
                        page.mouse.click(box["x"] + CHECKBOX_OFFSET_X, box["y"] + box["height"] / 2)

                if flow.direct_link_selector:
                    link = _poll(page, direct_link, TOKEN_TIMEOUT_S, deadline)
                    if not link:
                        raise HosterParseError("다운로드 주소가 발급되지 않았습니다 (캡차 또는 호스트 제한)")
                    return BrowserSolveResult(link, _usable_cookies(context.cookies(), url), str(page.evaluate(USER_AGENT_JS)), page.content())

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


def resolve_rootz_page(url: str, proxies: Optional[Dict[str, str]] = None) -> tuple[str, Dict[str, str], str]:
    """Read Rootz metadata and resolve its proxy endpoint without fetching file bytes."""
    _require_display()
    parsed = urlparse(url)
    short_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", short_id):
        raise HosterParseError("Rootz 링크 형식이 올바르지 않습니다")
    deadline = Deadline(SOLVE_BUDGET_SEC)
    with _queued_browser_slot("rootz.so", deadline):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            try:
                context = browser.new_context(viewport=VIEWPORT, proxy=_proxy_settings(proxies))
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=deadline.budget_ms(PAGE_LOAD_TIMEOUT_MS))
                # Rootz sets its page token during hydration; querying the API
                # before that finishes returns 403 even for a public file.
                page.wait_for_timeout(4000)
                result = page.evaluate("""async (id) => {
                    const metaResponse = await fetch(`/api/files/download-by-short?shortId=${encodeURIComponent(id)}`);
                    const meta = await metaResponse.json();
                    if (!meta.success || !meta.data) return {error: meta.error || '파일 정보 조회 실패'};
                    const file = meta.data;
                    if (file.status !== 'active') return {error: '파일이 비활성 상태입니다'};
                    if (file.passwordProtected) return {error: '비밀번호가 필요한 파일입니다'};
                    if (!file.downloadAllowed || file.cooldownRemaining > 0 || file.waitSeconds > 0)
                        return {error: '무료 다운로드 대기 또는 제한 중입니다'};
                    const response = await fetch(`/api/files/proxy-download/${encodeURIComponent(id)}`, {method: 'HEAD'});
                    const type = response.headers.get('content-type') || '';
                    if (!response.ok || type.includes('text/html') || type.includes('application/json'))
                        return {error: `다운로드 주소 확인 실패 (${response.status})`};
                    return {url: response.url, name: file.fileName, size: file.size};
                }""", short_id)
                if result.get("error"):
                    raise HosterParseError(f"Rootz: {result['error']}")
                direct = str(result.get("url") or "")
                if not direct.startswith(("https://", "http://")) or _same_site(urlparse(direct).hostname or "", "rootz.so"):
                    raise HosterParseError("Rootz: 직접 다운로드 주소를 받지 못했습니다")
                return direct, {"name": str(result.get("name") or ""), "size": _format_size_bytes(result.get("size") or 0)}, str(page.evaluate(USER_AGENT_JS))
            finally:
                browser.close()
