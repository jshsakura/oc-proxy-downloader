# -*- coding: utf-8 -*-
"""Tests for the Range-resume rules.

Both rules here were written against rows that got stuck in production, not
against a theory:

- Four downloads (ids 2050/2206/2236/2250) sat on ``failed`` with a ``.part``
  that was byte-for-byte the finished file, because ``total_size`` had been
  inflated by exactly the resume offset and every retry then asked for a range
  past the end and got a bare ``HTTP 416``.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import core.download_core as dc
from core.error_messages import KIND_TRANSIENT, classify_error
from core.resume import (
    OK,
    PARTIAL_CONTENT,
    PROBE_RANGE,
    RANGE_NOT_SATISFIABLE,
    complete_length,
    effective_initial_size,
    is_part_already_complete,
    probed_complete_length,
    total_size_from_content_length,
)


class TestEffectiveInitialSize:
    def test_partial_content_continues_from_the_requested_offset(self):
        assert effective_initial_size(PARTIAL_CONTENT, 1000) == 1000

    def test_plain_200_ignored_our_range_so_nothing_on_disk_counts(self):
        # This is the bug that inflated total_size: a 200 answering a Range
        # request carries the WHOLE file, so appending it doubles the .part.
        assert effective_initial_size(200, 1000) == 0

    def test_fresh_download_has_no_offset(self):
        assert effective_initial_size(200, 0) == 0

    def test_negative_offset_is_treated_as_no_offset(self):
        assert effective_initial_size(PARTIAL_CONTENT, -5) == 0


class TestTotalSizeFromContentLength:
    def test_fresh_body_states_the_full_length(self):
        assert total_size_from_content_length("484635681", 0) == 484635681

    def test_resumed_body_states_only_the_remainder(self):
        assert total_size_from_content_length("100", 900) == 1000

    def test_missing_header_is_unusable(self):
        assert total_size_from_content_length(None, 0) is None

    def test_non_numeric_header_is_unusable(self):
        assert total_size_from_content_length("chunked", 0) is None
        assert total_size_from_content_length("", 0) is None


class TestCompleteLength:
    def test_unsatisfied_range_form(self):
        assert complete_length("bytes */484635681") == 484635681

    def test_satisfied_range_form(self):
        assert complete_length("bytes 0-1023/2048") == 2048

    def test_unknown_total_is_not_a_length(self):
        assert complete_length("bytes 0-1023/*") is None

    def test_missing_header(self):
        assert complete_length(None) is None
        assert complete_length("") is None


class TestIsPartAlreadyComplete:
    def test_the_real_stuck_row(self):
        # id 2050: total_size in the DB said 484,651,827 but the resource is
        # 484,635,681 — exactly the .part size. The download was finished.
        assert is_part_already_complete("bytes */484635681", 484635681) is True

    def test_overlong_part_is_not_complete(self):
        # An earlier 200-answered-a-Range doubled the file: it is longer than
        # the resource and must be rewritten, not finalized.
        assert is_part_already_complete("bytes */1000", 1500) is False

    def test_short_part_is_not_complete(self):
        assert is_part_already_complete("bytes */1000", 999) is False

    def test_without_a_stated_length_we_cannot_claim_completeness(self):
        assert is_part_already_complete(None, 1000) is False
        assert is_part_already_complete("bytes */*", 1000) is False


class TestProbedCompleteLength:
    """A 416 is only *recommended* to carry Content-Range. Without the probe, a
    server that omits it would cost us a re-download of a file we already hold."""

    def test_206_states_the_length_in_content_range(self):
        assert probed_complete_length(206, "bytes 0-0/484635681", "1") == 484635681

    def test_200_ignored_the_range_so_content_length_is_the_whole_file(self):
        assert probed_complete_length(200, None, "484635681") == 484635681

    def test_206_without_a_stated_total_teaches_nothing(self):
        assert probed_complete_length(206, "bytes 0-0/*", "1") is None

    def test_error_status_teaches_nothing(self):
        assert probed_complete_length(404, "bytes 0-0/123", "1") is None
        assert probed_complete_length(416, None, None) is None


class FakeResponse:
    def __init__(self, status, headers):
        self.status = status
        self.headers = headers

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Records the probe request and answers it with a canned response."""

    def __init__(self, probe_response):
        self._probe_response = probe_response
        self.probe_headers = None

    def get(self, url, headers=None, proxy=None):
        self.probe_headers = headers
        return self._probe_response


