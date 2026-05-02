# -*- coding: utf-8 -*-
"""``simple_parser`` 의 분기 커버리지를 채우기 위한 추가 테스트."""

from unittest.mock import MagicMock

import pytest

from core import simple_parser as sp


# ---------------------------------------------------------------------------
# parse_1fichier_simple_sync — 대기시간이 있는 흐름
# ---------------------------------------------------------------------------


def _make_wait_page_html(wait_seconds: int) -> str:
    """``var ct = N`` 형식의 대기페이지 HTML."""
    return f"""
    <html><body>
        <table>
            <tr>
                <td><img src="/qr.pl?k=1"></td>
                <td class="normal">
                    <span style="font-weight:bold">file.bin</span>
                    <br>
                    <span style="font-size:0.9em;font-style:italic">100 MB</span>
                </td>
            </tr>
        </table>
        <form id="f1"><input type="hidden" name="adz" value="x"></form>
        <script>var ct = {wait_seconds};</script>
    </body></html>
    """


def test_parse_simple_sync_with_wait_time_skips_actual_sleep(monkeypatch):
    """대기시간이 있을 때 ``time.sleep`` 호출 횟수만큼 카운트다운 한다."""

    get_response = MagicMock()
    get_response.status_code = 200
    get_response.text = _make_wait_page_html(60)
    get_response.headers = {}

    post_response = MagicMock()
    post_response.status_code = 302
    post_response.text = ""
    post_response.headers = {"Location": "https://a-2.1fichier.com/p1/file.bin"}

    cookie = MagicMock()
    cookie.name = "session"
    cookie.value = "v"

    scraper = MagicMock()
    scraper.cookies = [cookie]
    scraper.get.return_value = get_response
    scraper.post.return_value = post_response

    monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)
    sleep_calls = []
    monkeypatch.setattr(sp.time, "sleep", lambda s: sleep_calls.append(s))

    # download_id 없이 호출 → 대기 루프는 단순 sleep 1회만 실행
    result = sp.parse_1fichier_simple_sync(
        "https://1fichier.com/?abc",
        password=None,
        proxies=None,
        proxy_addr=None,
        download_id=None,
        sse_callback=None,
    )

    assert result["wait_time"] == 60
    assert sum(sleep_calls) == 60
    assert result["download_link"].startswith("https://a-2.1fichier.com/")


def test_parse_simple_sync_sse_callback_invoked_during_wait(monkeypatch):
    """download_id 가 있으면 카운트다운 도중 SSE 콜백이 호출된다."""

    get_response = MagicMock()
    get_response.status_code = 200
    get_response.text = _make_wait_page_html(60)
    get_response.headers = {}

    post_response = MagicMock()
    post_response.status_code = 302
    post_response.text = ""
    post_response.headers = {"Location": "https://a-2.1fichier.com/p1/file.bin"}

    scraper = MagicMock()
    scraper.cookies = []
    scraper.get.return_value = get_response
    scraper.post.return_value = post_response

    monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)
    monkeypatch.setattr(sp.time, "sleep", lambda s: None)

    # SessionLocal 모킹 — DB 검사 분기 통과
    session_mock = MagicMock()
    session_mock.__enter__.return_value.query.return_value.filter.return_value.first.return_value = None
    monkeypatch.setattr(sp, "SessionLocal", lambda: session_mock)

    sse_messages = []

    def sse_cb(msg_type, payload):
        sse_messages.append((msg_type, payload))

    sp.parse_1fichier_simple_sync(
        "https://1fichier.com/?abc",
        password=None,
        proxies=None,
        proxy_addr=None,
        download_id=42,
        sse_callback=sse_cb,
    )

    # status_update + 카운트다운 메시지가 최소 1번씩
    types = [m[0] for m in sse_messages]
    assert "status_update" in types
    assert any(t == "waiting" for t in types)


def test_parse_simple_sync_returns_none_when_stopped_during_wait(monkeypatch):
    """대기 중 cancel_signal 이 set 되면 None 반환 (DB 폴링 없음)."""
    from core import cancel_signal

    get_response = MagicMock()
    get_response.status_code = 200
    get_response.text = _make_wait_page_html(60)
    get_response.headers = {}

    scraper = MagicMock()
    scraper.cookies = []
    scraper.get.return_value = get_response

    monkeypatch.setattr(sp.cloudscraper, "create_scraper", lambda **kw: scraper)

    # 카운트다운 진입 *전* 에 cancel signal 을 set 해두면, get_event 가
    # 이미 set 된 Event 를 반환하므로 첫 wait 호출이 즉시 True 로 깨어난다.
    cancel_signal.reset_all_for_tests()
    cancel_signal.signal_cancel(42)

    try:
        result = sp.parse_1fichier_simple_sync(
            "https://1fichier.com/?abc",
            download_id=42,
        )
        assert result is None
    finally:
        cancel_signal.reset_all_for_tests()


# ---------------------------------------------------------------------------
# extract_file_info_simple — 추가 패턴
# ---------------------------------------------------------------------------


class TestExtractFileInfoExtra:
    def test_returns_none_when_html_invalid(self):
        # BeautifulSoup 은 어떤 입력이든 파싱하므로 None 반환은 진짜 빈 입력에서만.
        result = sp.extract_file_info_simple("")
        assert result is None or result == {}

    def test_size_parenthesis_pattern(self):
        html = """<html><body><p>file (12.5 GB)</p></body></html>"""
        info = sp.extract_file_info_simple(html)
        assert info is not None
        assert "GB" in info.get("size", "")
