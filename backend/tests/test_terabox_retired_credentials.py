import json

from core import config


def test_legacy_password_settings_are_hidden_and_removed_on_save(monkeypatch, tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({
        'terabox_email': 'old@example.com', 'terabox_password': 'old-password',
        'terabox_ndus': 'saved-session', 'fichier_password': 'keep-this',
    }))
    monkeypatch.setattr(config, 'CONFIG_DIR', tmp_path)
    monkeypatch.setattr(config, 'CONFIG_FILE', path)
    loaded = config.get_config()
    assert 'terabox_email' not in loaded
    assert 'terabox_password' not in loaded
    assert loaded['terabox_ndus'] == 'saved-session'

    config.save_config({'theme': 'dark', 'terabox_password': 'stale-browser'})
    persisted = json.loads(path.read_text())
    assert 'terabox_email' not in persisted
    assert 'terabox_password' not in persisted
    assert persisted['terabox_ndus'] == 'saved-session'
    assert persisted['fichier_password'] == 'keep-this'


def test_legacy_browser_cannot_restore_or_expose_password_login():
    legacy = {'terabox_email': 'old@example.com', 'terabox_password': 'secret', 'terabox_ndus': 'cookie'}
    public = config.mask_secrets(legacy)
    assert public == {'terabox_ndus': '********'}
    incoming = config.restore_masked_secrets({**legacy, 'terabox_ndus': '********'}, legacy)
    assert incoming == {'terabox_ndus': 'cookie'}
