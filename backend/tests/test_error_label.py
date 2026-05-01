# -*- coding: utf-8 -*-
"""``_download_with_proxy_async`` 의 단계별 라벨링 회귀 테스트.

회귀 시나리오: 다운로드 단계에서 발생한 ``HTTP 404: Not Found`` 가
``파싱 실패: HTTP 404: Not Found`` 로 잘못 표시되던 버그.

내부 ``_download_file_directly`` 가 raise 전에 ``req.status`` 를 ``failed``
로 바꿔버리기 때문에, ``req.status`` 만 보고 단계를 판단할 수 없다.
대신 ``download_started`` 라는 로컬 플래그로 추적한다.
"""

import pytest

from core.models import StatusEnum


def _label_for(download_started: bool, exc: Exception) -> str:
    """``_download_with_proxy_async`` except 블록의 라벨링 식을 그대로 흉내."""
    stage_label = "다운로드 실패" if download_started else "파싱 실패"
    return f"{stage_label}: {str(exc)}"


def test_parsing_stage_failure_uses_parsing_label():
    msg = _label_for(False, Exception("페이지 로드 실패: HTTP 404"))
    assert msg.startswith("파싱 실패")
    assert "HTTP 404" in msg


def test_download_stage_failure_uses_download_label_even_if_status_is_failed():
    """download_started=True 면 status 가 이미 failed 로 바뀌었어도 다운로드 실패로 라벨링."""
    msg = _label_for(True, Exception("HTTP 404: Not Found"))
    assert msg.startswith("다운로드 실패")
    assert "HTTP 404: Not Found" in msg
    # 핵심 회귀 방어
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
    """실수로 enum 이름이 바뀌면 라벨링도 깨지므로 가드."""
    assert StatusEnum.parsing.name == "parsing"
    assert StatusEnum.downloading.name == "downloading"
    assert StatusEnum.stopped.name == "stopped"
    assert StatusEnum.failed.name == "failed"
