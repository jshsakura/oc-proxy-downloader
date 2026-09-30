"""Container provenance and PoW observation without external requests."""
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from core import link_containers as module
from core.download_core import DownloadCore, SPECIAL_HOSTER_PARSE_TIMEOUT_SEC
from core.hoster_common import HosterParseError


def test_public_links_exclude_ads_and_script_templates():
    html = '''<script>const fake="https://rootz.so/d/template";</script>
    <a href="https://discord.gg/example">invite</a>
    <a href="https://rootz.so.evil.example/d/a">ad</a>
    <a href="https://www.rootz.so/d/real">BASE B</a>'''
    assert module.extract_container_links(html, "https://filecrypt.cc/Container/a.html") == ["https://www.rootz.so/d/real"]


def test_multiple_files_require_selection():
    with pytest.raises(HosterParseError, match="여러 개"):
        module.choose_container_link(["https://rootz.so/d/part1", "https://rootz.so/d/part2"])


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["direct", "local", "proxy"])
async def test_container_with_saved_filename_never_reaches_file_transfer(monkeypatch, tmp_path, entry):
    """Old metadata or a caller bypassing the queue cannot save container HTML."""
    from core import download_core as dc
    from unittest.mock import MagicMock
    url = "https://filecrypt.cc/Container/2AE0D4F816.html"
    part = tmp_path / "Culdcept.nsp.part"
    part.write_bytes(b"PFS0existing-partial-data")
    req = SimpleNamespace(url=url, file_name="Culdcept.nsp", total_size=1074912470,
                          save_path=str(part), id=42)
    core = DownloadCore()
    session = MagicMock(side_effect=AssertionError("container must not be fetched as a file"))
    transfer = AsyncMock(side_effect=AssertionError("container must not reach file I/O"))
    monkeypatch.setattr(dc.aiohttp, "ClientSession", session)
    monkeypatch.setattr(dc, "download_file_content", transfer)
    with pytest.raises(HosterParseError, match="HTML은"):
        if entry == "direct":
            await core._download_file_directly(req, MagicMock(), url)
        elif entry == "local":
            await core._download_local_async(req, MagicMock())
        else:
            await core._perform_file_download_async(req, MagicMock())
    session.assert_not_called()
    transfer.assert_not_awaited()
    assert part.read_bytes() == b"PFS0existing-partial-data"


def test_container_cannot_be_marked_complete_even_with_binary_mime(tmp_path):
    from core.download_core import assert_downloaded_a_real_file
    path = tmp_path / "2AE0D4F816.html"
    payload = b"<html>FileCrypt security check</html>"
    path.write_bytes(payload)
    req = SimpleNamespace(url="https://filecrypt.cc/Container/2AE0D4F816.html",
                          file_name=path.name, save_path=str(path), total_size=len(payload))
    with pytest.raises(HosterParseError, match="컨테이너"):
        assert_downloaded_a_real_file(req, len(payload), "application/octet-stream")


@pytest.mark.parametrize("error", ["Response payload is not completed", "Not enough data to satisfy content length", "Incomplete read"])
def test_interrupted_transfer_does_not_promise_an_automatic_retry(error):
    from core.error_messages import classify_error
    verdict = classify_error("다운로드", error)
    assert "자동 재시도됩니다" not in verdict.to_user_message()
    assert "수동" in verdict.to_user_message()


@pytest.mark.asyncio
async def test_failed_filecrypt_resolution_never_downloads_its_html(monkeypatch):
    from core import download_core as dc
    from unittest.mock import MagicMock
    url = "https://filecrypt.cc/Container/2AE0D4F816.html"
    req = SimpleNamespace(id=42, url=url, original_url=url, file_name="Culdcept.nsp",
                          file_size="1 GB", total_size=1074912470, downloaded_size=0,
                          use_proxy=False, status=dc.StatusEnum.parsing, failure_kind=None,
                          next_retry_at=None, attempt_count=0, attempts_json=None, error=None)
    db = MagicMock()
    core = DownloadCore()
    core.send_download_update = AsyncMock()
    core._await_host_cooldown = AsyncMock()
    core._record_host_refusal = AsyncMock()
    core._run_special_parser = AsyncMock(side_effect=HosterParseError("FileCrypt 보안 확인 미완료"))
    core._download_local_async = AsyncMock()
    monkeypatch.setattr(dc, "SessionLocal", lambda: db)
    monkeypatch.setattr(dc.db_async, "first", AsyncMock(return_value=req))
    monkeypatch.setattr(dc.db_async, "commit", AsyncMock())
    monkeypatch.setattr(dc.db_async, "refresh", AsyncMock())
    await core._download_task(42, skip_parsing=True)
    core._run_special_parser.assert_awaited_once()
    core._download_local_async.assert_not_awaited()
    assert req.status == dc.StatusEnum.failed
    assert req.url == req.original_url == url
    assert req.file_name == "Culdcept.nsp" and req.total_size == 1074912470
    assert core.send_download_update.await_args.args[1]["stage"] == "파싱"


