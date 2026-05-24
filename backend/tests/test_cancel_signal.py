# -*- coding: utf-8 -*-
"""``core.cancel_signal`` unit tests."""

import threading

import pytest

from core import cancel_signal


@pytest.fixture(autouse=True)
def _reset_cancel_state():
    """Reset the global pool before and after each test."""
    cancel_signal.reset_all_for_tests()
    yield
    cancel_signal.reset_all_for_tests()


def test_get_event_creates_lazily():
    e = cancel_signal.get_event(1)
    assert isinstance(e, threading.Event)
    assert not e.is_set()
    # Calling with the same id twice returns the same Event
    assert cancel_signal.get_event(1) is e


def test_signal_cancel_sets_event():
    e = cancel_signal.get_event(1)
    cancel_signal.signal_cancel(1)
    assert e.is_set()


def test_signal_before_get_event_still_arrives():
    """Race: even if signal is called *before* get_event, a later get_event
    call must return an already-set Event (so the wait loop wakes immediately).
    """
    cancel_signal.signal_cancel(1)
    e = cancel_signal.get_event(1)
    assert e.is_set()


def test_clear_removes_event():
    cancel_signal.signal_cancel(1)
    cancel_signal.clear(1)
    # After clear, a new Event is created and must not be set.
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
