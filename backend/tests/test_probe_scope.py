# -*- coding: utf-8 -*-
"""The auditor may only rule on links it can actually read.

The prober reads 1fichier's body markers. Handed a DataNodes link it used to
answer ``KIND_UNREACHABLE`` with "1fichier URL 이 아님" and ``definitive=True``,
and ``apply_probe_to_request`` wrote that over ``req.error``. On the live
instance that erased the real failure reason from 248 DataNodes rows, leaving
them pinned dead with nothing but a note about the prober's own reach — and a
bulk restart then skipped every one of them.

A verdict about the auditor is not a verdict about the link.
"""

import asyncio
import datetime

import pytest

from core.models import DownloadRequest, StatusEnum
from services.link_probe import (
    KIND_ALIVE,
    KIND_UNSUPPORTED,
    apply_probe_to_request,
    is_probe_supported,
    probe_1fichier_url,
)


DATANODES = "https://datanodes.to/oi9iokrci5va"
FICHIER = "https://1fichier.com/?abc123"


class TestProbeScope:

    @pytest.mark.parametrize("url", [FICHIER, "https://www.1fichier.com/?x"])
    def test_1fichier_is_in_scope(self, url):
        assert is_probe_supported(url) is True

    @pytest.mark.parametrize("url", [
        DATANODES,
        "https://megaup.net/abc",
        "https://mega.nz/file/abc",
        "",
        None,
    ])
    def test_everything_else_is_out_of_scope(self, url):
        assert is_probe_supported(url) is False

    def test_an_out_of_scope_url_is_reported_as_unsupported_not_unreachable(self):
        """`unreachable` means we looked and could not get there. Here we never
        looked, and the two must not share a kind."""
        probe = asyncio.run(probe_1fichier_url(DATANODES))

        assert probe.kind == KIND_UNSUPPORTED
        assert probe.definitive is False


class TestUnsupportedLeavesTheRecordAlone:

    def _row(self):
        return DownloadRequest(
            url=DATANODES,
            status=StatusEnum.stopped,
            error="[다운로드 실패] 다운로드 노드에 연결할 수 없습니다",
            failure_kind="transient",
            next_retry_at=datetime.datetime(2026, 8, 12, 9, 0, 0),
        )

    def test_the_real_failure_reason_survives(self):
        row = self._row()
        probe = asyncio.run(probe_1fichier_url(DATANODES))

        apply_probe_to_request(row, probe)

        assert row.error == "[다운로드 실패] 다운로드 노드에 연결할 수 없습니다"

    def test_the_classification_and_cooldown_survive(self):
        row = self._row()
        probe = asyncio.run(probe_1fichier_url(DATANODES))

        apply_probe_to_request(row, probe)

        assert row.failure_kind == "transient"
        assert row.next_retry_at == datetime.datetime(2026, 8, 12, 9, 0, 0)

    def test_the_attempt_is_still_recorded(self):
        """Skipping the verdict is not the same as pretending nothing happened —
        the ring buffer should show the auditor passed over this row."""
        row = self._row()
        probe = asyncio.run(probe_1fichier_url(DATANODES))

        apply_probe_to_request(row, probe)

        assert row.last_probed_at is not None
        assert KIND_UNSUPPORTED in (row.attempts_json or "")


class TestTargetSelection:

    def test_out_of_scope_rows_are_never_targets(self):
        """Filtering at selection means an unsupported row is not merely
        harmless to probe — it is never handed to the prober at all."""
        from api.routes.audit import _probeable_ids

        rows = [
            (1, DATANODES, None),
            (2, FICHIER, None),
            (3, "https://megaup.net/x", None),
            (4, None, FICHIER),   # resolved link gone, original still probeable
        ]

        assert _probeable_ids(rows) == [2, 4]

    def test_alive_is_still_applied_for_in_scope_rows(self):
        """The guard must not make the auditor useless where it does work."""
        from services.link_probe import ProbeResult

        row = DownloadRequest(url=FICHIER, status=StatusEnum.failed,
                              error="죽은 링크", failure_kind="dead")
        alive = ProbeResult(kind=KIND_ALIVE, summary="alive", raw_status=200,
                            body_marker=None, retry_after_seconds=None,
                            definitive=True)

        apply_probe_to_request(row, alive)

        assert row.failure_kind is None
