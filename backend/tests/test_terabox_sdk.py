import base64
import hashlib
import http.server
import json
import threading
import time

import pytest
import requests

from core import terabox_sdk
from core.hoster_common import HosterParseError

GRANT = terabox_sdk.ShareGrant(
    owner="11", share_id="22", fs_id="33", md5="b" * 32, sekey="share-key",
    dlink="https://d.1024tera.com/file/x?fid=9&sign=signed%3D&expires=5&clienttype=7&path=/forged",
)
TOKEN = "a" * 64
ORIGIN = "https://www.terabox.com"
NDUS = "fixture-account-cookie"


class Reply:
    def __init__(self, payload=None, text="", status=200, headers=None):
        self.payload = payload
        self.text = text
        self.status_code = status
        self.headers = headers or {}

    def json(self):
        if self.payload is None:
            raise ValueError("not json")
        return self.payload


class FakeAccount:
    def __init__(self, located=None, check=None):
        self.headers = {}
        self.proxies = {}
        self.cookies = requests.cookies.RequestsCookieJar()
        self.located = located or {"max_conn": 4, "urls": [{"url": "https://d13.freeterabox.com/x?sign=y"}]}
        self.check = check or {"errno": 0, "uk": 4242}
        self.located_query = None
        self.report = {"errno": 0, "uinfo": base64.b64encode(terabox_sdk._rc4(b"runtime-key", b"4242")).decode()}

    def get(self, url, params=None, timeout=None):
        if "/main" in url:
            return Reply(text=f'fn%28%22{TOKEN}%22%29')
        if url.endswith("/api/check/login"):
            assert params["jsToken"] == TOKEN
            return Reply(self.check)
        assert url.endswith("/rest/2.0/pcs/file")
        self.located_query = params
        return Reply(self.located)

    def post(self, url, params=None, data=None, timeout=None):
        assert url.endswith("/api/report/user") and data["action"] == "pc_uniyunguanjia_login"
        return Reply(self.report)


def test_rc4_matches_the_published_vector():
    assert terabox_sdk._rc4(b"Plaintext", b"Key").hex().upper() == "BBF316E8D940AF0AD3"


def test_runtime_key_rejects_a_malformed_token():
    with pytest.raises(HosterParseError):
        terabox_sdk.runtime_key("not base64!", "4242")


def test_request_nonce_binds_cookie_account_key_time_and_device():
    inner = hashlib.sha1(b"cookie").hexdigest().encode() + b"4242" + b"\x00key" + b"100" + b"device"
    assert terabox_sdk.request_nonce("cookie", "4242", b"\x00key", 100, "device") == hashlib.sha1(inner).hexdigest()


def test_locate_looks_up_a_share_by_md5_with_its_signed_grant(monkeypatch):
    fake = FakeAccount()
    monkeypatch.setattr(terabox_sdk.requests, "Session", lambda: fake)
    links = terabox_sdk.locate_candidates("https://www.1024tera.com", "cookie", GRANT, None)
    query = fake.located_query
    assert links == ["https://d13.freeterabox.com/x?sign=y"]
    assert query["path"] == GRANT.md5
    assert query["method"] == "locatedownload" and query["clienttype"] == "9" and query["app_id"] == "250528"
    assert query["product"] == "share" and query["primaryid"] == "22" and query["uk"] == "11"
    assert query["fid_list"] == "[33]" and json.loads(query["extra"]) == {"sekey": "share-key"}
    assert query["fid"] == "9" and query["sign"] == "signed=" and query["expires"] == "5"


def test_locate_uses_the_sdk_identity_for_issuance(monkeypatch):
    fake = FakeAccount()
    monkeypatch.setattr(terabox_sdk.requests, "Session", lambda: fake)
    terabox_sdk.locate_candidates("https://www.1024tera.com", "cookie", GRANT, None)
    assert fake.headers["User-Agent"] == terabox_sdk.SDK_USER_AGENT


def test_locate_refuses_when_the_cookie_is_not_logged_in(monkeypatch):
    fake = FakeAccount(check={"errno": -6})
    monkeypatch.setattr(terabox_sdk.requests, "Session", lambda: fake)
    with pytest.raises(HosterParseError, match="-6"):
        terabox_sdk.locate_candidates("https://www.1024tera.com", "cookie", GRANT, None)


