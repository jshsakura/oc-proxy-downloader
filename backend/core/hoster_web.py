"""Guest website flows, using the site's current scripts and browser session."""

import hashlib
import json
from urllib.parse import urlparse

from core.hoster_common import HosterParseError, _raise_for_dead_page


def is_gofile_storage_url(url):
    p = urlparse(url or "")
    return (p.scheme == "https" and not p.username and not p.password
            and (p.hostname or "").endswith(".gofile.io")
            and p.path.startswith("/download/"))


def resolve_gofile_website(url, content_id):
    """Observe one normal page visit; never synthesize website/API tokens.

    The website creates its own guest session and requests its own contents.
    A matching response publishes the file address. No paid API credentials,
    redundant metadata request or file GET is performed here.
    """
    from core import browser_solver as browser
    browser._require_display()
    deadline = browser.Deadline(120)
    with browser._queued_browser_slot("gofile.io", deadline), browser.sync_playwright() as pw:
        instance = pw.chromium.launch(headless=False)
        page = None
        try:
            context = instance.new_context(viewport=browser.VIEWPORT)
            page = context.new_page()
            replies = []

            def observe(response):
                p = urlparse(response.url)
                if p.hostname == "api.gofile.io" and p.path == f"/contents/{content_id}":
                    try:
                        replies.append((response.status, response.json()))
                    except Exception:
                        replies.append((response.status, {}))

            page.on("response", observe)
            response = page.goto(url, wait_until="domcontentloaded", timeout=deadline.budget_ms(60000))
            if response and response.status >= 400:
                raise HosterParseError(f"GoFile 공유 페이지 HTTP {response.status} (원본 보존)")
            while not replies and deadline.remaining() > 0:
                page.wait_for_timeout(deadline.budget_ms(500))
            if not replies:
                _raise_for_dead_page("GoFile", page.content(), 200)
                raise HosterParseError("GoFile 웹 페이지가 파일 목록을 제공하지 않았습니다; 자동 반복 없음")
            status, payload = replies[0]
            if status == 429 or payload.get("status") == "error-rateLimit":
                raise HosterParseError("GoFile 무료 조회 속도 제한 — 자동 재시도하지 않습니다")
            if status in {404, 410} or payload.get("status") in {"error-notFound", "error-notExist"}:
                raise HosterParseError("GoFile 파일 상태 확인 실패 (삭제 여부 미확인)")
            if payload.get("status") == "error-notPremium":
                raise HosterParseError("GoFile 웹 경로에서 프리미엄 권한을 요구했습니다; 무료 다운로드 진행 불가")
            if status != 200 or payload.get("status") != "ok":
                raise HosterParseError(f"GoFile 웹 파일 목록 응답 실패 HTTP {status}; 자동 반복 없음")
            data = payload.get("data") or {}
            if data.get("canAccess") is False:
                raise HosterParseError("GoFile 웹 경로에서 파일 접근 권한을 요구했습니다; 무료 다운로드 진행 불가")
            return {"data": data, "cookies": {c["name"]: c["value"] for c in context.cookies()},
                    "user_agent": page.evaluate("navigator.userAgent"), "referer": page.url}
        finally:
            if page is not None:
                # Already received markup only: never re-open a page for evidence.
                try:
                    key = hashlib.sha256(url.encode()).hexdigest()[:16]
                    path = browser.CONFIG_DIR / f"gofile_{key}.html"
                    path.write_text(page.content()); path.chmod(0o600)
                    meta = browser.CONFIG_DIR / f"gofile_{key}.json"
                    meta.write_text(json.dumps({"source_sha256": hashlib.sha256(url.encode()).hexdigest(),
                                               "deletion_confirmed": False})); meta.chmod(0o600)
                except Exception:
                    pass
            instance.close()
