# -*- coding: utf-8 -*-
"""다운로드 취소 신호를 in-memory 로 전파하는 스레드 세이프 풀.

기존엔 카운트다운 루프가 1초마다 DB 를 쿼리해 ``status == stopped`` 를
확인했지만, 다운로드 N 개가 동시에 대기 중이면 매초 N 번의 DB 라운드
트립이 발생해 부하가 컸음.

대신 정지 요청은 ``signal_cancel(id)`` 로 ``threading.Event`` 를 set
하고, 카운트다운 루프는 ``event.wait(timeout=1.0)`` 로 깬다. DB 는
영속 상태(완료/실패/정지) 기록 용도로만 사용.

Race-safe:
- ``signal_cancel`` 이 카운트다운 시작 *전* 에 호출돼도, 같은 키로
  Event 를 미리 만들어 set 해두므로 ``get_event`` 가 깨워질 준비된
  Event 를 반환한다.
- 카운트다운이 끝났거나 다운로드가 완료/실패하면 ``clear`` 로 정리.
"""

from __future__ import annotations

import threading
from typing import Dict, Optional


_events: Dict[int, threading.Event] = {}
_lock = threading.Lock()


def get_event(download_id: int) -> threading.Event:
    """``download_id`` 의 cancel Event 를 반환. 없으면 생성."""
    with _lock:
        event = _events.get(download_id)
        if event is None:
            event = threading.Event()
            _events[download_id] = event
        return event


def signal_cancel(download_id: int) -> None:
    """``download_id`` 의 카운트다운/대기 루프를 즉시 깨운다.

    호출 시점에 Event 가 없으면 미리 만들어 set — 이후 ``get_event`` 호출
    시점에도 즉시 깨어진 상태로 반환된다.
    """
    with _lock:
        event = _events.get(download_id)
        if event is None:
            event = threading.Event()
            _events[download_id] = event
        event.set()


def clear(download_id: int) -> None:
    """``download_id`` 의 Event 를 풀에서 제거.

    다운로드가 종결(완료/실패/정지) 됐을 때 메모리 누수 방지용으로 호출.
    """
    with _lock:
        _events.pop(download_id, None)


def is_cancelled(download_id: int) -> bool:
    """``download_id`` 가 이미 취소 신호를 받았는지 확인 (poll용)."""
    with _lock:
        event = _events.get(download_id)
        return event is not None and event.is_set()


def reset_all_for_tests() -> None:
    """테스트에서 전역 상태 초기화. 운영 코드에서는 호출하지 말 것."""
    with _lock:
        _events.clear()
