import json
from types import SimpleNamespace

import pytest
import requests
from fastapi import HTTPException

from api.routes import downloads
from core import hoster_legacy_sites as legacy
from core import error_messages, hoster_parsers, terabox_sdk, terabox_share
from core.hoster_common import HosterParseError

TOKEN = "a" * 64
SHARE_URL = "https://www.terabox.com/s/1fixture"


class Reply:
    def __init__(self, payload=None, text="", status=200, url="https://www.terabox.com/sharing/link", headers=None):
        self.headers = headers or {}
        self._payload = payload
        self.text = text
        self.status_code = status
        self.url = url

    def json(self):
        return self._payload


class FakeSession:
    """Answers the share API the way the web app sees it and records each call."""

    def __init__(self, rows, listings=None, errno=None, dlink="https://cdn.example.test/file?sign=x"):
        self.headers = {}
        self.proxies = {}
        self.cookies = requests.cookies.RequestsCookieJar()
        self.calls = []
        self.rows = rows
        self.listings = listings or {}
        self.errno = errno or {}
        self.dlink = dlink

    def _api(self, path, params, data):
        self.calls.append((path, dict(params), dict(data or {})))
        if params.get("jsToken") != TOKEN:
            return Reply({"errno": -1})
        if path in self.errno:
            return Reply({"errno": self.errno[path]})
        if path == "/share/verify":
            assert data["pwd"] == "pw"
            return Reply({"errno": 0, "randsk": "fixture%2Bsecret"})
        if path == "/api/shorturlinfo":
            assert params["shorturl"] == "1fixture"
            return Reply({"errno": 0, "uk_str": "11", "shareid": "22", "sign": "s", "timestamp": "123",
                          "randsk": "info%2Bsecret", "list": self.rows})
        if path == "/share/list":
            page = int(params["page"])
            rows = self.listings[params["dir"]]
            return Reply({"errno": 0, "list": rows[(page - 1) * 100:page * 100],
                          "has_more": int(len(rows) > page * 100)})
        if path == "/share/download":
            assert data["product"] == "share" and data["primaryid"] == "22" and data["uk"] == "11"
            self.requested = data
            return Reply({"errno": 0, "dlink": self.dlink})
        raise AssertionError(path)

    def get(self, url, params=None, timeout=None):
        path = url.split("terabox.com", 1)[1]
        if path == "/sharing/link":
            return Reply(text=f'<html>"jsToken":"{TOKEN}"</html>')
        return self._api(path, params, None)

    def post(self, url, params=None, data=None, timeout=None):
        return self._api(url.split("terabox.com", 1)[1], params, data)


def row(fs_id, name, size=8, directory=False, path=None):
    return {"fs_id": str(fs_id), "server_filename": name, "size": str(size),
            "isdir": str(int(directory)), "path": path or "/owner/" + name}


def resolve(monkeypatch, session, url=SHARE_URL):
    monkeypatch.setattr(terabox_share.requests, "Session", lambda: session)
    return terabox_share.parse_terabox_share_sync(url)


def test_single_file_share_returns_signed_link_and_file_info(monkeypatch):
    session = FakeSession([row(2, "root.bin", size=5 * 1024 ** 3)])
    result = resolve(monkeypatch, session)
    assert result["download_link"] == "https://cdn.example.test/file?sign=x"
    assert result["file_info"]["name"] == "root.bin"
    assert result["file_info"]["size"].endswith("GB")
    assert result["referer"] == "https://www.terabox.com/sharing/link?surl=fixture"
    assert session.requested["fid_list"] == "[2]"


def test_download_carries_the_share_secret_from_the_page_info(monkeypatch):
    session = FakeSession([row(2, "root.bin")])
    resolve(monkeypatch, session)
    assert json.loads(session.requested["extra"]) == {"sekey": "info+secret"}


def test_password_is_verified_and_its_key_wins(monkeypatch):
    session = FakeSession([row(2, "root.bin")])
    resolve(monkeypatch, session, SHARE_URL + "?pwd=pw")
    assert [call[0] for call in session.calls][:2] == ["/share/verify", "/api/shorturlinfo"]
    assert json.loads(session.requested["extra"]) == {"sekey": "fixture+secret"}


def test_folder_with_one_file_is_followed(monkeypatch):
    session = FakeSession([row(1, "dir", directory=True, path="/owner/dir")],
                          listings={"/owner/dir": [row(5, "inner.bin", path="/owner/dir/inner.bin")]})
    result = resolve(monkeypatch, session)
    assert result["file_info"]["name"] == "inner.bin"
    assert session.requested["fid_list"] == "[5]"


