# -*- coding: utf-8 -*-
"""Tests for API authentication enforcement and settings secret handling."""

import pytest

from api import middleware
from core.config import (
    SECRET_PLACEHOLDER,
    mask_secrets,
    restore_masked_secrets,
)


# --- settings secrets ---


def test_stored_credentials_are_masked_on_read():
    """The settings API is reachable over the LAN; it must not hand out the
    Telegram bot token or the 1fichier password in readable form."""
    config = {
        "telegram_bot_token": "937742375:AAF-real-token",
        "fichier_password": "hunter2",
        "download_path": "/downloads",
    }

    masked = mask_secrets(config)

    assert masked["telegram_bot_token"] == SECRET_PLACEHOLDER
    assert masked["fichier_password"] == SECRET_PLACEHOLDER
    assert masked["download_path"] == "/downloads"


def test_masking_leaves_unset_credentials_empty():
    """An empty value must stay empty so the UI can tell 'not configured' from
    'configured but hidden'."""
    assert mask_secrets({"fichier_password": ""})["fichier_password"] == ""


def test_masking_does_not_mutate_the_stored_config():
    config = {"fichier_password": "hunter2"}

    mask_secrets(config)

    assert config["fichier_password"] == "hunter2"


def test_saving_an_untouched_form_keeps_the_real_credential():
    """The form round-trips what it was shown, so the placeholder coming back
    means 'unchanged' — not 'set my password to asterisks'."""
    incoming = {"fichier_password": SECRET_PLACEHOLDER, "theme": "dark"}
    stored = {"fichier_password": "hunter2", "theme": "light"}

    merged = restore_masked_secrets(incoming, stored)

    assert merged["fichier_password"] == "hunter2"
    assert merged["theme"] == "dark"


def test_a_genuinely_changed_credential_is_written_through():
    incoming = {"fichier_password": "new-secret"}
    stored = {"fichier_password": "hunter2"}

    assert restore_masked_secrets(incoming, stored)["fichier_password"] == "new-secret"


# --- request gating ---


@pytest.mark.parametrize("path", [
    "/api/auth/login",
    "/api/auth/status",
    "/api/locales/ko.json",
    "/",
    "/assets/app.js",
])
def test_paths_reachable_before_a_token_exists(path):
    assert middleware._is_exempt(path)


@pytest.mark.parametrize("path", [
    "/api/settings",
    "/api/history/",
    "/api/download/",
    "/api/events",
])
def test_data_paths_are_guarded(path):
    assert not middleware._is_exempt(path)


class _FakeRequest:
    def __init__(self, path, headers=None, query=None):
        self.headers = headers or {}
        self.query_params = query or {}
        self.url = type("U", (), {"path": path})()


def test_bearer_token_is_read_from_the_header():
    req = _FakeRequest("/api/settings", headers={"Authorization": "Bearer abc123"})

    assert middleware._presented_token(req) == "abc123"


def test_sse_accepts_the_token_as_a_query_parameter():
    """EventSource cannot set headers, so the stream route takes it in the URL."""
    req = _FakeRequest("/api/events", query={"token": "abc123"})

    assert middleware._presented_token(req) == "abc123"


def test_other_routes_ignore_a_query_token():
    """Query strings leak through logs and referrers, so the exception stays
    scoped to the one route that cannot use a header."""
    req = _FakeRequest("/api/settings", query={"token": "abc123"})

    assert middleware._presented_token(req) == ""
