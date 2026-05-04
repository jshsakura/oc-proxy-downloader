# -*- coding: utf-8 -*-
"""``services.ouo_unwrap_service`` 단위 테스트.

ouo.io / ouo.press 단축링크 자동 우회 진입점의 분기 동작을 검증한다.
실제 네트워크는 타지 않고 ``OuoResolver.resolve`` 를 mock 으로 대체한다.
"""

from unittest.mock import patch

import pytest

import services.ouo_unwrap_service as ouo_svc
from core.ouo_resolver import OuoResolver


# ---------------------------------------------------------------------------
# 각 테스트마다 모듈 전역 캐시(_resolver) 를 초기화해서 mock 이 새 인스턴스에
# 적용되도록 한다.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_resolver_singleton():
    ouo_svc._resolver = None
    yield
    ouo_svc._resolver = None


# ---------------------------------------------------------------------------
# is_ouo_url
# ---------------------------------------------------------------------------


class TestIsOuoUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://ouo.io/abc123",
            "http://ouo.io/abc123",
            "https://ouo.press/abc123",
            "https://www.ouo.io/abc123",
            "https://ouo.io/Xy9zAB",
        ],
    )
    def test_returns_true_for_ouo_links(self, url):
        assert ouo_svc.is_ouo_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://1fichier.com/?abc123",
            "https://example.com/ouo.io",  # 호스트가 아니라 path 에 ouo.io 가 있는 경우
            "https://mega.nz/file/xxx",
            "",
            "not a url",
        ],
    )
    def test_returns_false_for_non_ouo_links(self, url):
        assert ouo_svc.is_ouo_url(url) is False

    def test_returns_false_for_none(self):
        assert ouo_svc.is_ouo_url(None) is False


# ---------------------------------------------------------------------------
# unwrap_if_ouo
# ---------------------------------------------------------------------------


class TestUnwrapIfOuo:
    def test_returns_none_for_non_ouo_url_without_invoking_resolver(self):
        # 비-ouo URL 은 resolver 를 만들지도 호출하지도 않고 None 을 돌려준다.
        with patch.object(OuoResolver, "resolve") as mock_resolve:
            result = ouo_svc.unwrap_if_ouo("https://1fichier.com/?abc123")
        assert result is None
        mock_resolve.assert_not_called()

    def test_returns_resolved_url_on_success(self):
        target = "https://1fichier.com/?realfileid"
        with patch.object(OuoResolver, "resolve", return_value=target) as mock_resolve:
            result = ouo_svc.unwrap_if_ouo("https://ouo.io/abc123")

        assert result == target
        assert mock_resolve.call_count == 1
        # phase / link_tier 는 다운로드 파이프라인 진입점임을 표시하는 용도.
        # 향후 cache 도입 시 이 라벨로 통계를 분리할 수 있어야 한다.
        kwargs = mock_resolve.call_args.kwargs
        assert kwargs.get("phase") == "user_request"
        assert kwargs.get("link_tier") == "base"

    def test_returns_none_when_resolver_returns_none(self):
        with patch.object(OuoResolver, "resolve", return_value=None):
            result = ouo_svc.unwrap_if_ouo("https://ouo.io/abc123")
        assert result is None

    def test_returns_none_when_resolver_raises(self):
        # resolver 예외는 캐치해서 None 을 돌려준다 — 호출 측에서는 단축링크
        # 우회 실패로 처리하고 502 를 반환한다.
        with patch.object(OuoResolver, "resolve", side_effect=RuntimeError("boom")):
            result = ouo_svc.unwrap_if_ouo("https://ouo.io/abc123")
        assert result is None

    def test_normalizes_ouo_press_to_ouo_io_in_resolver(self):
        # 정규화는 OuoResolver.resolve 내부에서 수행하지만, 진입점에서도
        # ouo.press 를 ouo URL 로 인식해야 한다 (분기 검증).
        with patch.object(OuoResolver, "resolve", return_value="https://1fichier.com/?id") as mock_resolve:
            result = ouo_svc.unwrap_if_ouo("https://ouo.press/abc123")
        assert result == "https://1fichier.com/?id"
        mock_resolve.assert_called_once()


# ---------------------------------------------------------------------------
# get_resolver — 싱글톤 동작
# ---------------------------------------------------------------------------


class TestGetResolverSingleton:
    def test_returns_same_instance_on_repeated_calls(self):
        # FlareSolverr 헬스체크가 실제 네트워크를 타지 않도록 mock.
        with patch.object(ouo_svc, "_flaresolverr_reachable", return_value=False):
            first = ouo_svc.get_resolver()
            second = ouo_svc.get_resolver()
        assert first is second

    def test_standalone_mode_uses_curl_only_backend(self):
        with patch.object(ouo_svc, "_flaresolverr_reachable", return_value=False):
            resolver = ouo_svc.get_resolver()
        assert resolver.config.backend_order == ("curl_impersonate",)
        # 독립 실행 모드에서는 FlareSolverr 세션 부트스트랩을 끈다.
        assert resolver.config.auto_session is False

    def test_full_chain_when_flaresolverr_reachable(self):
        with patch.object(ouo_svc, "_flaresolverr_reachable", return_value=True):
            resolver = ouo_svc.get_resolver()
        assert "curl_impersonate" in resolver.config.backend_order
        assert "flaresolverr_form" in resolver.config.backend_order
        assert resolver.config.auto_session is True
