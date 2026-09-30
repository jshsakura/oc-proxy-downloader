"""Collected host dispatch and conservative per-site form contracts."""
from types import SimpleNamespace
import contextlib
import pytest
from core import hoster_legacy_sites as sites, hoster_parsers as registry
from core.hoster_common import HosterParseError
from core.error_messages import classify_error, KIND_SOURCE_UNCONFIRMED, KIND_BROWSER_PARSE
from core.host_policy import canonical_host


class Reply:
    def __init__(self, text='', status=200, headers=None):
        self.body=text.encode();self.status_code=status;self.reason='test';self.encoding='utf-8'
        self.headers=headers or {'Content-Type':'text/html'};self.closed=False
    def iter_content(self,size):yield self.body
    def close(self):self.closed=True


class Session:
    def __init__(self,replies):
        self.replies=list(replies);self.calls=[];self.headers={'User-Agent':'same-UA'}
        self.cookies=SimpleNamespace(get_dict=lambda:{'sid':'same-cookie'});self.closed=False
    def mount(self,*args):pass
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs));return self.replies.pop(0)
    def close(self):self.closed=True


def setup(monkeypatch,replies):
    session=Session(replies);monkeypatch.setattr(sites,'_scraper',lambda proxies:session);return session


@pytest.mark.parametrize('key',[key for key,site in sites.SITES.items() if site.protocol=='xfs' and key!='sendnow'])
def test_each_xfs_has_own_file_form_and_single_submission(monkeypatch,key):
    site=sites.SITES[key];origin='https://'+site.domains[0];url=origin+'/abcdefgh1234'
    form='<form method="POST"><input type="hidden" name="op" value="download1"><input type="hidden" name="id" value="abcdefgh1234"><input type="hidden" name="fname" value="base.part3.rar"><input name="method_free" value="Free"></form>'
    direct='https://storage.'+site.domains[0]+'/d/token/base.part3.rar'
    selector_id='downloadlink' if key=='uptobox' else 'downloadbtn'
    session=setup(monkeypatch,[Reply(form),Reply(f'<a id="{selector_id}" href="{direct}">Download</a>')])
    result=getattr(sites,'parse_'+key+'_sync')(url)
    assert result['download_link']==direct
    assert result['file_info']['name']=='base.part3.rar'
    assert result['cookies']=={'sid':'same-cookie'} and result['user_agent']=='same-UA'
    assert [c[0] for c in session.calls]==['GET','POST']
    assert session.calls[1][2]['data']['id']=='abcdefgh1234'
    assert session.closed


@pytest.mark.parametrize('status',[403,404,410,429,503])
def test_error_page_never_returns_advertised_file_or_retries(monkeypatch,status):
    reply=Reply('<a id="downloadbtn" href="https://storage.filekeeper.net/d/t/base.nsp">x</a>',status)
    session=setup(monkeypatch,[reply])
    with pytest.raises(HosterParseError) as error:sites.parse_filekeeper_sync('https://filekeeper.net/abcdefgh1234')
    assert len(session.calls)==1 and reply.closed and session.closed
    if status in (404,410):assert classify_error('파싱',str(error.value)).kind==KIND_SOURCE_UNCONFIRMED


@pytest.mark.parametrize('change', ['repeated_op','wrong_id','captcha','foreign_action'])
def test_xfs_refusal_never_replays_or_posts_to_ads(monkeypatch,change):
    token='anotherfile' if change=='wrong_id' else 'abcdefgh1234'
    action='https://ad.example/' if change=='foreign_action' else ''
    captcha='<div class="g-recaptcha"></div>' if change=='captcha' else ''
    text=f'<form action="{action}" method="POST"><input type="hidden" name="op" value="download1"><input type="hidden" name="id" value="{token}">{captcha}</form>'
    session=setup(monkeypatch,[Reply(text),Reply(text)])
    with pytest.raises(HosterParseError):sites.parse_filekeeper_sync('https://filekeeper.net/abcdefgh1234')
    assert [c[0] for c in session.calls]==(['GET','POST'] if change=='repeated_op' else ['GET'])


