# -*- coding: utf-8 -*-
"""Settings API exposes inherited runtime values without persisting them."""

from unittest.mock import MagicMock

from api.routes import settings as settings_route


def test_flaresolverr_environment_value_is_visible_but_stored_value_stays_empty(monkeypatch):
    monkeypatch.setenv("FLARESOLVERR_URL", "http://flaresolverr.example:8191")
    monkeypatch.setattr(
        settings_route,
        "get_config",
        lambda: {"flaresolverr_url": "", "theme": "dark"},
    )
    monkeypatch.setattr(
        settings_route,
        "resolve_flaresolverr_url",
        lambda: "http://flaresolverr.example:8191",
    )

    result = settings_route.get_settings_endpoint(MagicMock())

    assert result["flaresolverr_url"] == ""
    assert result["flaresolverr_url_effective"] == "http://flaresolverr.example:8191"
    assert result["flaresolverr_url_source"] == "environment"


def test_explicit_flaresolverr_setting_reports_settings_source(monkeypatch):
    monkeypatch.setenv("FLARESOLVERR_URL", "http://from-compose:8191")
    monkeypatch.setattr(
        settings_route,
        "get_config",
        lambda: {"flaresolverr_url": "http://explicit:8191"},
    )
    monkeypatch.setattr(
        settings_route,
        "resolve_flaresolverr_url",
        lambda: "http://explicit:8191",
    )

    result = settings_route.get_settings_endpoint(MagicMock())

    assert result["flaresolverr_url_effective"] == "http://explicit:8191"
    assert result["flaresolverr_url_source"] == "settings"
