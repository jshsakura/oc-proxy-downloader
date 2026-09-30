import pytest
from urllib.parse import parse_qs, urlparse
from core.generic_links import google_drive_file_id, parse_google_drive_sync, google_drive_confirmation
from core.hoster_common import HosterParseError
from core.hoster_parsers import is_special_hoster_url


@pytest.mark.parametrize('url', ['https://drive.google.com/file/d/public-id/view?usp=sharing',
    'https://drive.google.com/open?id=public-id', 'https://drive.google.com/uc?id=public-id'])
def test_public_drive_links_use_download_transport_without_account_or_preflight(url):
    parsed = parse_google_drive_sync(url)
    assert is_special_hoster_url(url)
    assert google_drive_file_id(parsed['download_link']) == 'public-id'
    assert parsed['cookies'] == {} and parsed['referer'] == url


def test_resourcekey_survives_url_normalization():
    assert parse_qs(urlparse(parse_google_drive_sync('https://drive.google.com/file/d/file-id/view?resourcekey=shared-key')['download_link']).query)['resourcekey'] == ['shared-key']


@pytest.mark.parametrize('change', ['different_id', 'foreign_destination', 'post', 'missing_confirm'])
def test_confirmation_never_approves_another_file_or_foreign_form(change):
    identifier = 'another-file' if change == 'different_id' else 'file-id'
    dest = 'https://ad.test/download' if change == 'foreign_destination' else 'https://drive.usercontent.google.com/download'
    method = 'POST' if change == 'post' else 'GET'
    confirm = '' if change == 'missing_confirm' else '<input type="hidden" name="confirm" value="t">'
    body = f'<form id="download-form" action="{dest}" method="{method}"><input type="hidden" name="id" value="{identifier}">{confirm}</form>'
    with pytest.raises(HosterParseError):
        google_drive_confirmation(body, 'https://drive.usercontent.google.com/download?id=file-id', 'https://drive.google.com/file/d/file-id/view')


def test_public_large_file_confirmation_preserves_exact_server_fields():
    body = '<form id="download-form" action="https://drive.usercontent.google.com/download" method="GET"><input type="hidden" name="id" value="file-id"><input type="hidden" name="export" value="download"><input type="hidden" name="confirm" value="t"><input type="hidden" name="uuid" value="published-session-token"></form>'
    target = google_drive_confirmation(body, 'https://drive.usercontent.google.com/download?id=file-id', 'https://drive.google.com/file/d/file-id/view')
    assert parse_qs(urlparse(target).query) == {'id':['file-id'],'export':['download'],'confirm':['t'],'uuid':['published-session-token']}


@pytest.mark.parametrize('url', ['https://drive.google.com/drive/folders/folder-id', 'https://drive.google.com.evil.test/open?id=file-id'])
def test_drive_folder_and_lookalike_never_become_guessed_file_urls(url):
    with pytest.raises(HosterParseError):
        parse_google_drive_sync(url)


@pytest.mark.asyncio
async def test_fragmented_confirmation_is_read_completely_and_bounded():
    from core.generic_links import read_confirmation_body
    class Stream:
        async def iter_chunked(self, size):
            for value in [b'<for', b'm>', b'confirmed', b'</form>']:
                yield value
    assert await read_confirmation_body(Stream()) == b'<form>confirmed</form>'
    with pytest.raises(HosterParseError, match='상한'):
        await read_confirmation_body(Stream(), limit=7)