def test_listing_pages_through_a_large_folder(monkeypatch):
    many = [row(100 + i, f"f{i}.bin", path=f"/owner/dir/f{i}.bin") for i in range(101)]
    session = FakeSession([row(1, "dir", directory=True, path="/owner/dir")], listings={"/owner/dir": many})
    result = resolve(monkeypatch, session)
    assert len(result["split_into"]) == 101
    assert sum(1 for call in session.calls if call[0] == "/share/list") == 2


def test_several_files_name_a_row_each_and_request_no_link_yet(monkeypatch):
    session = FakeSession([row(1, "a.bin"), row(2, "b.bin", size=2048)])
    result = resolve(monkeypatch, session, SHARE_URL + "?pwd=pw")
    assert not hasattr(session, "requested") and not result["download_link"]
    assert [item["name"] for item in result["split_into"]] == ["a.bin", "b.bin"]
    assert result["split_into"][1]["size"] == "2.00 KB"
    assert result["split_into"][1]["url"] == SHARE_URL + "?fid=2&pwd=pw"


def test_every_form_of_a_share_link_splits_into_the_same_row_urls(monkeypatch):
    urls = set()
    for form in (SHARE_URL, "https://terabox.com/s/1fixture", "https://www.terabox.com/sharing/link?surl=fixture"):
        result = resolve(monkeypatch, FakeSession([row(1, "a.bin"), row(2, "b.bin")]), form)
        urls.add(result["split_into"][0]["url"])
    assert urls == {SHARE_URL + "?fid=1"}


def test_a_new_password_keeps_the_row_url_in_the_split_form():
    assert terabox_share.with_password(SHARE_URL + "?fid=2", "pw") == SHARE_URL + "?fid=2&pwd=pw"


def test_a_row_for_one_file_serves_that_file_and_does_not_split_again(monkeypatch):
    session = FakeSession([row(1, "a.bin"), row(2, "b.bin")])
    result = resolve(monkeypatch, session, SHARE_URL + "?fid=2")
    assert session.requested["fid_list"] == "[2]" and result["file_info"]["name"] == "b.bin"
    assert result["split_into"] is None


def test_a_row_for_one_file_stops_opening_folders_once_it_is_found(monkeypatch):
    session = FakeSession(
        [row(1, "a.bin"), row(9, "dir", directory=True, path="/owner/dir")],
        listings={"/owner/dir": [row(2, "b.bin")]},
    )
    resolve(monkeypatch, session, SHARE_URL + "?fid=1")
    assert not any(call[0] == "/share/list" for call in session.calls)


def test_a_regional_share_host_keeps_its_own_name():
    assert terabox_share.parse_share_link("https://dm.terabox.com/s/1abc")[0] == "https://dm.terabox.com"
    assert terabox_share.parse_share_link("https://terabox.com/s/1abc")[0] == "https://www.terabox.com"


class RegionalShare(FakeSession):
    """Answers -6 and names ``jp`` until the request arrives on the regional host."""

    def get(self, url, params=None, timeout=None):
        if "/sharing/link" not in url and not url.startswith("https://jp."):
            return Reply({"errno": -6}, headers={"url-domain-prefix": "jp"})
        return super().get(url, params=params, timeout=timeout)

    def post(self, url, params=None, data=None, timeout=None):
        if not url.startswith("https://jp."):
            return Reply({"errno": -6}, headers={"url-domain-prefix": "jp"})
        return super().post(url, params=params, data=data, timeout=timeout)


def test_a_wrong_region_answer_moves_the_share_instead_of_asking_for_a_login(monkeypatch):
    result = resolve(monkeypatch, RegionalShare([row(1, "a.bin")]))
    assert result["file_info"]["name"] == "a.bin"
    assert result["referer"].startswith("https://jp.terabox.com/")


class ForeverMoving(FakeSession):
    def get(self, url, params=None, timeout=None):
        if "/sharing/link" in url:
            return super().get(url, params=params, timeout=timeout)
        self.calls.append(url)
        prefix = "b" if url.startswith("https://a.") else "a"
        return Reply({"errno": -6}, headers={"url-domain-prefix": prefix})


