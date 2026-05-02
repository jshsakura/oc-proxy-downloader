# -*- coding: utf-8 -*-
"""``core.models`` 직렬화 헬퍼 단위 테스트."""

import datetime

from core.models import StatusEnum, _serialize_column_value, DownloadRequest, UserProxy


class TestSerializeColumnValue:
    def test_datetime_to_iso(self):
        dt = datetime.datetime(2026, 5, 2, 12, 30, 45)
        assert _serialize_column_value("requested_at", dt) == "2026-05-02T12:30:45"

    def test_datetime_none_passthrough(self):
        assert _serialize_column_value("requested_at", None) is None

    def test_status_enum_to_string(self):
        assert _serialize_column_value("status", StatusEnum.downloading) == "downloading"
        assert _serialize_column_value("status", StatusEnum.done) == "done"

    def test_legacy_paused_status_migrates_to_stopped(self):
        """구버전 DB 의 'paused' 문자열이 그대로 들어와도 'stopped' 로 노출."""
        assert _serialize_column_value("status", "paused") == "stopped"

    def test_size_none_becomes_zero(self):
        assert _serialize_column_value("downloaded_size", None) == 0
        assert _serialize_column_value("total_size", None) == 0

    def test_size_with_value_passthrough(self):
        assert _serialize_column_value("downloaded_size", 12345) == 12345

    def test_error_value_stringified(self):
        assert _serialize_column_value("error", Exception("boom")) == "boom"

    def test_error_none_passthrough(self):
        # error 가 falsy 면 분기 안 타고 그대로 통과
        assert _serialize_column_value("error", None) is None
        assert _serialize_column_value("error", "") == ""

    def test_other_field_passthrough(self):
        assert _serialize_column_value("url", "https://example.com") == "https://example.com"
        assert _serialize_column_value("use_proxy", True) is True


class TestAsDictMixin:
    def test_download_request_as_dict_includes_all_columns(self):
        req = DownloadRequest(
            url="https://1fichier.com/?abc",
            file_name="movie.mkv",
            file_size="1.4 GB",
            status=StatusEnum.downloading,
        )
        d = req.as_dict()
        # 핵심 필드가 직렬화돼서 들어가 있어야 함
        assert d["url"] == "https://1fichier.com/?abc"
        assert d["file_name"] == "movie.mkv"
        assert d["status"] == "downloading"

    def test_user_proxy_as_dict_works(self):
        proxy = UserProxy(address="http://1.2.3.4:8080", proxy_type="single")
        d = proxy.as_dict()
        assert d["address"] == "http://1.2.3.4:8080"
        assert d["proxy_type"] == "single"

    def test_size_columns_default_to_zero_when_none(self):
        req = DownloadRequest(url="x")
        # downloaded_size/total_size 명시하지 않았을 때 None 일 수 있음
        d = req.as_dict()
        assert d["downloaded_size"] in (0,)
        assert d["total_size"] in (0,)