def test_current_mirror_host_and_provenance():
    req = SimpleNamespace(original_url="https://akirabox.com/original/file", url="https://www.rootz.so/d/mirror")
    assert module.admission_url(req) == req.url
    req.url = "https://unregistered-cdn.example/token"
    assert module.admission_url(req) == req.original_url
    req.original_url = "https://filecrypt.cc/Container/container.html"
    req.url = "https://vikingfile.com/f/target"
    assert module.admission_url(req) == req.url


@pytest.mark.asyncio
@pytest.mark.parametrize("url,expected", [
    ("https://filecrypt.cc/Container/a.html", 960),
    ("https://filecrypt.to/Container/a.html", 960),
    ("https://linkcuy.com/a", SPECIAL_HOSTER_PARSE_TIMEOUT_SEC),
    ("https://rootz.so/d/a", SPECIAL_HOSTER_PARSE_TIMEOUT_SEC),
])
async def test_only_filecrypt_receives_long_outer_budget(url, expected):
    core = DownloadCore()
    core._run_parser = AsyncMock(return_value="resolved")
    parse = lambda: None
    assert await core._run_special_parser(url, parse) == "resolved"
    core._run_parser.assert_awaited_once_with(url, parse, expected)


@pytest.mark.parametrize("partial_navigation,returned_form", [(False, False), (True, False), (True, True), (False, True)])
def test_pow_passes_sixty_seconds_without_reclick_or_new_get(monkeypatch, tmp_path, partial_navigation, returned_form):
    class Locator:
        def __init__(self, selector): self.selector = selector
        @property
        def first(self): return self
        def count(self):
            if 'role=checkbox' in self.selector: return 1
            if self.selector == '#pow-captcha': return int(page.seconds < 65 or returned_form and page.seconds >= (66 if partial_navigation else 65))
            if 'data-state="working"' in self.selector: return int(page.seconds < 65)
            if 'data-state="idle"' in self.selector: return int(returned_form and page.seconds >= (66 if partial_navigation else 65))
            if 'cutcaptcha' in self.selector: return 1
            return 0
        def click(self, **kwargs): page.clicks += 1
        def get_attribute(self, key): return 'working'
    class Page:
        seconds = 0; clicks = 0; visits = 0
        url = "https://filecrypt.cc/Container/a.html"
        def on(self, event, callback): self.callback = callback
        def evaluate(self, expression): return 'complete'
        def goto(self, url, **kwargs): self.visits += 1; return SimpleNamespace(status=200)
        def bring_to_front(self): pass
        def locator(self, selector): return Locator(selector)
        def content(self):
            if partial_navigation and 65 <= self.seconds < 66:
                return '<html><head><title>Filecrypt</title></head></html>'
            if returned_form and self.seconds >= (66 if partial_navigation else 65):
                return '<div id="pow-captcha" data-state="idle"></div><a href="/Link/1" style="display:none"></a>'
            return ('<div id="pow-captcha" data-state="working"></div>' if self.seconds < 65
                    else '<a href="https://rootz.so/d/base">BASE</a>')
        def wait_for_timeout(self, ms):
            self.seconds += ms / 1000
            if returned_form and self.seconds >= 65:
                self.callback(SimpleNamespace(request=SimpleNamespace(is_navigation_request=lambda: True, frame=SimpleNamespace(parent_frame=None), method='POST'), status=200, url=self.url))
        def wait_for_function(self, expression, **kwargs):
            assert "document.body" in expression
            if partial_navigation:
                self.seconds = 66
    page = Page()
    class Context:
        def route(self, *args): pass
        def new_page(self): return page
    class Browser:
        def new_context(self, **kwargs): return Context()
        def close(self): pass
    class Deadline:
        def __init__(self, seconds): self.seconds = seconds; assert seconds == 900
        def remaining(self): return self.seconds - page.seconds
        def budget_ms(self, ms): return min(ms, int(self.remaining() * 1000))
    monkeypatch.setattr(module.browser, '_require_display', lambda: None)
    monkeypatch.setattr(module.browser, 'Deadline', Deadline)
    monkeypatch.setattr(module.browser, '_queued_browser_slot', lambda *args: contextlib.nullcontext())
    monkeypatch.setattr(module.browser, 'sync_playwright', lambda: contextlib.nullcontext(SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs: Browser()))))
    monkeypatch.setattr(module, 'CONFIG_DIR', tmp_path)
    if returned_form:
        with pytest.raises(HosterParseError, match="검증 미완료"):
            module.resolve_container_sync(page.url)
    else:
        assert module.resolve_container_sync(page.url) == "https://rootz.so/d/base"
    assert page.seconds == (66 if partial_navigation else 65)
    assert page.visits == 1 and page.clicks == 1


@pytest.mark.parametrize("host,allowed", [
    ("www.terabox.app", True), ("www.1024terabox.com", True),
    ("terabox.app.evil.example", False), ("fake-terabox.example", False),
])
def test_terabox_redirect_uses_domain_boundary(host, allowed):
    assert module.is_terabox_host(host) is allowed


