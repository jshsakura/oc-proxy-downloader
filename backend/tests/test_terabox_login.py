import base64
from urllib.parse import urlsplit

import pytest
import requests

from core import terabox_login
from core.hoster_common import HosterParseError


class Reply:
    def __init__(self, payload=None, text="", url=""):
        self.payload = payload
        self.text = text
        self.url = url

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def accept_every_cookie(monkeypatch):
    monkeypatch.setattr(terabox_login, "verify_ndus", lambda origin, ndus, proxies: None)


def use(monkeypatch, fake):
    fake.cookies["browserid"] = "browser-1"
    monkeypatch.setattr(terabox_login.requests, "Session", lambda: fake)


PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 32).decode()


class FakeQr:
    def __init__(self, replies):
        self.headers = {}
        self.proxies = {}
        self.params = {}
        self.cookies = requests.cookies.RequestsCookieJar()
        self.posts = []
        self.replies = list(replies)

    def get(self, url, **kwargs):
        assert url == terabox_login.LOGIN_PAGE
        return Reply(text='{"pcftoken":"pcf-1","jsToken":"page-token"}', url=url)

    def post(self, url, data=None, **kwargs):
        path = urlsplit(url).path
        self.posts.append((path, dict(data)))
        if path == "/passport/qrcode/get":
            return Reply({"code": 0, "data": {"uuid": "u1", "seq": "7", "qrcode": "data:image/png;base64," + PNG, "expires_in": 120}})
        return Reply(self.replies.pop(0))


def test_qr_flow_advances_the_sequence_and_ends_with_the_cookie(monkeypatch):
    fake = FakeQr([{"code": 39}, {"code": 0, "data": {"userid": "x"}}, {"code": 0, "data": {"ndus": "qr-cookie"}}])
    use(monkeypatch, fake)
    started = terabox_login.qr_start()
    assert started["png_base64"] == PNG and started["expires_in"] == 120
    handle = started["handle"]
    assert terabox_login.qr_poll(handle)["status"] == "waiting_scan"
    assert terabox_login.qr_poll(handle)["status"] == "waiting_confirm"
    assert terabox_login.qr_poll(handle) == {"status": "done", "ndus": "qr-cookie"}
    polls = [data for path, data in fake.posts if path == "/passport/qrcode/login"]
    assert [p["seq"] for p in polls] == ["8", "9", "10"]
    assert [p["step"] for p in polls] == ["0", "0", "1"]
    with pytest.raises(HosterParseError, match="만료"):
        terabox_login.qr_poll(handle)


def test_qr_approval_without_a_session_is_an_error(monkeypatch):
    fake = FakeQr([{"code": 0, "data": {}}, {"code": 0, "data": {}}])
    use(monkeypatch, fake)
    handle = terabox_login.qr_start()["handle"]
    assert terabox_login.qr_poll(handle)["status"] == "waiting_confirm"
    with pytest.raises(HosterParseError, match="세션"):
        terabox_login.qr_poll(handle)


def test_qr_refuses_a_reply_that_is_not_a_png(monkeypatch):
    class NotPng(FakeQr):
        def post(self, url, data=None, **kwargs):
            if url.endswith("/passport/qrcode/get"):
                return Reply({"code": 0, "data": {"uuid": "u", "seq": "1", "qrcode": base64.b64encode(b"nope").decode()}})
            return super().post(url, data, **kwargs)
    use(monkeypatch, NotPng([]))
    with pytest.raises(HosterParseError, match="QR 이미지"):
        terabox_login.qr_start()


def test_qr_poll_route_stores_the_cookie_without_returning_it(monkeypatch):
    from api.routes import settings as routes
    saved = {}
    monkeypatch.setattr(routes.terabox_login, "qr_poll", lambda handle: {"status": "done", "ndus": "qr-cookie"})
    monkeypatch.setattr(routes, "save_config", lambda values: saved.update(values))
    reply = routes.terabox_qr_poll({"handle": "h"})
    assert reply == {"success": True, "status": "done"}
    assert saved == {"terabox_ndus": "qr-cookie"}


def test_qr_uses_the_current_official_web_login_origin_and_context(monkeypatch):
    fake = FakeQr([])
    page_urls = []
    original_get = fake.get
    def record_get(url, **kwargs):
        page_urls.append(url)
        return original_get(url, **kwargs)
    fake.get = record_get
    use(monkeypatch, fake)
    terabox_login.qr_start()
    assert page_urls == ["https://www.terabox.com/ai/index"]
    assert fake.headers["Origin"] == "https://www.terabox.com"
    assert fake.params["jsToken"] == "page-token"
    assert fake.params["app_id"] == "250528"
    assert fake.posts[0][1]["psign"] == "0"


def started(monkeypatch, replies):
    fake = FakeQr(replies)
    use(monkeypatch, fake)
    return fake, terabox_login.qr_start()["handle"]