def test_network_failure_becomes_a_parse_error_without_the_signed_url(monkeypatch):
    fake = FakeAccount()

    def explode(url, params=None, timeout=None):
        raise requests.ConnectionError("https://secret.example.test/?sign=leak")

    fake.get = explode
    monkeypatch.setattr(terabox_sdk.requests, "Session", lambda: fake)
    with pytest.raises(HosterParseError) as caught:
        terabox_sdk.locate_candidates("https://www.1024tera.com", "cookie", GRANT, None)
    assert "leak" not in str(caught.value)


def test_verify_ndus_passes_for_a_logged_in_cookie_and_refuses_otherwise(monkeypatch):
    monkeypatch.setattr(terabox_sdk.requests, "Session", lambda: FakeAccount())
    terabox_sdk.verify_ndus("https://www.terabox.com", "cookie", None)
    monkeypatch.setattr(terabox_sdk.requests, "Session", lambda: FakeAccount(check={"errno": -6}))
    with pytest.raises(HosterParseError):
        terabox_sdk.verify_ndus("https://www.terabox.com", "cookie", None)


def test_parse_candidates_keeps_server_order_of_unique_plain_https_links():
    links = terabox_sdk.parse_candidates({"urls": [
        {"url": "http://plain.example.test/a"},
        {"url": "https://one.example.test/a"},
        {"url": "https://one.example.test/a"},
        {"url": "https://encrypted.example.test/a", "is_encrypt": 1},
        {"url": "https://two.example.test/a"},
    ], "bakurls": [{"url": "https://three.example.test/a"}]})
    assert links == ["https://one.example.test/a", "https://two.example.test/a", "https://three.example.test/a"]


@pytest.mark.parametrize("payload", [
    {"errno": 31362, "urls": [{"url": "https://a.example.test/"}]},
    {"error_code": 31045, "urls": [{"url": "https://a.example.test/"}]},
    {"is_encrypt": 1, "urls": [{"url": "https://a.example.test/"}]},
    {"urls": []},
    {"urls": [{"url": "http://a.example.test/"}]},
])
def test_parse_candidates_refuses_what_this_receiver_cannot_use(payload):
    with pytest.raises(HosterParseError):
        terabox_sdk.parse_candidates(payload)


def test_choose_fastest_takes_a_later_server_only_past_the_margin():
    rates = {"a": 100.0, "b": 124.0, "c": 126.0}
    assert terabox_sdk.choose_fastest(["a", "b", "c"], rates.__getitem__) == "c"
    rates = {"a": 100.0, "b": 124.0}
    assert terabox_sdk.choose_fastest(["a", "b"], rates.__getitem__) == "a"


def test_choose_fastest_ignores_a_refusing_first_server():
    rates = {"a": 0.0, "b": 5.0}
    assert terabox_sdk.choose_fastest(["a", "b"], rates.__getitem__) == "b"


def test_choose_fastest_refuses_when_no_server_answers():
    with pytest.raises(HosterParseError):
        terabox_sdk.choose_fastest(["a", "b"], lambda link: 0.0)


def test_choose_fastest_measures_at_most_four_servers():
    seen = []

    def measure(link):
        seen.append(link)
        return 1.0

    terabox_sdk.choose_fastest(list("abcdef"), measure)
    assert seen == list("abcd")


def test_small_file_takes_the_first_server_that_answers_without_comparing(monkeypatch):
    seen = []

    def rate(url, offset, length, ndus, domain, referer):
        seen.append((url, offset, length))
        return {"a": 0.0, "b": 1.0, "c": 9.0}[url]

    monkeypatch.setattr(terabox_sdk, "_measure_rate", rate)
    assert terabox_sdk.fastest_link(["a", "b", "c"], 1000, "", "r", lambda url: "") == "b"
    assert seen == [("a", 500, 500), ("b", 500, 500)]


@pytest.mark.parametrize("size", [1000, 1024 ** 3])
def test_fastest_link_refuses_when_every_server_refuses(monkeypatch, size):
    monkeypatch.setattr(terabox_sdk, "_measure_rate", lambda *a: 0.0)
    with pytest.raises(HosterParseError):
        terabox_sdk.fastest_link(["a"], size, "", "r", lambda url: "")


