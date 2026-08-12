# -*- coding: utf-8 -*-
"""Tests for the Range-resume rules.

Both rules here were written against rows that got stuck in production, not
against a theory:

- Four downloads (ids 2050/2206/2236/2250) sat on ``failed`` with a ``.part``
  that was byte-for-byte the finished file, because ``total_size`` had been
  inflated by exactly the resume offset and every retry then asked for a range
  past the end and got a bare ``HTTP 416``.
"""

import pytest

from core.error_messages import KIND_TRANSIENT, classify_error
from core.resume import (
    PARTIAL_CONTENT,
    RANGE_NOT_SATISFIABLE,
    complete_length,
    effective_initial_size,
    is_part_already_complete,
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


def test_status_constants():
    assert PARTIAL_CONTENT == 206
    assert RANGE_NOT_SATISFIABLE == 416


class TestClassification:
    """A 416 used to land in ``unknown`` — the bucket the audit cannot act on."""

    def test_416_is_transient_not_unknown(self):
        verdict = classify_error("다운로드", "HTTP 416: Range Not Satisfiable")
        assert verdict.kind == KIND_TRANSIENT
        assert verdict.definitive is False

    def test_reason_phrase_alone_is_enough(self):
        assert classify_error("다운로드", "Range Not Satisfiable").kind == KIND_TRANSIENT