def test_a_region_loop_ends_as_login_required(monkeypatch):
    session = ForeverMoving([row(1, "a.bin")])
    with pytest.raises(HosterParseError):
        resolve(monkeypatch, session)
    assert len(session.calls) == 3


def test_a_file_removed_from_the_share_is_reported(monkeypatch):
    session = FakeSession([row(1, "a.bin")])
    with pytest.raises(HosterParseError, match="찾지 못했습니다"):
        resolve(monkeypatch, session, SHARE_URL + "?fid=9")


def test_a_single_file_share_is_not_split(monkeypatch):
    assert resolve(monkeypatch, FakeSession([row(1, "a.bin")]))["split_into"] is None


def test_an_oversized_share_is_refused_not_truncated(monkeypatch):
    many = [row(i + 1, f"f{i}.bin") for i in range(terabox_share._MAX_SHARE_FILES + 1)]
    with pytest.raises(HosterParseError, match="너무 많습니다"):
        resolve(monkeypatch, FakeSession(many))


@pytest.mark.parametrize("errno,message", [(-9, "암호"), (-12, "암호"), (2, "만료"), (12, "만료")])
def test_share_errors_are_named(monkeypatch, errno, message):
    session = FakeSession([row(2, "root.bin")], errno={"/api/shorturlinfo": errno})
    with pytest.raises(HosterParseError, match=message):
        resolve(monkeypatch, session)


def test_login_requirement_is_reported_not_retried(monkeypatch):
    session = FakeSession([row(2, "root.bin")], errno={"/share/download": -6})
    with pytest.raises(HosterParseError, match="로그인"):
        resolve(monkeypatch, session)
    assert sum(1 for call in session.calls if call[0] == "/share/download") == 1


def test_non_https_link_is_rejected(monkeypatch):
    session = FakeSession([row(2, "root.bin")], dlink="http://cdn.example.test/file")
    with pytest.raises(HosterParseError, match="HTTPS"):
        resolve(monkeypatch, session)


@pytest.mark.parametrize("url,code,password", [
    ("https://www.terabox.com/s/1AbC_-9", "AbC_-9", ""),
    ("https://terabox.app/sharing/link?surl=AbC", "AbC", ""),
    ("https://1024terabox.com/s/1AbC?pwd=zz9", "AbC", "zz9"),
    ("https://www.1024tera.com/wap/share/code?surl=AbC", "AbC", ""),
    ("https://www.1024tera.com/wap/share/filelist?surl=AbC&pwd=q1", "AbC", "q1"),
])
def test_share_link_forms(url, code, password):
    _, parsed_code, parsed_password = terabox_share.parse_share_link(url)
    assert (parsed_code, parsed_password) == (code, password)


@pytest.mark.parametrize("url", [
    "http://www.terabox.com/s/1abc",
    "https://terabox.com.evil.example/s/1abc",
    "https://www.terabox.com/s/abc",
    "https://www.terabox.com/other",
])
def test_foreign_or_malformed_links_are_refused(url):
    with pytest.raises(HosterParseError):
        terabox_share.parse_share_link(url)


def test_js_token_is_read_from_either_page_encoding():
    assert terabox_share.extract_js_token(f"x fn%28%22{TOKEN}%22%29 y") == TOKEN
    assert terabox_share.extract_js_token(f'x fn("{TOKEN}") y') == TOKEN
    assert terabox_share.extract_js_token('{"jsToken":"abc"}') == "abc"
    assert terabox_share.extract_js_token("<html></html>") == ""


def test_registry_resolves_terabox_without_a_browser(monkeypatch):
    session = FakeSession([row(2, "root.bin")])
    monkeypatch.setattr(terabox_share.requests, "Session", lambda: session)
    assert legacy.parse_teraboxapp_sync(SHARE_URL)["file_info"]["name"] == "root.bin"


def test_download_errno_2_is_a_refusal_not_an_expired_share(monkeypatch):
    session = FakeSession([row(2, "root.bin")], errno={"/share/download": 2})
    with pytest.raises(HosterParseError, match="거절") as caught:
        resolve(monkeypatch, session)
    assert "만료" not in str(caught.value)


@pytest.mark.parametrize("url,expected", [
    ("https://www.terabox.com/s/1AbC", "https://www.terabox.com/s/1AbC?pwd=x%26y"),
    ("https://www.terabox.com/s/1AbC?pwd=old", "https://www.terabox.com/s/1AbC?pwd=x%26y"),
    ("https://www.1024tera.com/wap/share/code?surl=AbC", "https://www.1024tera.com/wap/share/code?surl=AbC&pwd=x%26y"),
])
def test_with_password_sets_pwd_once(url, expected):
    assert terabox_share.with_password(url, "x&y") == expected
    assert terabox_share.parse_share_link(expected)[2] == "x&y"


