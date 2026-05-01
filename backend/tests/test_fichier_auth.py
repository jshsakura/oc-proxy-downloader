# -*- coding: utf-8 -*-
"""``core.fichier_auth`` 동작 검증 (네트워크 없이 cloudscraper 모킹)."""

from unittest.mock import MagicMock

import pytest

from core import fichier_auth


@pytest.fixture(autouse=True)
def _clear_cache():
    """각 테스트 시작 시 모듈 전역 캐시를 비운다."""
    fichier_auth.clear_cached_session()
    yield
    fichier_auth.clear_cached_session()


def _scraper_with(login_html: str, console_html: str, status: int = 200):
    cookie = MagicMock()
    cookie.name, cookie.value = "SID", "abc123"
    scraper = MagicMock()
    scraper.cookies = [cookie]

    login_response = MagicMock()
    login_response.status_code = status
    login_response.text = login_html

    console_response = MagicMock()
    console_response.status_code = 200
    console_response.text = console_html

    scraper.get.side_effect = [login_response, console_response]
    scraper.post.return_value = login_response  # 로그인 POST 응답
    return scraper


class TestLogin:
    def test_login_success_returns_scraper_and_caches(self, monkeypatch):
        scraper = _scraper_with(
            login_html="<html>...</html>",
            console_html='<a href="/console/abo.pl">Logout</a>',
        )
        monkeypatch.setattr(fichier_auth.cloudscraper, "create_scraper", lambda **kw: scraper)

        s1 = fichier_auth.get_authenticated_scraper("user@x.com", "pw1")
        s2 = fichier_auth.get_authenticated_scraper("user@x.com", "pw1")
        assert s1 is s2  # 캐시 재사용

    def test_login_invalid_credentials_raises(self, monkeypatch):
        scraper = _scraper_with(
            login_html="Invalid email or password",
            console_html="",
        )
        monkeypatch.setattr(fichier_auth.cloudscraper, "create_scraper", lambda **kw: scraper)

        with pytest.raises(fichier_auth.FichierLoginError, match="이메일|비밀번호"):
            fichier_auth.get_authenticated_scraper("user@x.com", "wrongpw")

    def test_session_validation_fails_when_console_unrelated(self, monkeypatch):
        scraper = _scraper_with(
            login_html="<html>welcome</html>",
            console_html="<html>Login required</html>",  # 콘솔로 못 들어감
        )
        monkeypatch.setattr(fichier_auth.cloudscraper, "create_scraper", lambda **kw: scraper)

        with pytest.raises(fichier_auth.FichierLoginError, match="콘솔"):
            fichier_auth.get_authenticated_scraper("user@x.com", "pw")

    def test_empty_credentials_rejected(self):
        with pytest.raises(fichier_auth.FichierLoginError, match="비어"):
            fichier_auth.get_authenticated_scraper("", "")

    def test_get_session_cookies_returns_dict(self, monkeypatch):
        scraper = _scraper_with(
            login_html="ok",
            console_html='<a href="/console/index.pl">My account</a>',
        )
        monkeypatch.setattr(fichier_auth.cloudscraper, "create_scraper", lambda **kw: scraper)

        cookies = fichier_auth.get_session_cookies("user@x.com", "pw")
        assert cookies == {"SID": "abc123"}

    def test_force_refresh_invalidates_cache(self, monkeypatch):
        # 첫 호출
        scraper1 = _scraper_with(
            login_html="ok",
            console_html='<a href="/console/index.pl">My account</a>',
        )
        scraper2 = _scraper_with(
            login_html="ok",
            console_html='<a href="/console/index.pl">My account</a>',
        )

        scrapers = iter([scraper1, scraper2])
        monkeypatch.setattr(
            fichier_auth.cloudscraper, "create_scraper", lambda **kw: next(scrapers)
        )

        first = fichier_auth.get_authenticated_scraper("u", "p")
        second = fichier_auth.get_authenticated_scraper("u", "p", force_refresh=True)
        assert first is scraper1
        assert second is scraper2
        assert first is not second

    def test_test_login_returns_false_on_failure(self, monkeypatch):
        scraper = _scraper_with(
            login_html="invalid email",
            console_html="",
        )
        monkeypatch.setattr(fichier_auth.cloudscraper, "create_scraper", lambda **kw: scraper)
        assert fichier_auth.test_login("u", "wrong") is False


class TestGuestSlotDetection:
    def test_detect_block_reason_recognizes_guest_slots_full(self):
        from core import simple_parser as sp
        html = """
        <html><body>
            <p>Free download is temporarily limited due to high demand.</p>
            <p>All free guest slots are currently in use.</p>
            <p>Free slots are available right now for registered users.</p>
        </body></html>
        """
        reason = sp.detect_block_reason(html)
        assert reason is not None
        assert "게스트" in reason or "guest" in reason.lower()
        assert "로그인" in reason

    def test_classify_error_for_guest_slots_full(self):
        from core.error_messages import classify_error
        c = classify_error("파싱", "1fichier 차단: 무료 게스트 슬롯이 가득 참 (1fichier 무료 계정 로그인 필요)")
        assert "게스트" in c.summary or "슬롯" in c.summary
        assert "계정" in c.action and "로그인" in c.action
