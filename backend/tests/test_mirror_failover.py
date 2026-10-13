# -*- coding: utf-8 -*-
"""A file sent with several links moves to the next one when its link is stuck."""

import datetime
import json
from types import SimpleNamespace

from core.models import StatusEnum
from services.mirror_failover import (
    WAIT_FAILOVER_SEC,
    clean_mirrors,
    needs_failover,
    remaining_mirrors,
    switch_to_next_mirror,
)


NOW = datetime.datetime(2026, 10, 13, 16, 30)
FICHIER = "https://1fichier.com/?w64finlzsjikhgjm"
DATANODES = "https://datanodes.to/abc123def456"
MEGAUP = "https://megaup.net/xyz/Game.rar"


def _row(status, mirrors, next_retry_at=None, row_id=1, save_path=None):
    return SimpleNamespace(
        id=row_id, url=FICHIER, original_url=FICHIER, status=status,
        mirror_urls=json.dumps(mirrors) if mirrors else None,
        next_retry_at=next_retry_at, save_path=save_path,
        downloaded_size=10, total_size=100, failure_kind="daily_quota",
        attempt_count=2, finished_at=NOW, error="x",
    )


class TestRegistration:
    def test_keeps_order_and_drops_the_main_link_and_repeats(self):
        assert clean_mirrors(FICHIER, [DATANODES, FICHIER, " ", DATANODES, MEGAUP]) == [
            DATANODES, MEGAUP,
        ]

    def test_anything_but_a_list_means_no_mirrors(self):
        assert clean_mirrors(FICHIER, "https://a.example/x") == []
        assert clean_mirrors(FICHIER, None) == []


class TestWhenToMove:
    def test_a_failed_link_moves(self):
        assert needs_failover(_row(StatusEnum.failed, [DATANODES]), NOW, set())

    def test_a_link_held_by_a_host_wait_moves(self):
        held = _row(StatusEnum.pending, [DATANODES], NOW + datetime.timedelta(hours=3))
        assert needs_failover(held, NOW, set())

    def test_a_short_turn_in_the_queue_does_not_move(self):
        soon = _row(StatusEnum.pending, [DATANODES], NOW + datetime.timedelta(seconds=WAIT_FAILOVER_SEC - 1))
        assert not needs_failover(soon, NOW, set())

    def test_nothing_moves_without_another_link_or_while_running(self):
        assert not needs_failover(_row(StatusEnum.failed, []), NOW, set())
        assert not needs_failover(_row(StatusEnum.failed, [DATANODES]), NOW, {1})

    def test_a_stopped_row_is_left_to_the_user(self):
        assert not needs_failover(_row(StatusEnum.stopped, [DATANODES]), NOW, set())


class TestSwitch:
    def test_moves_to_the_next_link_and_queues_it_now(self):
        row = _row(StatusEnum.failed, [DATANODES, MEGAUP])

        assert switch_to_next_mirror(row, NOW) == DATANODES

        assert row.url == DATANODES
        assert remaining_mirrors(row) == [MEGAUP]
        assert row.status == StatusEnum.pending
        assert row.next_retry_at == NOW
        assert row.failure_kind is None and row.attempt_count == 0
        assert row.downloaded_size == 0 and row.total_size == 0

    def test_the_last_link_leaves_no_mirrors(self):
        row = _row(StatusEnum.failed, [MEGAUP])
        switch_to_next_mirror(row, NOW)
        assert row.mirror_urls is None

    def test_a_partial_file_from_the_previous_host_is_removed(self, tmp_path):
        part = tmp_path / "Game.rar.part"
        part.write_bytes(b"x")
        row = _row(StatusEnum.failed, [MEGAUP], save_path=str(part))

        switch_to_next_mirror(row, NOW)

        assert not part.exists() and row.save_path is None
