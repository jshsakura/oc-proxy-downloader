"""A partial settings write must not take the rest of the config with it.

This is not hypothetical: a POST carrying only {"download_route": "balance"}
truncated a live config.json to two keys, taking the Telegram token, the
1fichier credentials and the download path with it. The web form always sends
every field, so the hole only opens for API callers — which the app ships an API
token to enable.
"""
import json

import pytest

import core.config as config


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    return path


def test_a_partial_save_keeps_the_untouched_keys(config_file):
    config_file.write_text(json.dumps({
        "telegram_bot_token": "secret",
        "download_path": "/downloads",
        "max_concurrent_downloads": 8,
    }), encoding="utf-8")

    config.save_config({"download_route": "balance"})

    stored = json.loads(config_file.read_text(encoding="utf-8"))
    assert stored["download_route"] == "balance"
    assert stored["telegram_bot_token"] == "secret"
    assert stored["download_path"] == "/downloads"
    assert stored["max_concurrent_downloads"] == 8


def test_merge_false_replaces_wholesale(config_file):
    config_file.write_text(json.dumps({"telegram_bot_token": "secret"}), encoding="utf-8")

    config.save_config({"theme": "dark"}, merge=False)

    assert json.loads(config_file.read_text(encoding="utf-8")) == {"theme": "dark"}


def test_get_config_fills_in_keys_added_since_the_file_was_written(config_file):
    # A config.json from an older version has no download_route; reading it as
    # None would make the new setting look unset in the UI.
    config_file.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")

    loaded = config.get_config()

    assert loaded["theme"] == "dark"
    assert loaded["download_route"] == config.DEFAULT_CONFIG["download_route"]