def test_filekeeper_current_countdown_issues_download2_once(monkeypatch):
    # Reduced from the actual page for collected source 145507, not an XFS
    # form guessed from another host. The normal page starts at download2.
    html = '<span id="dl-filename">base.rar</span><div id="download-countdown" data-countdown="5" data-code="sfrn6h8bto0n" data-referer="https://filekeeper.net/sfrn6h8bto0n" data-rand="" data-method="" data-has-password="false" data-has-captcha="false"></div>'
    direct = 'https://tunnel1.dlproxy.uk/download/token/base.rar'
    session = setup(monkeypatch, [Reply(html), Reply(status=302, headers={'Location':direct})])
    waits = []
    monkeypatch.setattr(sites.time, 'sleep', waits.append)
    result = sites.parse_filekeeper_sync('https://filekeeper.net/sfrn6h8bto0n')
    assert result['download_link'] == direct and result['file_info']['name'] == 'base.rar'
    assert [c[0] for c in session.calls] == ['GET', 'POST']
    assert session.calls[1][2]['data'] == {'op':'download2', 'id':'sfrn6h8bto0n', 'rand':'',
        'referer':'https://filekeeper.net/sfrn6h8bto0n', 'method_free':'Free download', 'down_direct':'1'}
    assert waits == [5]


@pytest.mark.parametrize('key,html,direct',[
    ('solidfiles','<h1 class="node-name">base.nsp</h1><a class="direct-download" href="https://s1.solidfilesusercontent.com/base.nsp">x</a>','https://s1.solidfilesusercontent.com/base.nsp'),
    ('qiwi','<a download href="https://dl.spyderrock.com/base.rar">x</a>','https://dl.spyderrock.com/base.rar'),
    ('bayfiles','<a id="download-url" href="https://cdn.bayfiles.com/d/token/base.rar">x</a>','https://cdn.bayfiles.com/d/token/base.rar'),
    ('bowfile','<a class="download-link" href="https://cdn.bowfile.com/download/token/base.rar">x</a>','https://cdn.bowfile.com/download/token/base.rar'),
])
def test_site_published_storage_controls(monkeypatch,key,html,direct):
    site=sites.SITES[key];path='/v/abc' if key=='solidfiles' else '/file/abc' if key=='qiwi' else '/abc'
    session=setup(monkeypatch,[Reply(html)])
    assert sites.parse_site(key,'https://'+site.domains[0]+path)['download_link']==direct
    assert len(session.calls)==1


def test_doodrive_advertised_form_steps_once(monkeypatch):
    first='<form method="POST"><input type="hidden" name="f" value="id"></form>'
    second='<form method="POST"><input type="hidden" name="data" value="token"></form>'
    third='<a href="https://s1.doodrive.com/d/token/base.nsp">Download</a>'
    session=setup(monkeypatch,[Reply(first),Reply(second),Reply(third)])
    result=sites.parse_doodrive_sync('https://doodrive.com/f/abc')
    assert result['download_link']=='https://s1.doodrive.com/d/token/base.nsp'
    assert [c[0] for c in session.calls]==['GET','POST','POST']


def test_page_size_is_bounded(monkeypatch):
    reply=Reply('x'*(2*1024*1024+1));session=setup(monkeypatch,[reply])
    with pytest.raises(HosterParseError,match='크기 상한'):sites.parse_filekeeper_sync('https://filekeeper.net/abcdefgh1234')
    assert reply.closed and session.closed


def test_redirect_preserves_source_and_never_contacts_ad(monkeypatch):
    session=setup(monkeypatch,[Reply(status=302,headers={'Location':'https://ad.example/login'})])
    with pytest.raises(HosterParseError) as error:sites.parse_filekeeper_sync('https://filekeeper.net/abcdefgh1234')
    assert len(session.calls)==1 and classify_error('파싱',str(error.value)).kind==KIND_BROWSER_PARSE


@pytest.mark.parametrize('host', [
    'filekeeper.net','tusfiles.com','uptobox.com','clicknupload.to','clicknupload.cc','clicknupload.red','clicknupload.co',
    'clickndownload.org','send.cm','letsupload.io','bowfile.com','doodrive.com','filerio.in','frdl.my',
    'solidfiles.com','bayfiles.com','qiwi.gg','teraboxapp.com','www62.zippyshare.com',
])
def test_collected_host_routes_to_dedicated_resolver(host):
    spec=registry._spec_for_url('https://'+host+'/abc')
    assert spec is not None and spec.parse.startswith('legacy.')


def test_host_aliases_share_one_transfer_slot():
    assert canonical_host('www62.zippyshare.com')=='zippyshare.com'
    assert canonical_host('clicknupload.red')==canonical_host('clickndownload.org')=='clicknupload.to'
    assert canonical_host('tusfiles.com')==canonical_host('send.cm')
    assert not registry.is_special_hoster_url('https://www62.zippyshare.com.evil.example/v/abc/file.html')


@pytest.mark.parametrize('proxy', [False,True])
def test_new_form_and_file_transport_use_same_egress(proxy):
    from core.download_core import DownloadCore
    req=SimpleNamespace(id=1,url='https://filekeeper.net/abcdefgh1234',original_url=None,use_proxy=proxy)
    commits=[];db=SimpleNamespace(commit=lambda:commits.append(True))
    routed=DownloadCore()._apply_download_route(req,db)
    assert req.use_proxy is False
    assert bool(commits)==proxy
    if proxy:assert routed[0] is False


