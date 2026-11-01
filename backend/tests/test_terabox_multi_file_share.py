"""A share holding several files becomes one row per file."""
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core import download_core as dc
from core.error_messages import classify_error
from core.hoster_common import HosterParseError
from core.models import Base, DownloadRequest, StatusEnum
from utils import file_helpers

SHARE = "https://www.terabox.com/s/1fixture?pwd=pw"
FILES = [
    {"url": SHARE + "&fid=1", "name": "a.bin", "size": "1.00 MB"},
    {"url": SHARE + "&fid=2", "name": "b.bin", "size": "2.00 MB"},
    {"url": SHARE + "&fid=3", "name": "c.bin"},
]


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session


def share_row(db, **fields):
    row = DownloadRequest(url=SHARE, original_url=SHARE, password="pw", use_proxy=False,
                          proxy_pinned=True, file_name="Whole Collection.zip", status=StatusEnum.pending, **fields)
    db.add(row)
    db.commit()
    return row


def file_reply(url, password=None, proxies=None):
    return {"download_link": "https://cdn.example.test/" + url.rsplit("=", 1)[-1], "file_info": None,
            "cookies": {}, "user_agent": None, "referer": None, "split_into": None}


def split_reply():
    return {"download_link": "", "file_info": None, "cookies": {}, "user_agent": None,
            "referer": None, "split_into": FILES}


def core_with(monkeypatch, parse):
    core = dc.DownloadCore()
    events = AsyncMock()

    async def run_parser(url, call):
        return call()

    monkeypatch.setattr(dc, "parse_special_hoster_sync", parse)
    monkeypatch.setattr(core, "_run_special_parser", run_parser)
    monkeypatch.setattr(core, "_download_file_directly", AsyncMock())
    monkeypatch.setattr(core, "_delayed_start_next_pending", AsyncMock())
    monkeypatch.setattr(dc.sse_manager, "broadcast_message", events)
    monkeypatch.setattr(dc, "generate_file_path", lambda name, is_temporary=True: f"/fixture/{name}.part")
    return core, events


def splitting(url, password=None, proxies=None):
    return file_reply(url) if "fid=" in url else split_reply()


def rows_by_name(db):
    db.expire_all()
    return {row.file_name: row for row in db.query(DownloadRequest).all()}


@pytest.mark.asyncio
async def test_each_file_gets_a_row_and_this_row_downloads_the_first(monkeypatch, db):
    req = share_row(db, mirror_urls='["https://example.org/other"]')
    core, events = core_with(monkeypatch, splitting)
    await core._download_special_hoster_async(req, db)
    rows = rows_by_name(db)
    assert set(rows) == {"a.bin", "b.bin", "c.bin"}
    first = rows["a.bin"]
    assert first.id == req.id and first.url == first.original_url == FILES[0]["url"]
    assert first.mirror_urls is None and first.total_size == 1024 ** 2 and first.save_path == "/fixture/a.bin.part"
    added = rows["b.bin"]
    assert added.status == StatusEnum.pending and added.url == added.original_url == FILES[1]["url"]
    assert added.password == "pw" and added.use_proxy is False and added.proxy_pinned is True
    assert added.total_size == 2 * 1024 ** 2
    assert rows["c.bin"].total_size == 0
    assert "force_refresh" in [call.args[0] for call in events.await_args_list]
    core._download_file_directly.assert_awaited_once()
    assert core._download_file_directly.await_args.args[2] == "https://cdn.example.test/1"


@pytest.mark.asyncio
async def test_a_refusal_on_the_first_file_leaves_the_others_their_rows(monkeypatch, db):
    def first_is_gone(url, password=None, proxies=None):
        if "fid=1" in url:
            raise HosterParseError("TeraBox 공유 링크가 만료되었거나 삭제되었습니다")
        return splitting(url)

    req = share_row(db)
    core, _ = core_with(monkeypatch, first_is_gone)
    await core._download_special_hoster_async(req, db)
    rows = rows_by_name(db)
    assert set(rows) == {"a.bin", "b.bin", "c.bin"}
    assert rows["a.bin"].status == StatusEnum.failed and rows["b.bin"].status == StatusEnum.pending
    core._download_file_directly.assert_not_awaited()


@pytest.mark.asyncio
async def test_adding_the_share_again_takes_only_the_files_without_a_row(monkeypatch, db):
    db.add(DownloadRequest(url=FILES[0]["url"], original_url=FILES[0]["url"], file_name="a.bin", status=StatusEnum.done))
    db.commit()
    req = share_row(db)
    core, _ = core_with(monkeypatch, splitting)
    await core._download_special_hoster_async(req, db)
    assert db.query(DownloadRequest).count() == 3
    db.expire_all()
    assert req.url == FILES[1]["url"] and req.file_name == "b.bin"
    assert core._download_file_directly.await_args.args[2] == "https://cdn.example.test/2"


@pytest.mark.asyncio
async def test_adding_a_share_with_every_file_listed_reports_it_and_stops(monkeypatch, db):
    for item in FILES:
        db.add(DownloadRequest(url=item["url"], original_url=item["url"], file_name=item["name"], status=StatusEnum.done))
    db.commit()
    req = share_row(db)
    core, _ = core_with(monkeypatch, splitting)
    await core._download_special_hoster_async(req, db)
    db.expire_all()
    assert db.query(DownloadRequest).count() == 4 and req.url == SHARE
    assert req.status == StatusEnum.failed and req.next_retry_at is None
    assert "이미 모두" in req.error
    core._download_file_directly.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_single_file_result_leaves_the_row_alone(monkeypatch, db):
    req = share_row(db)
    core, events = core_with(monkeypatch, file_reply)
    await core._download_special_hoster_async(req, db)
    assert db.query(DownloadRequest).count() == 1 and req.url == SHARE
    assert "force_refresh" not in [call.args[0] for call in events.await_args_list]


@pytest.mark.parametrize("raw", [
    "TeraBox 공유의 파일은 이미 모두 목록에 있습니다",
    "TeraBox 공유 파일이 너무 많습니다 (최대 200개)",
    "TeraBox 공유에서 이 파일을 찾지 못했습니다",
])
def test_split_refusals_are_not_retried_automatically(raw):
    assert classify_error("파싱", raw).kind != "unknown"
    row = DownloadRequest(url=SHARE, attempt_count=0)
    assert dc.apply_failure_to_request(row, "파싱", raw).next_retry_at is None


def test_a_partial_of_another_file_with_the_same_name_is_not_reused(monkeypatch, tmp_path):
    monkeypatch.setattr(file_helpers, "get_download_path", lambda: tmp_path)
    (tmp_path / "data.bin.part").write_bytes(b"another file")
    assert file_helpers.generate_file_path("data.bin", is_temporary=True) == str(tmp_path / "data(1).bin.part")
    (tmp_path / "data(1).bin").write_bytes(b"finished")
    assert file_helpers.generate_file_path("data.bin", is_temporary=True) == str(tmp_path / "data(2).bin.part")
