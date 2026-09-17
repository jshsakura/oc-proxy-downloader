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


def test_changing_fichier_credentials_wakes_the_old_guest_queue(monkeypatch):
    monkeypatch.setattr(
        settings_route,
        "get_config",
        lambda: {"fichier_email": "old@example.com", "fichier_password": "old"},
    )
    monkeypatch.setattr(settings_route, "save_config", MagicMock())
    monkeypatch.setattr(settings_route.download_core, "refresh_concurrency_settings", MagicMock())
    wake = MagicMock()
    monkeypatch.setattr(settings_route.download_core, "clear_fichier_cooldowns", wake)

    settings_route.update_settings_endpoint(
        {"fichier_email": "new@example.com", "fichier_password": "new"},
        MagicMock(),
    )

    wake.assert_called_once_with("계정 정보 변경")


def test_unchanged_masked_fichier_credentials_leave_the_queue_asleep(monkeypatch):
    monkeypatch.setattr(
        settings_route,
        "get_config",
        lambda: {"fichier_email": "same@example.com", "fichier_password": "stored"},
    )
    monkeypatch.setattr(settings_route, "save_config", MagicMock())
    monkeypatch.setattr(settings_route.download_core, "refresh_concurrency_settings", MagicMock())
    wake = MagicMock()
    monkeypatch.setattr(settings_route.download_core, "clear_fichier_cooldowns", wake)

    settings_route.update_settings_endpoint(
        {"fichier_email": "same@example.com", "fichier_password": "********"},
        MagicMock(),
    )

    wake.assert_not_called()
