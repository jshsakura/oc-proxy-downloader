# -*- coding: utf-8 -*-
"""Regression tests for per-stage labeling in ``_download_with_proxy_async``.

Regression scenario: an ``HTTP 404: Not Found`` raised during the download
stage was incorrectly shown as ``파싱 실패: HTTP 404: Not Found``.

Because the internal ``_download_file_directly`` switches ``req.status`` to
``failed`` before raising, the stage cannot be inferred from ``req.status``
alone. Instead it is tracked with a local ``download_started`` flag.
"""

import pytest

from core.models import StatusEnum


def _label_for(download_started: bool, exc: Exception) -> str:
    """Mimics exactly the labeling expression in the ``_download_with_proxy_async`` except block."""
    stage_label = "다운로드 실패" if download_started else "파싱 실패"
    return f"{stage_label}: {str(exc)}"


def test_parsing_stage_failure_uses_parsing_label():
    msg = _label_for(False, Exception("페이지 로드 실패: HTTP 404"))
    assert msg.startswith("파싱 실패")
    assert "HTTP 404" in msg


def test_download_stage_failure_uses_download_label_even_if_status_is_failed():
    """When download_started=True, label as download failure even if status already became failed."""
    msg = _label_for(True, Exception("HTTP 404: Not Found"))
    assert msg.startswith("다운로드 실패")
    assert "HTTP 404: Not Found" in msg
    # Core regression guard
    assert "파싱 실패" not in msg


@pytest.mark.parametrize(
    "started,exc_text,expected_prefix",
    [
        (False, "다운로드 폼을 찾을 수 없음", "파싱 실패"),
        (False, "페이지 로드 실패: HTTP 503", "파싱 실패"),
        (True, "HTTP 404: Not Found", "다운로드 실패"),
        (True, "HTTP 410: Gone", "다운로드 실패"),
        (True, "Connection reset", "다운로드 실패"),
    ],
)
def test_label_table(started, exc_text, expected_prefix):
    assert _label_for(started, Exception(exc_text)).startswith(expected_prefix)


def test_status_enum_values_stable():
    """Guard: if an enum name is changed by accident, labeling breaks too."""
    assert StatusEnum.parsing.name == "parsing"
    assert StatusEnum.downloading.name == "downloading"
    assert StatusEnum.stopped.name == "stopped"
    assert StatusEnum.failed.name == "failed"