def test_late_password_lands_in_the_stored_links():
    link = "https://www.1024tera.com/wap/share/code?surl=AbC"
    req = SimpleNamespace(url=link, original_url=link)
    downloads._apply_share_password(req, "q1")
    assert terabox_share.parse_share_link(req.url)[2] == "q1"
    assert terabox_share.parse_share_link(req.original_url)[2] == "q1"

    other = SimpleNamespace(url="https://example.com/f", original_url=None)
    with pytest.raises(HTTPException) as refused:
        downloads._apply_share_password(other, "q1")
    assert refused.value.status_code == 400


def test_account_cookie_is_not_forwarded_to_an_external_signed_download(monkeypatch):
    monkeypatch.setattr(terabox_share, "get_config", lambda: {"terabox_ndus": " acct-cookie "})
    session = FakeSession([row(2, "root.bin")])
    result = resolve(monkeypatch, session)
    assert terabox_sdk.first_cookie(session.cookies, "ndus", "www.terabox.com") == "acct-cookie"
    assert "ndus" not in result["cookies"]


@pytest.mark.parametrize("url", [
    "https://www.1024tera.com/wap/share/filelist?surl=AbC",
    "https://www.1024tera.com/wap/share/code?surl=AbC",
    "https://www.terabox.com/s/1AbC",
])
def test_every_share_page_form_is_a_special_hoster_url(url):
    assert hoster_parsers.is_special_hoster_url(url)


@pytest.mark.parametrize("message,marker", [
    ("TeraBox 공유 암호가 올바르지 않습니다 (주소 뒤에 ?pwd=암호 를 붙이세요)", "추출 코드"),
    ("TeraBox가 익명 다운로드 요청을 거절했습니다 (오류 2). 로그인 계정이 필요할 수 있습니다", "ndus"),
])
def test_terabox_refusals_are_classified_with_the_next_step(message, marker):
    classified = error_messages.classify_error("parse", message)
    assert classified.kind == error_messages.KIND_AUTH_REQUIRED
    assert marker in classified.summary + classified.action


def test_retired_email_password_never_start_a_login(monkeypatch):
    monkeypatch.setattr(terabox_share, "get_config", lambda: {
        "terabox_email": "old@example.com", "terabox_password": "retired-password"
    })
    seen = []
    monkeypatch.setattr(terabox_share, "_resolve", lambda url, proxies, cookie: seen.append(cookie) or {"ok": True})
    assert terabox_share.parse_terabox_share_sync(SHARE_URL) == {"ok": True}
    assert seen == [""]


@pytest.mark.parametrize("target,expected", [
    ("https://d.1024tera.com/file?sign=x", "account-cookie"),
    ("https://data.terabox.com/file?sign=x", "account-cookie"),
    ("https://cdn.example.test/file?sign=x", None),
    ("https://terabox.com.evil.example/file?sign=x", None),
])
def test_account_cookie_reaches_only_trusted_file_servers(monkeypatch, target, expected):
    monkeypatch.setattr(terabox_share, "get_config", lambda: {"terabox_ndus": "account-cookie"})
    session = FakeSession([row(2, "root.bin")], dlink=target)
    result = resolve(monkeypatch, session)
    assert result["cookies"].get("ndus") == expected


def with_account(monkeypatch, ndus="cookie"):
    monkeypatch.setattr(terabox_share, "get_config", lambda: {"terabox_ndus": ndus})


def test_account_share_downloads_from_the_fastest_sdk_server(monkeypatch):
    with_account(monkeypatch)
    seen = {}

    def locate(origin, ndus, grant, proxies):
        seen.update(origin=origin, ndus=ndus, grant=grant)
        return ["https://data.1024tera.com/a", "https://d13.freeterabox.com/b"]

    monkeypatch.setattr(terabox_sdk, "locate_candidates", locate)
    monkeypatch.setattr(terabox_sdk, "fastest_link", lambda links, size, ndus, referer, domain_of: links[1])
    result = resolve(monkeypatch, FakeSession([{**row(2, "root.bin", size=5 * 1024 ** 3), "md5": "b" * 32}]))
    assert result["download_link"] == "https://d13.freeterabox.com/b"
    assert result["user_agent"] == terabox_sdk.SDK_USER_AGENT
    assert result["referer"] == "https://www.terabox.com/"
    assert seen["origin"] == "https://www.terabox.com" and seen["ndus"] == "cookie"
    assert seen["grant"].md5 == "b" * 32 and seen["grant"].fs_id == "2" and seen["grant"].sekey == "info+secret"
    assert seen["grant"].dlink == "https://cdn.example.test/file?sign=x"


