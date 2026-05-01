# -*- coding: utf-8 -*-
"""``core.simple_parser`` 단위 테스트.

네트워크 / DB 의존이 없는 순수 함수들 (URL 정리, 다운로드 링크 후보 검증,
파일 정보·대기시간 추출, HTML 다운로드 링크 선택) 을 모두 검증한다.
"""

import pytest
from bs4 import BeautifulSoup

from core import simple_parser as sp


# ---------------------------------------------------------------------------
# clean_1fichier_url
# ---------------------------------------------------------------------------


class TestClean1fichierUrl:
    def test_keeps_url_when_only_file_id(self):
        url = "https://1fichier.com/?abc123"
        assert sp.clean_1fichier_url(url) == url

    def test_strips_affiliate_parameter(self):
        url = "https://1fichier.com/?abc123&af=12345"
        assert sp.clean_1fichier_url(url) == "https://1fichier.com/?abc123"

    def test_strips_multiple_extra_parameters(self):
        url = "https://1fichier.com/?abc123&af=1&utm=2&ref=3"
        assert sp.clean_1fichier_url(url) == "https://1fichier.com/?abc123"

    def test_returns_url_untouched_when_no_query(self):
        url = "https://1fichier.com/abc123"
        assert sp.clean_1fichier_url(url) == url

    def test_returns_homepage_url_unchanged(self):
        url = "https://1fichier.com/"
        assert sp.clean_1fichier_url(url) == url

    def test_does_not_strip_token_from_download_host(self):
        """다운로드 서버 호스트의 토큰은 절대 잘라내면 안 된다 (404 의 원인)."""
        url = "https://a-1.1fichier.com/p38234d8d/file?key=tok&ts=999"
        assert sp.clean_1fichier_url(url) == url

    def test_returns_unchanged_for_non_1fichier(self):
        url = "https://example.com/?abc&def"
        assert sp.clean_1fichier_url(url) == url

    def test_empty_input_returns_input(self):
        assert sp.clean_1fichier_url("") == ""
        assert sp.clean_1fichier_url(None) is None


# ---------------------------------------------------------------------------
# is_likely_download_url
# ---------------------------------------------------------------------------


class TestIsLikelyDownloadUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://a-1.1fichier.com/p38234d8d/movie.mkv",
            "https://cdn-7.1fichier.com/abc/file.bin",
            "https://s17.1fichier.com/longidentifier1234/file",
        ],
    )
    def test_download_hosts_pass(self, url):
        assert sp.is_likely_download_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://1fichier.com/",
            "https://1fichier.com/?abc",
            "https://1fichier.com/cgu.html",
            "https://1fichier.com/console/abo.pl",
            "https://1fichier.com/tarifs.html",
            "https://img.1fichier.com/logo-footer.png",
            "https://1fichier.com/api.html",
            "https://1fichier.com/abus.html",
            "https://1fichier.com/hlp.html",
        ],
    )
    def test_non_download_links_fail(self, url):
        assert sp.is_likely_download_url(url) is False

    def test_static_assets_rejected(self):
        assert sp.is_likely_download_url("https://a-1.1fichier.com/static/style.css") is False
        assert sp.is_likely_download_url("https://a-1.1fichier.com/img/favicon.ico") is False

    def test_empty_or_invalid_input(self):
        assert sp.is_likely_download_url(None) is False
        assert sp.is_likely_download_url("") is False
        assert sp.is_likely_download_url(123) is False


# ---------------------------------------------------------------------------
# pick_download_link_from_html
# ---------------------------------------------------------------------------


