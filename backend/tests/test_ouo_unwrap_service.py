# -*- coding: utf-8 -*-
"""``services.ouo_unwrap_service`` unit tests.

Verifies the branching behavior of the auto-bypass entry point for ouo.io /
ouo.press short links. No real network is used; ``OuoResolver.resolve`` is
replaced with a mock.
"""

from unittest.mock import patch

import pytest

import services.ouo_unwrap_service as ouo_svc
from core.ouo_resolver import OuoResolver


# ---------------------------------------------------------------------------
# Reset the module-global cache (_resolver) for each test so the mock is
# applied to a fresh instance.
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
            "https://example.com/ouo.io",  # ouo.io is in the path, not the host
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
        # A non-ouo URL returns None without creating or calling the resolver.
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
        # phase / link_tier mark this as the download-pipeline entry point.
        # When a cache is introduced later, these labels must allow splitting stats.
        kwargs = mock_resolve.call_args.kwargs
        assert kwargs.get("phase") == "user_request"
        assert kwargs.get("link_tier") == "base"

    def test_returns_none_when_resolver_returns_none(self):
        with patch.object(OuoResolver, "resolve", return_value=None):
            result = ouo_svc.unwrap_if_ouo("https://ouo.io/abc123")
        assert result is None

    def test_returns_none_when_resolver_raises(self):
        # A resolver exception is caught and None is returned — the caller treats
        # it as a short-link bypass failure and returns 502.
        with patch.object(OuoResolver, "resolve", side_effect=RuntimeError("boom")):
            result = ouo_svc.unwrap_if_ouo("https://ouo.io/abc123")
        assert result is None

    def test_normalizes_ouo_press_to_ouo_io_in_resolver(self):
        # Normalization happens inside OuoResolver.resolve, but the entry point
        # must also recognize ouo.press as an ouo URL (branch verification).
        with patch.object(OuoResolver, "resolve", return_value="https://1fichier.com/?id") as mock_resolve:
            result = ouo_svc.unwrap_if_ouo("https://ouo.press/abc123")
        assert result == "https://1fichier.com/?id"
        mock_resolve.assert_called_once()


# ---------------------------------------------------------------------------
# get_resolver — singleton behavior
# ---------------------------------------------------------------------------


class TestGetResolverSingleton:
    def test_returns_same_instance_on_repeated_calls(self):
        # Mock so the FlareSolverr health check does not hit the real network.
        with patch.object(ouo_svc, "_flaresolverr_reachable", return_value=False):
            first = ouo_svc.get_resolver()
            second = ouo_svc.get_resolver()
        assert first is second

    def test_standalone_mode_uses_curl_only_backend(self):
        with patch.object(ouo_svc, "_flaresolverr_reachable", return_value=False):
            resolver = ouo_svc.get_resolver()
        assert resolver.config.backend_order == ("curl_impersonate",)
        # In standalone mode, disable FlareSolverr session bootstrap.
        assert resolver.config.auto_session is False

    def test_full_chain_when_flaresolverr_reachable(self):
        with patch.object(ouo_svc, "_flaresolverr_reachable", return_value=True):
            resolver = ouo_svc.get_resolver()
        assert "curl_impersonate" in resolver.config.backend_order
        assert "flaresolverr_form" in resolver.config.backend_order
        assert resolver.config.auto_session is True