@pytest.mark.parametrize('captcha', [False,True])
def test_rapidgator_free_button_once_and_file_navigation_intercepted(monkeypatch,captcha):
    from core import browser_solver as browser
    state=SimpleNamespace(clicks=0,visits=0,seconds=0,aborted=0,route=None)
    target='https://s1.rapidgator.net/download/token/base.nsp'
    class Locator:
        @property
        def first(self):return self
        def wait_for(self,**kwargs):pass
        def click(self,**kwargs):state.clicks+=1
        def count(self):return int(captcha)
        def inner_text(self,**kwargs):return 'File size: 10 MB'
    class Page:
        url='https://rapidgator.net/file/'+'a'*32+'/base.nsp.html'
        def locator(self,*args):return Locator()
        def goto(self,url,**kwargs):state.visits+=1;return SimpleNamespace(status=200)
        def wait_for_timeout(self,ms):
            state.seconds+=ms/1000
            request=SimpleNamespace(url=target,is_navigation_request=lambda:True,frame=SimpleNamespace(parent_frame=None))
            def abort():state.aborted+=1
            state.route(SimpleNamespace(request=request,abort=abort,continue_=lambda:None))
        def content(self):return '<h1 class="file-name">base.nsp</h1>'
        def evaluate(self,expression):return 'same-UA'
    page=Page()
    class Context:
        def route(self,pattern,callback):state.route=callback
        def new_page(self):return page
        def cookies(self,urls):assert urls==[target];return [{'name':'sid','value':'same-cookie'}]
    instance=SimpleNamespace(new_context=lambda **kwargs:Context(),close=lambda:None)
    monkeypatch.setattr(browser,'_require_display',lambda:None)
    monkeypatch.setattr(browser,'_queued_browser_slot',lambda *args:contextlib.nullcontext())
    monkeypatch.setattr(browser,'Deadline',lambda seconds:SimpleNamespace(remaining=lambda:seconds-state.seconds,budget_ms=lambda ms:ms))
    monkeypatch.setattr(browser,'sync_playwright',lambda:contextlib.nullcontext(SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs:instance))))
    if captcha:
        with pytest.raises(HosterParseError,match='캡차'):sites.parse_rapidgator_free_sync(page.url)
        assert state.aborted==0
    else:
        result=sites.parse_rapidgator_free_sync(page.url)
        assert result['download_link']==target and result['cookies']=={'sid':'same-cookie'}
        assert state.aborted==1
    assert state.clicks==1 and state.visits==1

@pytest.mark.parametrize('refused', [False, True])
def test_rapidgator_submits_observed_turnstile_confirmation_once(monkeypatch, refused):
    from core import browser_solver as browser
    state=SimpleNamespace(clicks=[],seconds=0,stage='file',route=None)
    target='https://s1.rapidgator.net/download/token/update.rar'
    class Locator:
        def __init__(self,selector):self.selector=selector
        @property
        def first(self):return self
        def wait_for(self,**kwargs):pass
        def count(self):
            if 'recaptcha' in self.selector or 'hcaptcha' in self.selector:return 0
            if 'captchaform' in self.selector:return int(state.stage=='confirmation')
            return 1
        def inner_text(self,**kwargs):return 'File size: 149 MB'
        def locator(self,selector):return Locator(selector)
        def input_value(self,**kwargs):return 'token-issued-by-the-normal-page'
        def click(self,**kwargs):
            state.clicks.append(self.selector)
            if 'submit-button' in self.selector:
                if not refused:
                    request=SimpleNamespace(url=target,is_navigation_request=lambda:True,frame=SimpleNamespace(parent_frame=None))
                    state.route(SimpleNamespace(request=request,abort=lambda:None,continue_=lambda:None))
            else:state.stage='confirmation'
    class Page:
        url='https://rapidgator.net/file/'+'b'*32+'/update.rar.html'
        def locator(self,s):return Locator(s)
        def goto(self,*args,**kwargs):return SimpleNamespace(status=200)
        def wait_for_timeout(self,ms):state.seconds+=ms/1000
        def content(self):return '<form id="captchaform" action="/download/captcha" method="post"><input name="DownloadCaptchaForm[verifyCode]" value="normal-token"><div class="cf-turnstile"></div><a id="submit-button">Send</a></form>'
        def evaluate(self,*args):return 'normal-UA'
    class Context:
        def route(self,p,cb):state.route=cb
        def new_page(self):return Page()
        def cookies(self,*args):return []
    instance=SimpleNamespace(new_context=lambda **kw:Context(),close=lambda:None)
    monkeypatch.setattr(browser,'_require_display',lambda:None)
    monkeypatch.setattr(browser,'_queued_browser_slot',lambda *a:contextlib.nullcontext())
    monkeypatch.setattr(browser,'Deadline',lambda seconds:SimpleNamespace(remaining=lambda:seconds-state.seconds,budget_ms=lambda ms:ms))
    monkeypatch.setattr(browser,'sync_playwright',lambda:contextlib.nullcontext(SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw:instance))))
    if refused:
        with pytest.raises(HosterParseError,match='자동 반복 없음'):sites.parse_rapidgator_free_sync(Page.url)
    else:
        assert sites.parse_rapidgator_free_sync(Page.url)['download_link']==target
    assert len(state.clicks)==2
    assert state.clicks[1]=='#submit-button:visible'