def test_sdk_server_outside_terabox_never_receives_the_account_cookie(monkeypatch):
    with_account(monkeypatch)
    monkeypatch.setattr(terabox_sdk, "locate_candidates", lambda *a: ["https://d13.freeterabox.com/b"])
    monkeypatch.setattr(terabox_sdk, "fastest_link", lambda links, *a: links[0])
    result = resolve(monkeypatch, FakeSession([{**row(2, "root.bin"), "md5": "b" * 32}]))
    assert "ndus" not in result["cookies"]


def test_sdk_server_inside_terabox_receives_the_account_cookie(monkeypatch):
    with_account(monkeypatch)
    monkeypatch.setattr(terabox_sdk, "locate_candidates", lambda *a: ["https://data.1024tera.com/a"])
    monkeypatch.setattr(terabox_sdk, "fastest_link", lambda links, *a: links[0])
    result = resolve(monkeypatch, FakeSession([{**row(2, "root.bin"), "md5": "b" * 32}]))
    assert result["cookies"] == {"ndus": "cookie"}


def test_sdk_refusal_falls_back_to_the_web_link(monkeypatch):
    with_account(monkeypatch)

    def refuse(*args):
        raise HosterParseError("refused")

    monkeypatch.setattr(terabox_sdk, "locate_candidates", refuse)
    result = resolve(monkeypatch, FakeSession([{**row(2, "root.bin"), "md5": "b" * 32}]))
    assert result["download_link"] == "https://cdn.example.test/file?sign=x"
    assert result["user_agent"] == terabox_share.DEFAULT_HOSTER_USER_AGENT


@pytest.mark.parametrize("ndus,md5", [("", "b" * 32), ("cookie", "")])
def test_sdk_is_not_attempted_without_an_account_or_md5(monkeypatch, ndus, md5):
    with_account(monkeypatch, ndus)
    monkeypatch.setattr(terabox_sdk, "locate_candidates", lambda *a: pytest.fail("attempted SDK"))
    result = resolve(monkeypatch, FakeSession([{**row(2, "root.bin"), "md5": md5}]))
    assert result["download_link"] == "https://cdn.example.test/file?sign=x"


def test_api_follows_the_host_the_share_page_settled_on(monkeypatch):
    session = FakeSession([row(2, "root.bin")])
    settled = "https://www.1024terabox.com/sharing/link?surl=fixture"
    original_get = session.get
    hosts = []

    def get(url, params=None, timeout=None):
        hosts.append(url.split("/")[2])
        reply = original_get(url.replace("teraboxapp.com", "terabox.com").replace("1024terabox.com", "terabox.com"), params, timeout)
        reply.url = settled
        return reply

    session.get = get
    original_post = session.post

    def post(url, params=None, data=None, timeout=None):
        hosts.append(url.split("/")[2])
        return original_post(url.replace("1024terabox.com", "terabox.com"), params, data, timeout)

    session.post = post
    resolve(monkeypatch, session, "https://www.teraboxapp.com/s/1fixture")
    assert hosts[0] == "www.teraboxapp.com"
    assert set(hosts[1:]) == {"www.1024terabox.com"}


def test_share_page_cannot_redirect_the_api_off_terabox(monkeypatch):
    session = FakeSession([row(2, "root.bin")])
    original_get = session.get

    def get(url, params=None, timeout=None):
        reply = original_get(url, params, timeout)
        reply.url = "https://evil.example.test/sharing/link"
        return reply

    session.get = get
    with pytest.raises(HosterParseError):
        resolve(monkeypatch, session)


def test_account_cookie_covers_every_share_domain(monkeypatch):
    with_account(monkeypatch)
    monkeypatch.setattr(terabox_sdk, "locate_candidates", lambda *a: ["https://d13.freeterabox.com/b"])
    monkeypatch.setattr(terabox_sdk, "fastest_link", lambda links, *a: links[0])
    session = FakeSession([{**row(2, "root.bin"), "md5": "b" * 32}])
    resolve(monkeypatch, session)
    assert {c.domain for c in session.cookies if c.name == "ndus"} == {
        "." + host for host in terabox_share.TERABOX_SHARE_HOSTS
    }


