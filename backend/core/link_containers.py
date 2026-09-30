"""Resolve intermediate pages to one host URL without downloading their HTML.

Only published links or the page's own navigation are used. Human challenges,
login and an empty container are outcomes of a real page visit, not a blacklist.
"""

import re
import json
import hashlib
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from patchright.sync_api import Error as BrowserError

from core import browser_solver as browser
from core.hoster_common import HosterParseError
from core.host_policy import canonical_host
from core.config import CONFIG_DIR


CONTAINER_HOSTS = frozenset({
    "filecrypt.cc", "filecrypt.co", "filecrypt.to", "linkcuy.com", "momerybox.com",
    "ouo.io", "ouo.press", "multiup.io",
})
FILECRYPT_HOSTS = frozenset({"filecrypt.cc", "filecrypt.co", "filecrypt.to"})
TERABOX_HOSTS = frozenset({"1024terabox.com", "terabox.app", "terabox.com"})
OUO_HOSTS = frozenset({"ouo.io", "ouo.press"})
DESTINATION_HOSTS = frozenset({
    "1fichier.com", "mega.nz", "multiup.io", "mixdrop.ag", "megaup.net",
    "datanodes.to", "gofile.io", "send.now", "mediafire.com", "pixeldrain.com",
    "bunkr.si", "vikingfile.com", "akirabox.com", "rootz.so", "datavaults.co",
    "rapidgator.net",
    "filekeeper.net", "send.cm", "uptobox.com", "clicknupload.to", "filerio.in",
    "frdl.my", "letsupload.io", "bowfile.com", "doodrive.com", "solidfiles.com",
    "bayfiles.com", "qiwi.gg", "zippyshare.com", "teraboxapp.com",
})


def is_container_url(url):
    return (urlparse(url or "").hostname or "").lower().removeprefix("www.") in CONTAINER_HOSTS


def admission_url(req):
    """After unwrap, admit by the actual mirror while keeping its provenance."""
    original = getattr(req, "original_url", None)
    current = getattr(req, "url", "")
    if is_container_url(original) or (
        supported_destination(current) and original
        and canonical_host(urlparse(current).hostname) != canonical_host(urlparse(original).hostname)
    ):
        return current
    return original or current


def supported_destination(url):
    parsed = urlparse(url or "")
    return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
            and not parsed.username and not parsed.password
            and canonical_host(parsed.hostname) in DESTINATION_HOSTS)


def is_terabox_host(host):
    host = (host or "").lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in TERABOX_HOSTS)


def inspect_terabox_download(page, deadline, captured):
    """Test the published action once; a header login link is not a refusal."""
    button = page.locator(".download-btn:visible").first
    try:
        button.wait_for(state="visible", timeout=deadline.budget_ms(15000))
    except Exception as exc:
        raise HosterParseError("링크 컨테이너의 TeraBox 다운로드 버튼을 확인하지 못했습니다 (권한 미확인)") from exc
    button.click(timeout=deadline.budget_ms(15000))
    # This selector was observed after Download in the real Part3 session.
    # Do not inspect the header's Login link or any hidden dialog template.
    login = page.locator(".login-dialog:visible")
    until = min(deadline.remaining(), 15)
    expires = time.monotonic() + until
    while deadline.remaining() > 0 and time.monotonic() < expires:
        if captured:
            return choose_container_link(list(dict.fromkeys(captured)))
        if login.count():
            raise HosterParseError("TeraBox 공유 파일 다운로드에 로그인이 필요합니다 (Download 단회 클릭 후 로그인 창 관찰)")
        page.wait_for_timeout(deadline.budget_ms(500))
    raise HosterParseError("링크 컨테이너의 TeraBox 다운로드 단회 요청에서 파일 주소를 확인하지 못했습니다 (권한 미확인)")


def inspect_ouo_download(page, deadline, captured):
    """Click one published /go/ form; never replay or switch bypass engines."""
    links=extract_container_links(page.content(),page.url)
    if links:return choose_container_link(links)
    challenge=page.locator('.g-recaptcha:visible, iframe[src*="recaptcha"]:visible, iframe[src*="hcaptcha"]:visible')
    if challenge.count():
        raise HosterParseError('링크 컨테이너의 사람 확인이 완료되지 않았습니다 (OUO 캡차)')
    button=page.locator('form[action*="/go/"] button[type="submit"]:visible, form[action*="/go/"] input[type="submit"]:visible').first
    button.wait_for(state='visible',timeout=deadline.budget_ms(15000))
    button.click(timeout=deadline.budget_ms(15000))
    expires=time.monotonic()+min(deadline.remaining(),30)
    while deadline.remaining()>0 and time.monotonic()<expires:
        if captured:return choose_container_link(list(dict.fromkeys(captured)))
        if challenge.count():raise HosterParseError('링크 컨테이너의 사람 확인이 완료되지 않았습니다 (OUO 캡차)')
        try:
            links=extract_container_links(page.content(),page.url)
        except BrowserError:
            links=[]
        if links:return choose_container_link(links)
        page.wait_for_timeout(deadline.budget_ms(500))
    raise HosterParseError('링크 컨테이너 OUO 단회 요청에서 파일 주소를 확인하지 못했습니다; 자동 반복 없음')