class SequencedSession:
    """Answers successive requests from a list, recording the headers of each."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.sent = []

    def get(self, url, headers=None, proxy=None):
        self.sent.append(dict(headers or {}))
        return self._responses.pop(0)


class TestResolveRangeOverrun:
    """The wiring, not the arithmetic: a good ``.part`` must never be deleted on
    a guess. These four files were 3.6 GB of already-downloaded data."""

    @staticmethod
    def _core_with_stubbed_finalize():
        core = dc.DownloadCore()
        core._finalize_completed_file = AsyncMock()
        return core

    @pytest.mark.asyncio
    async def test_a_416_that_states_the_length_finalizes_without_a_probe(self, tmp_path):
        part = tmp_path / "f.rar.part"
        part.write_bytes(b"x" * 100)
        req = SimpleNamespace(id=1, save_path=str(part), total_size=140)
        core = self._core_with_stubbed_finalize()
        session = FakeSession(FakeResponse(200, {}))

        resolved = await core._resolve_range_overrun(
            req, db=None, response=FakeResponse(416, {"Content-Range": "bytes */100"}),
            part_size=100, download_mode="local",
            session=session, url="https://host/f", headers={},
        )

        assert resolved is True
        assert req.total_size == 100  # the inflated total is corrected
        assert session.probe_headers is None  # no probe was needed
        assert part.exists()
        core._finalize_completed_file.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_bare_416_probes_for_the_length_before_deciding(self, tmp_path):
        part = tmp_path / "f.rar.part"
        part.write_bytes(b"x" * 100)
        req = SimpleNamespace(id=1, save_path=str(part), total_size=140)
        core = self._core_with_stubbed_finalize()
        session = FakeSession(
            FakeResponse(206, {"Content-Range": "bytes 0-0/100", "Content-Length": "1"})
        )

        resolved = await core._resolve_range_overrun(
            req, db=None, response=FakeResponse(416, {}),
            part_size=100, download_mode="local",
            session=session, url="https://host/f", headers={"User-Agent": "x"},
        )

        assert resolved is True
        assert session.probe_headers["Range"] == PROBE_RANGE
        assert session.probe_headers["User-Agent"] == "x"  # caller headers kept
        assert part.exists()

    @pytest.mark.asyncio
    async def test_an_overlong_part_is_discarded_once_the_length_is_known(self, tmp_path):
        part = tmp_path / "f.rar.part"
        part.write_bytes(b"x" * 150)
        req = SimpleNamespace(id=1, save_path=str(part), total_size=150)
        core = self._core_with_stubbed_finalize()
        session = FakeSession(
            FakeResponse(206, {"Content-Range": "bytes 0-0/100", "Content-Length": "1"})
        )

        resolved = await core._resolve_range_overrun(
            req, db=None, response=FakeResponse(416, {}),
            part_size=150, download_mode="local",
            session=session, url="https://host/f", headers={},
        )

        assert resolved is False
        assert not part.exists()

    @pytest.mark.asyncio
    async def test_a_finished_file_is_never_deleted(self, tmp_path):
        # The discard branch only ever means "throw away a partial". If save_path
        # is not a .part it is a file the user already has, and no length
        # mismatch justifies deleting it out from under them.
        finished = tmp_path / "f.rar"
        finished.write_bytes(b"x" * 150)
        req = SimpleNamespace(id=1, save_path=str(finished), total_size=150)
        core = self._core_with_stubbed_finalize()
        session = FakeSession(
            FakeResponse(206, {"Content-Range": "bytes 0-0/100", "Content-Length": "1"})
        )

        with pytest.raises(Exception, match="416"):
            await core._resolve_range_overrun(
                req, db=None, response=FakeResponse(416, {}),
                part_size=150, download_mode="local",
                session=session, url="https://host/f", headers={},
            )

        assert finished.exists()

    @pytest.mark.asyncio
    async def test_a_probe_that_teaches_nothing_falls_back_to_a_plain_get(self, tmp_path):
        """Giving up left the row with no way forward — the same .part, the same
        Range, the same 416, every retry, forever. A request with no Range at all
        states the resource's full length in Content-Length, which is all that
        was missing."""
        part = tmp_path / "f.rar.part"
        part.write_bytes(b"x" * 100)
        req = SimpleNamespace(id=1, save_path=str(part), total_size=140)
        core = self._core_with_stubbed_finalize()
        session = SequencedSession([
            FakeResponse(403, {}),                                  # bytes=0-0 refused
            FakeResponse(200, {"Content-Length": "100"}),           # plain GET answers
        ])

        resolved = await core._resolve_range_overrun(
            req, db=None, response=FakeResponse(416, {}),
            part_size=100, download_mode="local",
            session=session, url="https://host/f", headers={},
        )

        assert resolved is True, "the .part was the whole file after all"
        assert [h.get("Range") for h in session.sent] == [PROBE_RANGE, None]
        assert part.exists()

    @pytest.mark.asyncio
    async def test_the_fallback_can_also_prove_a_mismatch(self, tmp_path):
        part = tmp_path / "f.rar.part"
        part.write_bytes(b"x" * 150)
        req = SimpleNamespace(id=1, save_path=str(part), total_size=150)
        core = self._core_with_stubbed_finalize()
        session = SequencedSession([
            FakeResponse(403, {}),
            FakeResponse(200, {"Content-Length": "100"}),
        ])

        resolved = await core._resolve_range_overrun(
            req, db=None, response=FakeResponse(416, {}),
            part_size=150, download_mode="local",
            session=session, url="https://host/f", headers={},
        )

        assert resolved is False
        assert not part.exists()

    @pytest.mark.asyncio
    async def test_an_unknown_length_keeps_the_part_and_raises(self, tmp_path):
        # This is the case that would otherwise throw away gigabytes on a guess.
        part = tmp_path / "f.rar.part"
        part.write_bytes(b"x" * 100)
        req = SimpleNamespace(id=1, save_path=str(part), total_size=140)
        core = self._core_with_stubbed_finalize()
        session = FakeSession(FakeResponse(403, {}))

        with pytest.raises(Exception, match="416"):
            await core._resolve_range_overrun(
                req, db=None, response=FakeResponse(416, {}),
                part_size=100, download_mode="local",
                session=session, url="https://host/f", headers={},
            )

        assert part.exists()
        core._finalize_completed_file.assert_not_awaited()


def test_status_constants():
    assert OK == 200
    assert PARTIAL_CONTENT == 206
    assert RANGE_NOT_SATISFIABLE == 416
    assert PROBE_RANGE == "bytes=0-0"


class TestClassification:
    """A 416 used to land in ``unknown`` — the bucket the audit cannot act on."""

    def test_416_is_transient_not_unknown(self):
        verdict = classify_error("다운로드", "HTTP 416: Range Not Satisfiable")
        assert verdict.kind == KIND_TRANSIENT
        assert verdict.definitive is False

    def test_reason_phrase_alone_is_enough(self):
        assert classify_error("다운로드", "Range Not Satisfiable").kind == KIND_TRANSIENT