@pytest.mark.parametrize('fs_status', [200,403])
def test_proven_get_interstitial_uses_browser_once_with_its_actual_session(monkeypatch,fs_status):
    from requests.cookies import RequestsCookieJar
    from core import hoster_common as common
    session=setup(monkeypatch,[Reply('<html>Just a moment <script src="/cdn-cgi/challenge-platform/"></script></html>',403)])
    session.cookies=RequestsCookieJar()
    calls=[]
    target='https://storage.filekeeper.net/d/token/base.nsp'
    def browser_get(url,**kw):
        calls.append(url)
        return {'status':fs_status,'url':url,'response':f'<a id="downloadbtn" href="{target}">Download</a>',
            'userAgent':'browser-UA','cookies':[{'name':'cf_clearance','value':'browser-cookie'}]}
    monkeypatch.setattr(common,'_flaresolverr_request_get',browser_get)
    if fs_status==200:
        result=sites.parse_filekeeper_sync('https://filekeeper.net/abcdefgh1234')
        assert result['download_link']==target
        assert result['user_agent']=='browser-UA'
        assert result['cookies']=={'cf_clearance':'browser-cookie'}
    else:
        with pytest.raises(HosterParseError,match='자동 반복 없음'):sites.parse_filekeeper_sync('https://filekeeper.net/abcdefgh1234')
    assert len(calls)==1 and len(session.calls)==1


def test_rejected_post_and_plain_cloudflare_footer_never_start_browser(monkeypatch):
    from core import hoster_common as common
    monkeypatch.setattr(common,'_flaresolverr_request_get',lambda *a,**kw:pytest.fail('rejected POST or plain footer replay'))
    form='<form method="POST"><input type="hidden" name="op" value="download2"><input type="hidden" name="id" value="abcdefgh1234"></form>'
    session=setup(monkeypatch,[Reply(form),Reply('<html>Just a moment challenge-platform</html>',403)])
    with pytest.raises(HosterParseError):sites.parse_filekeeper_sync('https://filekeeper.net/abcdefgh1234')
    assert [r[0] for r in session.calls]==['GET','POST']
    session=setup(monkeypatch,[Reply('<html>Access denied; Cloudflare</html>',403)])
    with pytest.raises(HosterParseError):sites.parse_filekeeper_sync('https://filekeeper.net/abcdefgh1234')
    assert len(session.calls)==1


def test_sendnow_actual_file_card_not_code_title_or_upload_limit():
    # Saved 2605 DOM: the title is only an ID and the footer advertises 100 GB.
    html = '''<title>r4nvci07hlux</title>
    <h6 class="tx-uppercase max-width-50">RIV-UE-NSwTcH-NSP-Update122-Ziperto.rar</h6>
    <h6 class="modal-title" id="qr">RIV-UE-NSwTcH-NSP-Update122-Ziperto.rar</h6>
    <button id="downloadbtn">Download [42.2 MB]</button>
    <h5>Upload up to 100 GB per file for Free</h5>'''
    assert sites._extract_sendnow_file_info(html) == {
        'name': 'RIV-UE-NSwTcH-NSP-Update122-Ziperto.rar', 'size': '42.2 MB',
    }


def test_sendnow_marketing_text_is_not_file_metadata():
    assert sites._extract_sendnow_file_info('<title>abc123456789</title><h5>Upload up to 100 GB per file for Free</h5>') == {}


def test_sendnow_disagreeing_file_cards_stop_without_guessing():
    with pytest.raises(sites.HosterParseError, match='이름이 서로'):
        sites._extract_sendnow_file_info('<h6 class="max-width-50">a.rar</h6><h6 id="qr">b.rar</h6>')