def extract_container_links(text, base_url):
    soup = BeautifulSoup(text or "", "html.parser")
    candidates = []
    for node in soup.select("a[href], [data-url], [data-link]"):
        for attribute in ("href", "data-url", "data-link"):
            value = node.get(attribute)
            if value:
                candidates.append(urljoin(base_url, value))

    # Preserve published order and choose just one mirror. A failed mirror must
    # not fan out to all the others automatically.
    return list(dict.fromkeys(value for value in candidates if supported_destination(value)))


def choose_container_link(links):
    if len(links) != 1:
        raise HosterParseError("링크 컨테이너에 파일 또는 미러가 여러 개입니다. 실제 파일 링크를 선택하세요.")
    return links[0]


def resolve_container_sync(url):
    if canonical_host(urlparse(url).hostname) == "multiup.io":
        from core.hoster_sites import resolve_multiup_mirror_sync
        return resolve_multiup_mirror_sync(url)
    browser._require_display()
    deadline = browser.Deadline(900 if canonical_host(urlparse(url).hostname) == "filecrypt.cc" else 120)
    source_host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    captured = []
    navigation = {}
    with browser._queued_browser_slot(source_host, deadline):
        if canonical_host(source_host) == "filecrypt.cc":
            from core.executors import signal_parse_started
            signal_parse_started()
            deadline = browser.Deadline(900)
        with browser.sync_playwright() as pw:
            instance = pw.chromium.launch(headless=False)
            try:
                context = instance.new_context(viewport=browser.VIEWPORT)

                def route_navigation(route):
                    request = route.request
                    if request.is_navigation_request():
                        target_host = (urlparse(request.url).hostname or "").lower().removeprefix("www.")
                        try:
                            subframe = request.frame.parent_frame is not None
                        except BrowserError:
                            # Popup/service-worker requests can precede creation
                            # of their frame. Always resolve the intercepted
                            # request instead of leaving page.goto hung forever.
                            if target_host == source_host:
                                route.continue_()
                            else:
                                route.abort()
                            return
                        if subframe:
                            if (target_host == source_host
                                    or any(target_host == host or target_host.endswith("." + host)
                                           for host in ("cutcaptcha.net", "filecrypt.cc", "filecrypt.co", "filecrypt.to", "challenges.cloudflare.com", "google.com", "gstatic.com"))):
                                route.continue_()
                            else:
                                route.abort()
                            return
                        if supported_destination(request.url):
                            captured.append(request.url)
                            route.abort()  # admission to that host happens later
                            return
                        if target_host != source_host and not (
                            source_host in FILECRYPT_HOSTS and target_host in FILECRYPT_HOSTS
                        ) and not (
                            source_host in OUO_HOSTS and target_host in OUO_HOSTS
                        ) and not (source_host == "momerybox.com" and is_terabox_host(target_host)):
                            route.abort()  # popunder advertisement
                            return
                    route.continue_()

                context.route("**/*", route_navigation)
                page = context.new_page()
                def observe_navigation(reply):
                    try:
                        request = reply.request
                        if request.is_navigation_request() and request.frame.parent_frame is None:
                            navigation.update(method=request.method, status=reply.status,
                                              host=urlparse(reply.url).hostname)
                    except Exception:
                        pass
                page.on("response", observe_navigation)
                response = page.goto(url, wait_until="domcontentloaded", timeout=deadline.budget_ms(60000))
                response_status = navigation.get('status', response.status if response else 200)
                if response_status in {403, 503}:
                    from types import SimpleNamespace
                    from core.hoster_common import _cloudflare_challenge_seen
                    proof = SimpleNamespace(status_code=response_status, headers=getattr(response, 'headers', {}))
                    if _cloudflare_challenge_seen(proof, page.content()):
                        # Let the existing browser complete its own initial
                        # check. No reload, second visit or POST is issued here.
                        while navigation.get('status') in {403, 503} and deadline.remaining()>0:
                            page.wait_for_timeout(deadline.budget_ms(500))
                        if navigation.get('status') not in {200, 206}:
                            raise HosterParseError('링크 컨테이너 Cloudflare 초기 확인이 완료되지 않았습니다; 자동 반복 없음')
                        page.wait_for_function("document.body && document.readyState !== 'loading'", timeout=deadline.budget_ms(15000))
                    else:
                        raise HosterParseError(f"링크 컨테이너 페이지 HTTP {response_status}")
                elif response_status >= 400:
                    raise HosterParseError(f"링크 컨테이너 페이지 HTTP {response_status}")
                # Inspect the real download action, never just the redirect.
                if is_terabox_host(urlparse(page.url).hostname):
                    return inspect_terabox_download(page, deadline, captured)
                if source_host in OUO_HOSTS:
                    return inspect_ouo_download(page,deadline,captured)
                page.bring_to_front()
                text = page.content()
                links = extract_container_links(text, page.url)
                if links:
                    return choose_container_link(links)
                # FileCrypt's public security step runs its own JS work. Click
                # once and let it finish; never forge its form or replay a fail.
                checkbox = page.locator("#pow-captcha [role=checkbox]").first
                if checkbox.count():
                    checkbox.click(timeout=deadline.budget_ms(20000))
                    # Observe the next page rather than depending on one
                    # version's internal JS state names. Polling the DOM sends
                    # no host requests and never re-clicks the security form.
                    while deadline.remaining() > 0:
                        if captured:
                            return choose_container_link(list(dict.fromkeys(captured)))
                        try:
                            text = page.content()
                        except BrowserError:
                            # page.content can race the proof's one navigation.
                            # Waiting on the current tab makes no extra request.
                            page.wait_for_timeout(deadline.budget_ms(250))
                            continue
                        links = extract_container_links(text, page.url)
                        if links:
                            return choose_container_link(links)
                        if (navigation.get("method") == "POST"
                                and page.locator('#pow-captcha[data-state="idle"]').count()
                                and page.evaluate("document.readyState") == "complete"):
                            raise HosterParseError("링크 컨테이너 FileCrypt 보안 작업 제출 후 확인 화면이 다시 나왔습니다 (검증 미완료; 자동 반복 없음)")
                        # A hidden captcha iframe can be part of the PoW's
                        # own verification resources. It is not a failed proof.
                        if not page.locator("#pow-captcha").count():
                            # The proof form navigates automatically. A new
                            # document can temporarily contain only its head;
                            # do not classify that intermediate DOM as empty.
                            page.wait_for_function(
                                "document.body && document.readyState !== 'loading'",
                                timeout=deadline.budget_ms(60000),
                            )
                            links = extract_container_links(page.content(), page.url)
                            if links:
                                return choose_container_link(links)
                            # A full proof submission can return the same form.
                            # It is neither a file's disappearance nor a cue to
                            # click again. Observe its settled next document.
                            if page.locator("#pow-captcha").count():
                                raise HosterParseError("링크 컨테이너 FileCrypt 보안 작업 제출 후 확인 화면이 다시 나왔습니다 (검증 미완료; 자동 반복 없음)")
                            break
                        page.wait_for_timeout(deadline.budget_ms(1000))
                    if page.locator('#pow-captcha[data-state="working"]').count():
                        raise HosterParseError("FileCrypt 보안 검증 작업이 제한시간 내 완료되지 않았습니다 (진행 미확인; 자동 반복 없음)")
                # Some containers expose a single Link/... navigation through
                # a download button. Follow one; intercept its final host URL.
                button = page.locator('a[href*="/Link/"]:visible, button.download:visible, button[onclick*="openLink"]:visible').first
                if button.count():
                    button.click(timeout=deadline.budget_ms(20000))
                    until = min(deadline.remaining(), 15)
                    for _ in range(int(until)):
                        if captured:
                            return choose_container_link(list(dict.fromkeys(captured)))
                        page.wait_for_timeout(1000)
                if captured:
                    return choose_container_link(list(dict.fromkeys(captured)))
                challenge = page.locator('iframe[src*="cutcaptcha"]:visible, .g-recaptcha:visible, iframe[src*="recaptcha"]:visible')
                if challenge.count():
                    raise HosterParseError("링크 컨테이너의 사람 확인이 완료되지 않았습니다 (캡차)")
                raise HosterParseError("링크 컨테이너에서 지원 파일 호스트 주소를 찾지 못했습니다")
            except HosterParseError:
                raise
            except Exception as exc:
                if captured:
                    return choose_container_link(list(dict.fromkeys(captured)))
                raise HosterParseError("링크 컨테이너 브라우저 처리 실패; 자동 반복하지 않습니다") from exc
            finally:
                # Capture the observation without a second HTTP probe. Never
                # store nonce/cookie values in the machine-readable evidence.
                try:
                    proof = page.locator("#pow-captcha").first
                    evidence = {"final_host": urlparse(page.url).hostname,
                                "initial_http_status": response.status if response else None,
                                "last_navigation": navigation,
                                "pow_state": proof.get_attribute("data-state") if proof.count() else None,
                                "progress_style": page.locator(".pow-captcha__progress i").first.get_attribute("style") if page.locator(".pow-captcha__progress i").count() else None,
                                "nonce_present": bool(page.locator('input[name="pow_nonce"]').first.input_value()) if page.locator('input[name="pow_nonce"]').count() else False,
                                "deletion_confirmed": False}
                    key = hashlib.sha256(url.encode()).hexdigest()[:16]
                    path = Path(CONFIG_DIR) / f"container_{key}_response.json"
                    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
                    path.chmod(0o600)
                    html = path.with_suffix(".html")
                    html.write_text(page.content())
                    html.chmod(0o600)
                except Exception:
                    pass
                instance.close()