class TestPickDownloadLinkFromHtml:
    def test_returns_a_server_link_first(self):
        html = """
        <html><body>
            <a href="https://1fichier.com/console/abo.pl">Premium</a>
            <a href="https://a-3.1fichier.com/p1abcdef/movie.mkv">Click here to download</a>
            <a href="https://1fichier.com/?other&af=1">Download our app</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        link = sp.pick_download_link_from_html(soup, html)
        assert link == "https://a-3.1fichier.com/p1abcdef/movie.mkv"

    def test_falls_back_to_keyword_match_when_no_download_host(self):
        html = """
        <html><body>
            <a href="/cgu.html">Terms</a>
            <a href="https://download.1fichier.com/abcdef/file">Click here to download</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        link = sp.pick_download_link_from_html(soup, html)
        assert link == "https://download.1fichier.com/abcdef/file"

    def test_skips_promo_download_links_pointing_at_homepage(self):
        """'Download our app' 같은 홍보 링크는 절대 선택하지 않아야 한다."""
        html = """
        <html><body>
            <a href="https://1fichier.com/console/upload.pl">Upload your file</a>
            <a href="https://1fichier.com/?premium=1">Download our app</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        link = sp.pick_download_link_from_html(soup, html)
        assert link is None

    def test_regex_fallback_uses_raw_html(self):
        html = """
        <html><body>
            <p>setTimeout(()=>location.href="https://a-9.1fichier.com/p7token/biggame.iso", 0);</p>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        link = sp.pick_download_link_from_html(soup, html)
        assert link == "https://a-9.1fichier.com/p7token/biggame.iso"

    def test_returns_none_for_empty_soup(self):
        assert sp.pick_download_link_from_html(None) is None
        assert sp.pick_download_link_from_html(BeautifulSoup("", "html.parser")) is None

    def test_anchor_with_standard_id_ok(self):
        """1fichier 표준 다운로드 버튼 id='ok' 가 있으면 그 링크 우선."""
        html = """
        <html><body>
            <a id="ok" href="https://example-file-host.1fichier.com/aaaabbbbccc/movie.mkv">Get</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        link = sp.pick_download_link_from_html(soup, html)
        assert link == "https://example-file-host.1fichier.com/aaaabbbbccc/movie.mkv"

    def test_form_action_to_download_host_is_picked(self):
        html = """
        <html><body>
            <form action="https://a-1.1fichier.com/p1tok/file.bin" method="get"></form>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert sp.pick_download_link_from_html(soup, html) == \
            "https://a-1.1fichier.com/p1tok/file.bin"

    def test_javascript_location_redirect_is_picked(self):
        html = """
        <html><body>
            <script>
              setTimeout(function(){ window.location = "https://a-7.1fichier.com/p7tok/big.iso"; }, 0);
            </script>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        assert sp.pick_download_link_from_html(soup, html) == \
            "https://a-7.1fichier.com/p7tok/big.iso"

    def test_relative_anchor_href_is_resolved(self):
        html = """
        <html><body>
            <a id="ok" href="/p1abc/movie.mkv">Click here to download</a>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        # relative path 는 1fichier.com 메인 도메인 + 경로가 되므로
        # is_likely_download_url 에서 다운로드 호스트가 아니라 거절됨 → None
        assert sp.pick_download_link_from_html(soup, html) is None


# ---------------------------------------------------------------------------
# extract_file_info_simple
# ---------------------------------------------------------------------------


QR_HTML = """
<html><body>
    <table>
        <tr>
            <td><img src="/qr.pl?key=abc"></td>
            <td class="normal">
                <span style="font-weight:bold">my_movie.mkv</span>
                <br>
                <span style="font-size:0.9em;font-style:italic">1.52 GB</span>
            </td>
        </tr>
    </table>
</body></html>
"""

REGEX_HTML = """
<html><head><title>my_archive.zip - 1fichier.com: Cloud Storage</title></head>
<body>
    <p>File size: <strong>500.0 MB</strong></p>
</body></html>
"""


class TestExtractFileInfo:
    def test_qr_table_structure_is_preferred(self):
        info = sp.extract_file_info_simple(QR_HTML)
        assert info["name"] == "my_movie.mkv"
        assert info["size"] == "1.52 GB"

    def test_regex_fallback_strips_title_suffix(self):
        info = sp.extract_file_info_simple(REGEX_HTML)
        assert info["name"] == "my_archive.zip"
        assert info["size"].lower().endswith("mb")

    def test_returns_none_for_homepage(self):
        info = sp.extract_file_info_simple("<html><title>1fichier.com: Cloud Storage</title></html>")
        # 'cloud storage' 는 필터링되므로 name 없음 → None
        assert info is None or info.get("name") is None


# ---------------------------------------------------------------------------
# extract_wait_time_from_button
# ---------------------------------------------------------------------------


class TestExtractWaitTime:
    def test_javascript_calc_form(self):
        assert sp.extract_wait_time_from_button("var ct = 3*60;") == 180

    def test_javascript_simple_form_only_when_at_least_60(self):
        assert sp.extract_wait_time_from_button("var ct = 90;") == 90

    def test_javascript_simple_form_below_60_is_ignored(self):
        # 60초 미만은 카운트다운 변수일 수 있어 무시
        assert sp.extract_wait_time_from_button("var ct = 30;") is None

    def test_minutes_text(self):
        assert sp.extract_wait_time_from_button("You must wait 5 minutes.") == 300

    def test_button_text_form(self):
        # 분 표기가 없으면 button 패턴이 잡힘 — 60 이하라도 정상 반환
        assert sp.extract_wait_time_from_button("Free download in 45 seconds") == 45

    def test_no_match_returns_none(self):
        assert sp.extract_wait_time_from_button("hello world") is None
