# -*- coding: utf-8 -*-
"""``core.cancel_signal`` 단위 테스트."""

import threading

import pytest

from core import cancel_signal


@pytest.fixture(autouse=True)
def _reset_cancel_state():
    """각 테스트 전후로 전역 풀 초기화."""
    cancel_signal.reset_all_for_tests()
    yield
    cancel_signal.reset_all_for_tests()


def test_get_event_creates_lazily():
    e = cancel_signal.get_event(1)
    assert isinstance(e, threading.Event)
    assert not e.is_set()
    # 같은 id 두 번 호출하면 같은 Event 반환
    assert cancel_signal.get_event(1) is e


def test_signal_cancel_sets_event():
    e = cancel_signal.get_event(1)
    cancel_signal.signal_cancel(1)
    assert e.is_set()


def test_signal_before_get_event_still_arrives():
    """Race: signal 이 get_event 보다 *먼저* 호출돼도, 이후 get_event 호출
    시 이미 set 된 Event 가 반환되어야 한다 (대기 루프 즉시 깨어남).
    """
    cancel_signal.signal_cancel(1)
    e = cancel_signal.get_event(1)
    assert e.is_set()


def test_clear_removes_event():
    cancel_signal.signal_cancel(1)
    cancel_signal.clear(1)
    # clear 후엔 새 Event 가 만들어지고 set 되어 있지 않아야 한다.
    e = cancel_signal.get_event(1)
    assert not e.is_set()


def test_is_cancelled():
    assert cancel_signal.is_cancelled(1) is False
    cancel_signal.signal_cancel(1)
    assert cancel_signal.is_cancelled(1) is True
    cancel_signal.clear(1)
    assert cancel_signal.is_cancelled(1) is False


def test_independent_ids():
    cancel_signal.signal_cancel(1)
    assert cancel_signal.is_cancelled(1)
    assert not cancel_signal.is_cancelled(2)