@pytest.mark.parametrize("login_after_click", [False, True])
def test_terabox_requires_actual_visible_login_after_download(monkeypatch, login_after_click):
    state = SimpleNamespace(clicks=0, now=0)
    class Locator:
        @property
        def first(self): return self
        def wait_for(self, **kwargs): pass
        def click(self, **kwargs): state.clicks += 1
        def count(self): return int(state.clicks > 0 and login_after_click)
    class Page:
        def locator(self, selector):
            assert selector in (".download-btn:visible", ".login-dialog:visible")
            return Locator()
        def wait_for_timeout(self, ms): state.now += ms / 1000
    deadline = SimpleNamespace(remaining=lambda: 120-state.now, budget_ms=lambda ms: ms)
    monkeypatch.setattr(module.time, "monotonic", lambda: state.now)
    with pytest.raises(HosterParseError) as caught:
        module.inspect_terabox_download(Page(), deadline, [])
    assert state.clicks == 1
    from core.error_messages import classify_error, KIND_AUTH_REQUIRED, KIND_BROWSER_PARSE
    verdict = classify_error("파싱", str(caught.value))
    assert verdict.kind == (KIND_AUTH_REQUIRED if login_after_click else KIND_BROWSER_PARSE)


@pytest.mark.asyncio
async def test_filecrypt_outer_clock_starts_after_browser_queue(monkeypatch):
    import threading
    from core import download_core as dc
    from core.executors import signal_parse_started
    queued = threading.Event()
    admit = threading.Event()
    def parse():
        queued.set()
        assert admit.wait(2)
        signal_parse_started()
        return "destination"
    core = DownloadCore()
    task = __import__('asyncio').create_task(core._run_parser('https://filecrypt.cc/Container/a.html', parse, timeout=0.01))
    assert await __import__('asyncio').to_thread(queued.wait, 1)
    try:
        await __import__('asyncio').sleep(0.05)
        assert not task.done()
        admit.set()
        assert await __import__('asyncio').wait_for(task, 1) == 'destination'
    finally:
        admit.set()
        await __import__('asyncio').gather(task, return_exceptions=True)


@pytest.mark.parametrize('issued', [False,True])
def test_ouo_published_form_clicks_once_without_engine_retry(monkeypatch,issued):
    state=SimpleNamespace(clicks=0,seconds=0);captured=[]
    class Locator:
        @property
        def first(self):return self
        def count(self):return 0
        def wait_for(self,**kwargs):pass
        def click(self,**kwargs):state.clicks+=1
    class Page:
        url='https://ouo.io/source'
        def content(self):return '<form method="POST" action="/go/source"><button type="submit">Get link</button></form>'
        def locator(self,selector):return Locator()
        def wait_for_timeout(self,ms):
            state.seconds+=ms/1000
            if issued:captured.append('https://rootz.so/d/base')
    deadline=SimpleNamespace(remaining=lambda:120-state.seconds,budget_ms=lambda ms:ms)
    monkeypatch.setattr(module.time,'monotonic',lambda:state.seconds)
    if issued:assert module.inspect_ouo_download(Page(),deadline,captured)=='https://rootz.so/d/base'
    else:
        with pytest.raises(HosterParseError,match='단회 요청'):module.inspect_ouo_download(Page(),deadline,captured)
    assert state.clicks==1 and state.seconds<=30


def test_ouo_alias_uses_same_admission():
    from core.host_policy import canonical_host, SITE_DOWNLOAD_LIMITS
    assert canonical_host('ouo.press')==canonical_host('ouo.io')
    assert SITE_DOWNLOAD_LIMITS[canonical_host('ouo.press')]==1


def test_popup_without_created_frame_does_not_leave_navigation_pending(monkeypatch):
    from core.link_containers import BrowserError
    calls=[]
    class Request:
        def __init__(self,url):self.url=url
        def is_navigation_request(self):return True
        @property
        def frame(self):raise BrowserError('Frame for this navigation request is not available')
    class Page:
        url='https://filecrypt.cc/Container/source.html'
        def on(self,*args):pass
        def goto(self,*args,**kwargs):
            for url in [self.url,'https://advertisement.test/popup']:
                context.callback(SimpleNamespace(request=Request(url),
                    continue_=lambda:calls.append('continued'),abort=lambda:calls.append('aborted')))
            return SimpleNamespace(status=200)
        def bring_to_front(self):pass
        def content(self):return '<a href="https://rootz.so/d/exact-file">Download</a>'
    class Context:
        def route(self,pattern,cb):self.callback=cb
        def new_page(self):return Page()
    context=Context()
    instance=SimpleNamespace(new_context=lambda **kw:context,close=lambda:None)
    monkeypatch.setattr(module.browser,'_require_display',lambda:None)
    monkeypatch.setattr(module.browser,'_queued_browser_slot',lambda *a:contextlib.nullcontext())
    monkeypatch.setattr(module.browser,'sync_playwright',lambda:contextlib.nullcontext(SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw:instance))))
    assert module.resolve_container_sync(Page.url)=='https://rootz.so/d/exact-file'
    assert calls==['continued','aborted']
