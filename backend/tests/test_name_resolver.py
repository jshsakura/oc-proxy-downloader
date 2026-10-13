# -*- coding: utf-8 -*-
"""Rows waiting in the queue learn their real file names ahead of the download."""

from types import SimpleNamespace

import pytest

from core.hoster_common import HosterParseError
from core.link_names import fichier_file_id, parse_fichier_check
from services import name_resolver as nr


LIVE = "https://1fichier.com/?ccwoppei56xf49pllwms"
DEAD = "https://1fichier.com/?y5rqqlaquwbgusecpgbs"
DATANODES = "https://datanodes.to/o7syev8j42bt"

# What check_links.pl answered on 2026-10-13 while this IP's quota was spent.
CHECK_ANSWER = (
    "<td>https://1fichier.com/?ccwoppei56xf49pllwms;"
    "SKYFRCANIVRSY-(US)-NSwTcH-[BASE]-NSP-Ziperto.rar;375458163</td>\n"
    "<td>https://1fichier.com/?y5rqqlaquwbgusecpgbs;;;NOT FOUND</td>\n"
)


def _row(row_id, url, name):
    return SimpleNamespace(
        id=row_id, url=url, original_url=url, file_name=name,
        file_size=None, total_size=0,
    )


class TestLinkChecker:
    def test_live_link_gives_name_and_exact_size(self):
        found = parse_fichier_check(CHECK_ANSWER)
        assert found["ccwoppei56xf49pllwms"] == {
            "name": "SKYFRCANIVRSY-(US)-NSwTcH-[BASE]-NSP-Ziperto.rar",
            "size_bytes": 375458163,
        }

    def test_deleted_link_is_known_to_have_no_name(self):
        assert parse_fichier_check(CHECK_ANSWER)["y5rqqlaquwbgusecpgbs"] is None

    def test_unmentioned_link_is_left_out(self):
        assert "otherid" not in parse_fichier_check(CHECK_ANSWER)

    def test_escaped_characters_in_a_name_are_restored(self):
        found = parse_fichier_check("https://1fichier.com/?abc;Tom &amp; Jerry.rar;10\n")
        assert found["abc"]["name"] == "Tom & Jerry.rar"

    def test_file_id_only_for_1fichier(self):
        assert fichier_file_id(LIVE) == "ccwoppei56xf49pllwms"
        assert fichier_file_id(DATANODES) == ""


class TestPickUnnamed:
    def test_ids_are_picked_and_real_names_are_not(self):
        rows = [
            _row(1, LIVE, "1fichier:ccwoppei56xf49pllwms"),
            _row(2, DATANODES, "o7syev8j42bt"),
            _row(3, DATANODES, "Game.part1.rar"),
        ]
        assert [r.id for r in nr.pick_unnamed(rows, {}, 10_000.0)] == [1, 2]

    def test_a_row_asked_about_lately_waits(self):
        rows = [_row(1, LIVE, "1fichier:ccwoppei56xf49pllwms")]
        now = 10_000.0
        assert nr.pick_unnamed(rows, {1: now - 60}, now) == []
        later = now + nr.NAME_RETRY_AFTER_SEC
        assert len(nr.pick_unnamed(rows, {1: now}, later)) == 1


class TestLookups:
    @pytest.mark.asyncio
    async def test_one_check_names_every_live_1fichier_row(self, monkeypatch):
        asked = []

        def fake_check(urls):
            asked.append(list(urls))
            return parse_fichier_check(CHECK_ANSWER)

        monkeypatch.setattr(nr, "fetch_fichier_names_sync", fake_check)
        live = _row(1, LIVE, "1fichier:ccwoppei56xf49pllwms")
        dead = _row(2, DEAD, "1fichier:y5rqqlaquwbgusecpgbs")

        named = await nr.NameResolver()._name_fichier_rows([live, dead])

        assert asked == [[LIVE, DEAD]]
        assert named == ["SKYFRCANIVRSY-(US)-NSwTcH-[BASE]-NSP-Ziperto.rar"]
        assert live.total_size == 375458163
        assert dead.file_name == "1fichier:y5rqqlaquwbgusecpgbs"

    @pytest.mark.asyncio
    async def test_page_rows_are_named_from_their_page(self, monkeypatch):
        monkeypatch.setattr(
            nr, "fetch_page_name_sync",
            lambda url: {"name": "ESTW-NSwTcH-NSP-Update121-Ziperto.rar", "size": "565.1 MB"},
        )
        row = _row(1, DATANODES, "o7syev8j42bt")

        named = await nr.NameResolver()._name_page_rows([row])

        assert named == ["ESTW-NSwTcH-NSP-Update121-Ziperto.rar"]
        assert row.file_size == "565.1 MB"

    @pytest.mark.asyncio
    async def test_a_429_stops_the_page_reads(self, monkeypatch):
        calls = []

        def refuse(url):
            calls.append(url)
            raise HosterParseError("HTTP 429")

        monkeypatch.setattr(nr, "fetch_page_name_sync", refuse)
        resolver = nr.NameResolver()
        rows = [_row(1, DATANODES, "a"), _row(2, DATANODES, "b")]

        assert await resolver._name_page_rows(rows) == []
        assert len(calls) == 1
        assert 1 in resolver._tried and 2 not in resolver._tried