def test_fastest_link_measures_large_files_mid_file(monkeypatch):
    calls = []

    def rate(url, offset, length, ndus, domain, referer):
        calls.append((offset, length, referer))
        return {"a": 1.0, "b": 9.0}[url]

    monkeypatch.setattr(terabox_sdk, "_measure_rate", rate)
    size = 1024 ** 3
    assert terabox_sdk.fastest_link(["a", "b"], size, "", "r", lambda url: "") == "b"
    assert calls == [(size // 2, terabox_sdk.PROBE_BYTES, "r")] * 2


class RangeServer:
    """A real HTTP server, so the probe runs through the real requests and urllib3 read path."""

    def __init__(self, handle):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                handle(self)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/f"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_measure_rate_reads_a_bounded_range_with_the_sdk_identity():
    seen = {}

    def handle(request):
        seen.update(request.headers)
        body = b"x" * terabox_sdk.PROBE_BYTES
        request.send_response(206)
        request.send_header("Content-Length", str(len(body)))
        request.end_headers()
        request.wfile.write(body)

    server = RangeServer(handle)
    try:
        assert terabox_sdk._measure_rate(server.url, 100, terabox_sdk.PROBE_BYTES, "", "", "https://r.example.test/") > 0
    finally:
        server.close()
    assert seen["Range"] == f"bytes=100-{100 + terabox_sdk.PROBE_BYTES - 1}"
    assert seen["User-Agent"] == terabox_sdk.SDK_USER_AGENT
    assert seen["Referer"] == "https://r.example.test/"


def test_measure_rate_gives_a_refusal_no_rate():
    def handle(request):
        request.send_response(403)
        request.send_header("Content-Length", "0")
        request.end_headers()

    server = RangeServer(handle)
    try:
        assert terabox_sdk._measure_rate(server.url, 0, 1024, "", "", "r") == 0.0
    finally:
        server.close()


def test_measure_rate_gives_a_tiny_answer_no_rate():
    def handle(request):
        request.send_response(206)
        request.send_header("Content-Length", "4")
        request.end_headers()
        request.wfile.write(b"tiny")

    server = RangeServer(handle)
    try:
        assert terabox_sdk._measure_rate(server.url, 0, terabox_sdk.PROBE_BYTES, "", "", "r") == 0.0
    finally:
        server.close()


def test_measure_rate_stops_on_time_against_a_dribbling_server(monkeypatch):
    monkeypatch.setattr(terabox_sdk, "PROBE_SECONDS", 0.5)

    def handle(request):
        request.send_response(206)
        request.send_header("Content-Length", str(terabox_sdk.PROBE_BYTES))
        request.end_headers()
        try:
            while True:
                request.wfile.write(b"x" * 64)
                request.wfile.flush()
                time.sleep(0.05)
        except OSError:
            pass

    server = RangeServer(handle)
    started = time.monotonic()
    try:
        assert terabox_sdk._measure_rate(server.url, 0, terabox_sdk.PROBE_BYTES, "", "", "r") == 0.0
    finally:
        server.close()
    assert time.monotonic() - started < 2


def test_measure_rate_survives_a_dead_server():
    assert terabox_sdk._measure_rate("http://127.0.0.1:9/f", 0, 1024, "", "", "r") == 0.0


def test_measure_rate_sends_the_account_cookie_only_to_its_domain_and_only_over_https(monkeypatch):
    sessions = []
    real_session = requests.Session

    def recording():
        session = real_session()
        session.get = lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("stop"))
        sessions.append(session)
        return session

    monkeypatch.setattr(terabox_sdk.requests, "Session", recording)
    terabox_sdk._measure_rate("https://d.1024tera.com/", 0, 1024, "cookie", "1024tera.com", "r")
    terabox_sdk._measure_rate("https://d13.freeterabox.com/", 0, 1024, "cookie", "", "r")
    assert [(c.name, c.domain, c.secure) for c in sessions[0].cookies] == [("ndus", ".1024tera.com", True)]
    assert list(sessions[1].cookies) == []


@pytest.mark.parametrize("payload", [{"urls": 1}, {"urls": [{"url": "https://[x/a"}]}])
def test_parse_candidates_refuses_malformed_links_as_a_parse_error(payload):
    with pytest.raises(HosterParseError):
        terabox_sdk.parse_candidates(payload)


def test_malformed_token_escape_reads_as_no_token():
    assert terabox_sdk.extract_js_token('"jsToken":"\\q"') == ""


def test_first_cookie_survives_the_same_name_on_two_domains():
    jar = requests.cookies.RequestsCookieJar()
    jar.set("ndus", "other", domain=".terabox.com")
    jar.set("ndus", "here", domain=".1024terabox.com")
    assert terabox_sdk.first_cookie(jar, "ndus", "www.1024terabox.com") == "here"
    assert terabox_sdk.first_cookie(jar, "ndus", "www.nephobox.com") == ""
    assert terabox_sdk.first_cookie(jar, "missing", "www.terabox.com") == ""


class RegionalAccount(FakeAccount):
    """A session TeraBox accepts only on ``home``; elsewhere -6 names the right prefix."""

    def __init__(self, home, prefix):
        super().__init__()
        self.home = home
        self.prefix = prefix
        self.visited = []

    def get(self, url, params=None, timeout=None):
        if url.endswith("/api/check/login"):
            self.visited.append(url.split("/api/")[0])
            if not url.startswith(self.home):
                return Reply({"errno": -6}, headers={"url-domain-prefix": self.prefix})
        return super().get(url, params=params, timeout=timeout)


def test_wrong_region_moves_to_the_host_terabox_names():
    fake = RegionalAccount("https://jp.terabox.com", "jp")
    account = terabox_sdk._open_account(fake, ORIGIN, NDUS, None)
    assert account["origin"] == "https://jp.terabox.com" and account["uk"] == "4242"
    assert fake.visited == [ORIGIN, "https://jp.terabox.com"]


def test_a_real_expired_login_is_still_refused():
    fake = FakeAccount(check={"errno": -6})
    with pytest.raises(HosterParseError, match="-6"):
        terabox_sdk._open_account(fake, ORIGIN, NDUS, None)


def test_a_region_loop_ends_in_an_error_not_a_hang():
    fake = RegionalAccount("https://never.terabox.com", "jp")
    with pytest.raises(HosterParseError, match="-6"):
        terabox_sdk._open_account(fake, ORIGIN, NDUS, None)
    assert len(fake.visited) == 2


@pytest.mark.parametrize("origin, prefix, expected", [
    ("https://www.terabox.com", "jp", "https://jp.terabox.com"),
    ("https://www.terabox.com", "www", "https://www.terabox.com"),
    ("https://terabox.com", "jp", "https://jp.terabox.com"),
    ("https://jp.1024terabox.com", "dm", "https://dm.1024terabox.com"),
    ("https://www.terabox.com", "", "https://www.terabox.com"),
    ("https://www.terabox.com", "evil.example.org/#", "https://www.terabox.com"),
    ("https://www.terabox.com", "-bad", "https://www.terabox.com"),
])
def test_regional_origin_only_swaps_the_first_label(origin, prefix, expected):
    assert terabox_sdk.regional_origin(origin, prefix) == expected


class TokenlessOffHome(RegionalAccount):
    def get(self, url, params=None, timeout=None):
        if "/main" in url and not url.startswith(self.home):
            return Reply(text="<html>no token here</html>")
        if url.endswith("/api/check/login") and not url.startswith(self.home):
            self.visited.append(url.split("/api/")[0])
            return Reply({"errno": -6}, headers={"url-domain-prefix": self.prefix})
        return super().get(url, params=params, timeout=timeout)


def test_a_wrong_region_page_without_a_token_still_finds_the_right_host():
    fake = TokenlessOffHome("https://jp.terabox.com", "jp")
    assert terabox_sdk._open_account(fake, ORIGIN, NDUS, None)["origin"] == "https://jp.terabox.com"


def test_a_right_region_page_without_a_token_is_still_an_error():
    class NoToken(FakeAccount):
        def get(self, url, params=None, timeout=None):
            if "/main" in url:
                return Reply(text="<html></html>")
            return super().get(url, params={**(params or {}), "jsToken": TOKEN}, timeout=timeout)
    with pytest.raises(HosterParseError, match="인증 정보"):
        terabox_sdk._open_account(NoToken(), ORIGIN, NDUS, None)


@pytest.mark.parametrize("failing", ["/main", "/api/check/login"])
def test_a_server_error_during_the_check_counts_as_unreachable(failing):
    class Down(FakeAccount):
        def get(self, url, params=None, timeout=None):
            if failing in url:
                return Reply(status=503)
            return super().get(url, params=params, timeout=timeout)
    with pytest.raises(terabox_sdk.TeraboxUnreachable):
        terabox_sdk._open_account(Down(), ORIGIN, NDUS, None)


def test_the_referer_follows_a_region_hop():
    fake = RegionalAccount("https://jp.terabox.com", "jp")
    terabox_sdk._open_account(fake, ORIGIN, NDUS, None)
    assert fake.headers["Referer"] == "https://jp.terabox.com/"