def test_poll_asks_for_the_cookie_in_the_body_like_the_official_pc_client(monkeypatch):
    fake, handle = started(monkeypatch, [{"code": 39}])
    terabox_login.qr_poll(handle)
    sent = fake.posts[-1][1]
    assert sent["need_extra"] == '["ndus", "uid"]'
    assert sent["first_referer"] == ""


def test_approval_with_the_cookie_on_two_domains_still_completes(monkeypatch):
    fake, handle = started(monkeypatch, [{"code": 0, "data": {"userid": "x"}}])
    assert terabox_login.qr_poll(handle)["status"] == "waiting_confirm"
    fake.cookies.set("ndus", "other", domain=".1024terabox.com")
    fake.cookies.set("ndus", "approved", domain=".terabox.com")
    fake.replies.append({"code": 0})
    assert terabox_login.qr_poll(handle) == {"status": "done", "ndus": "approved"}


def test_approved_cookie_the_server_refuses_is_reported_not_returned(monkeypatch):
    fake, handle = started(monkeypatch, [{"code": 0, "data": {"ndus": "dead"}}])

    def refuse(origin, ndus, proxies):
        raise HosterParseError("로그인 확인 오류 -6")

    monkeypatch.setattr(terabox_login, "verify_ndus", refuse)
    with pytest.raises(HosterParseError):
        terabox_login.qr_poll(handle)


def test_poll_log_carries_the_step_and_code_but_no_secret(monkeypatch, capsys):
    fake, handle = started(monkeypatch, [{"code": 39}, {"code": 0, "data": {"ndus": "secret-cookie"}}])
    terabox_login.qr_poll(handle)
    assert "step=0 code=39" in capsys.readouterr().out
    terabox_login.qr_poll(handle)
    out = capsys.readouterr().out
    assert "code=0" in out and "secret-cookie" not in out and "u1" not in out


def test_network_failure_on_start_is_a_clean_error(monkeypatch):
    fake = FakeQr([])
    use(monkeypatch, fake)

    def boom(url, **kwargs):
        raise requests.ConnectionError("https://www.terabox.com/?jsToken=leak")

    fake.get = boom
    with pytest.raises(HosterParseError) as caught:
        terabox_login.qr_start()
    assert "leak" not in str(caught.value)


def test_malformed_image_is_a_clean_error(monkeypatch):
    fake = FakeQr([])
    use(monkeypatch, fake)
    original = fake.post

    def post(url, data=None, **kwargs):
        reply = original(url, data=data, **kwargs)
        reply.payload["data"]["qrcode"] = "not base64!"
        return reply

    fake.post = post
    with pytest.raises(HosterParseError):
        terabox_login.qr_start()


def test_a_timed_out_poll_keeps_waiting_instead_of_abandoning_the_qr(monkeypatch):
    fake, handle = started(monkeypatch, [{"code": 39}])
    original = fake.post

    def timeout(url, data=None, **kwargs):
        raise requests.ReadTimeout("slow")

    fake.post = timeout
    assert terabox_login.qr_poll(handle) == {"status": "waiting_scan"}
    fake.post = original
    assert terabox_login.qr_poll(handle) == {"status": "waiting_scan"}


def test_an_unreachable_check_keeps_the_approved_cookie_for_the_next_poll(monkeypatch):
    fake, handle = started(monkeypatch, [{"code": 0, "data": {"ndus": "approved"}}])

    def unreachable(origin, ndus, proxies):
        raise terabox_login.TeraboxUnreachable("down")

    monkeypatch.setattr(terabox_login, "verify_ndus", unreachable)
    assert terabox_login.qr_poll(handle) == {"status": "waiting_confirm"}
    monkeypatch.setattr(terabox_login, "verify_ndus", lambda origin, ndus, proxies: None)
    posts_before = len(fake.posts)
    assert terabox_login.qr_poll(handle) == {"status": "done", "ndus": "approved"}
    assert len(fake.posts) == posts_before


def test_approval_is_checked_on_the_regional_host_the_reply_names(monkeypatch):
    fake = FakeQr([{"code": 0, "data": {"ndus": "qr-cookie", "region_domain_prefix": "jp"}}])
    use(monkeypatch, fake)
    checked = []
    monkeypatch.setattr(terabox_login, "verify_ndus", lambda origin, ndus, proxies: checked.append(origin))
    handle = terabox_login.qr_start()["handle"]
    assert terabox_login.qr_poll(handle)["status"] == "done"
    assert checked == ["https://jp.terabox.com"]


def test_a_malformed_region_prefix_cannot_move_the_check_to_another_host(monkeypatch):
    fake = FakeQr([{"code": 0, "data": {"ndus": "qr-cookie", "region_domain_prefix": "evil.example.org/#"}}])
    use(monkeypatch, fake)
    checked = []
    monkeypatch.setattr(terabox_login, "verify_ndus", lambda origin, ndus, proxies: checked.append(origin))
    handle = terabox_login.qr_start()["handle"]
    assert terabox_login.qr_poll(handle)["status"] == "done"
    assert checked == ["https://www.terabox.com"]