def test_share_secret_cookie_on_two_domains_does_not_crash(monkeypatch):
    session = FakeSession([row(2, "root.bin")])
    session.cookies.set("BOXCLND", "other", domain=".1024tera.com")
    session.cookies.set("BOXCLND", "from%2Bcookie", domain=".terabox.com")
    original_post = session._api

    def api(path, params, data):
        reply = original_post(path, params, data)
        if path == "/api/shorturlinfo":
            reply._payload.pop("randsk")
        return reply

    session._api = api
    resolve(monkeypatch, session)
    assert json.loads(session.requested["extra"]) == {"sekey": "from+cookie"}


@pytest.mark.parametrize("raw,expected", [
    ("value-1", "value-1"),
    ("  value-1\n", "value-1"),
    ("ndus=value-1", "value-1"),
    ("lang=en; ndus=value-1; csrf=z", "value-1"),
    ("Cookie: ndus=value-1", "value-1"),
    ("", ""),
    (None, ""),
])
def test_normalize_ndus_accepts_what_people_paste(raw, expected):
    assert terabox_share.normalize_ndus(raw) == expected


@pytest.mark.parametrize("raw", ["two words", "a=1; b=2", "x" * 8193])
def test_normalize_ndus_refuses_anything_else(raw):
    with pytest.raises(HosterParseError):
        terabox_share.normalize_ndus(raw)


def test_pasted_cookie_header_reaches_the_request_as_the_bare_value(monkeypatch):
    with_account(monkeypatch, "ndus=value-1; csrf=z")
    session = FakeSession([row(2, "root.bin")])
    resolve(monkeypatch, session)
    assert {c.value for c in session.cookies if c.name == "ndus"} == {"value-1"}


def test_share_password_never_reaches_a_download_server_as_referer(monkeypatch):
    with_account(monkeypatch)
    monkeypatch.setattr(terabox_sdk, "locate_candidates", lambda *a: ["https://d13.freeterabox.com/b"])
    monkeypatch.setattr(terabox_sdk, "fastest_link", lambda links, size, ndus, referer, domain_of: links[0])
    result = resolve(monkeypatch, FakeSession([{**row(2, "root.bin"), "md5": "b" * 32}]), SHARE_URL + "?pwd=pw")
    assert "pw" not in result["referer"]


def test_sdk_servers_all_refusing_falls_back_to_the_web_link(monkeypatch):
    with_account(monkeypatch)
    monkeypatch.setattr(terabox_sdk, "locate_candidates", lambda *a: ["https://d13.freeterabox.com/b"])
    monkeypatch.setattr(terabox_sdk, "_measure_rate", lambda *a: 0.0)
    result = resolve(monkeypatch, FakeSession([{**row(2, "root.bin"), "md5": "b" * 32}]))
    assert result["download_link"] == "https://cdn.example.test/file?sign=x"


def test_network_failure_reports_no_token_or_signature(monkeypatch):
    session = FakeSession([row(2, "root.bin")])
    original_get = session.get

    def get(url, params=None, timeout=None):
        if "shorturlinfo" in url:
            raise requests.ConnectionError(f"{url}?jsToken={TOKEN}&sign=leak")
        return original_get(url, params, timeout)

    session.get = get
    with pytest.raises(HosterParseError) as caught:
        resolve(monkeypatch, session)
    assert TOKEN not in str(caught.value) and "leak" not in str(caught.value)


def test_account_cookie_is_https_only(monkeypatch):
    with_account(monkeypatch)
    monkeypatch.setattr(terabox_sdk, "locate_candidates", lambda *a: ["https://d13.freeterabox.com/b"])
    monkeypatch.setattr(terabox_sdk, "fastest_link", lambda links, *a: links[0])
    session = FakeSession([{**row(2, "root.bin"), "md5": "b" * 32}])
    resolve(monkeypatch, session)
    assert all(c.secure for c in session.cookies if c.name == "ndus")


@pytest.mark.parametrize("message", ["TeraBox 공유 요청 실패 (ConnectionError)", "TeraBox 공유 페이지 요청 실패 (SSLError)"])
def test_share_network_failure_is_retried_automatically(message):
    assert error_messages.classify_error("파싱", message).kind == error_messages.KIND_TRANSIENT
