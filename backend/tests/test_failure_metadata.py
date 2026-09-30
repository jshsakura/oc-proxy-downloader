"""Failed host attempts retain known names without contacting the host again."""
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core import download_core as dc, hoster_sites as hs
from core.hoster_common import HosterParseError
from core.models import Base, DownloadRequest, StatusEnum


@pytest.mark.asyncio
@pytest.mark.parametrize('original_name', ['5zJ5M', 'Collector BASE label', 'already-known.nsp'])
async def test_refused_parse_persists_metadata_and_preserves_source(monkeypatch, original_name):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        req = DownloadRequest(url='https://www.rootz.so/d/5zJ5M', original_url='https://www.rootz.so/d/5zJ5M',
                              file_name=original_name, use_proxy=False, status=StatusEnum.pending)
        db.add(req)
        db.commit()
        row_id = req.id
        core = dc.DownloadCore()
        parse = AsyncMock(side_effect=HosterParseError('Rootz: 파일이 비활성 상태입니다 (deleted)',
                             file_info={'name': 'actual.nsp', 'size': '797.46 MB', 'size_bytes': 836200784}))
        transfer = AsyncMock()
        events = AsyncMock()
        monkeypatch.setattr(core, '_run_special_parser', parse)
        monkeypatch.setattr(core, '_download_file_directly', transfer)
        monkeypatch.setattr(dc.sse_manager, 'broadcast_message', events)
        await core._download_special_hoster_async(req, db)
        db.expire_all()
        saved = db.get(DownloadRequest, row_id)
        expected_name = original_name if original_name.endswith('.nsp') else 'actual.nsp'
        assert saved.file_name == expected_name
        assert saved.file_size == '797.46 MB'
        assert saved.total_size == 836200784  # exact bytes, not the rounded display size
        assert saved.downloaded_size == 0
        assert saved.status == StatusEnum.failed
        assert saved.failure_kind == 'source_unconfirmed'
        assert saved.attempt_count == 1 and saved.next_retry_at is None
        assert saved.original_url == saved.url == 'https://www.rootz.so/d/5zJ5M'
        parse.assert_awaited_once()
        transfer.assert_not_awaited()
        failed = [call.args[1] for call in events.await_args_list if call.args[1].get('status') == 'failed']
        assert failed[0]['filename'] == expected_name
        assert failed[0]['total_size'] == 836200784
    engine.dispose()


@pytest.mark.parametrize('parser,url,html_text,expected', [
    (hs.parse_vikingfile_sync, 'https://vikingfile.com/AbCd', '<h2 id="filename">movie.rar</h2><div id="size">100 MB</div>', 'movie.rar'),
    (hs.parse_akirabox_sync, 'https://akirabox.com/AbCd/file', '<meta property="og:title" content="movie.rar">', 'movie.rar'),
    (hs.parse_vikingfile_sync, 'https://vikingfile.com/AbCd', '<h2 id="filename">File not found</h2>', None),
])
def test_browser_failures_reuse_already_observed_page(monkeypatch, parser, url, html_text, expected):
    calls = []
    def fail(*args, **kwargs):
        calls.append(args[0])
        error = HosterParseError('호스트 제한')
        error.page_html = html_text
        raise error
    monkeypatch.setattr(hs, 'solve_download_page', fail)
    with pytest.raises(HosterParseError) as failure:
        parser(url)
    assert failure.value.file_info.get('name') == expected
    assert calls == [url]
