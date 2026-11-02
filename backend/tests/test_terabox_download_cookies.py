import aiohttp
import pytest
from yarl import URL

from core.download_core import build_download_cookie_options


@pytest.mark.asyncio
async def test_ndus_survives_file_server_redirect_without_leaking_to_other_hosts():
    options = build_download_cookie_options({'ndus': 'account-session', 'TSID': 'legacy'}, 'https://d.1024tera.com/file')
    assert options['cookies'] == {'TSID': 'legacy'}
    jar = options['cookie_jar']
    assert jar.filter_cookies(URL('https://d.1024tera.com/file'))['ndus'].value == 'account-session'
    assert jar.filter_cookies(URL('https://data.1024tera.com/file'))['ndus'].value == 'account-session'
    assert 'ndus' not in jar.filter_cookies(URL('https://example.test/file'))
    assert 'ndus' not in jar.filter_cookies(URL('https://1024tera.com.evil.test/file'))
    assert 'ndus' not in jar.filter_cookies(URL('http://data.1024tera.com/file'))


@pytest.mark.asyncio
async def test_external_download_never_receives_terabox_account_cookie():
    options = build_download_cookie_options({'ndus': 'account-session', 'other': 'keep'}, 'https://example.test/file')
    assert options == {'cookies': {'other': 'keep'}}


def test_other_hosts_keep_their_existing_download_cookie_context():
    assert build_download_cookie_options({'SID': 'fichier-session'}, 'https://a.1fichier.com/file') == {
        'cookies': {'SID': 'fichier-session'},
    }


def test_download_auth_error_is_actionable_and_cookie_allows_manual_retry(monkeypatch):
    from types import SimpleNamespace
    from core.terabox_share import terabox_download_error
    from core.error_messages import classify_error, KIND_AUTH_REQUIRED
    from api.routes import downloads
    message = terabox_download_error(403, b'{"error_code":31045,"error_msg":"user not exists"}')
    verdict = classify_error('download', message)
    assert verdict.kind == KIND_AUTH_REQUIRED
    assert '쿠키' in verdict.action
    req = SimpleNamespace(url='https://www.1024tera.com/s/1fixture', original_url=None,
                          failure_kind=KIND_AUTH_REQUIRED, error=message, next_retry_at=None)
    monkeypatch.setattr(downloads, 'get_config', lambda: {'terabox_ndus': 'renewed-cookie'})
    assert downloads._should_skip_retry(req, False) is None
    monkeypatch.setattr(downloads, 'get_config', lambda: {})
    assert downloads._should_skip_retry(req, True) == 'auth_required'


@pytest.mark.parametrize('status,body', [(403, b'Forbidden'), (403, b'{"error_code":999}'), (200, b'{"error_code":31045}')])
def test_other_responses_are_not_mislabeled_as_terabox_auth_failure(status, body):
    from core.terabox_share import terabox_download_error
    assert terabox_download_error(status, body) == ''


def test_terabox_cookie_cannot_unlock_another_hosts_auth_failure():
    from types import SimpleNamespace
    from core.error_messages import is_retry_blocked_now, KIND_AUTH_REQUIRED
    for url in ['https://datavaults.co/file', 'https://terabox.com.evil.test/file']:
        req = SimpleNamespace(url=url, original_url=None, failure_kind=KIND_AUTH_REQUIRED,
                              error='login required', next_retry_at=None)
        assert is_retry_blocked_now(req, False, has_terabox_cookie=True) == 'auth_required'
