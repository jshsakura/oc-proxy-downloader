# -*- coding: utf-8 -*-
"""``simple_parser._run_wait_countdown`` unit tests.

Verification points:
- On entering waiting, emit status_update + the first countdown immediately (no UI gap)
- Countdown in 5-second steps, then 1-second steps for the final 5 seconds
- Emit wait_countdown_complete at the end
- Abort immediately when cancel_signal is set
- No localized text in the SSE payload (structured data only)
"""

import pytest

from core import simple_parser as sp
from core import cancel_signal


@pytest.fixture(autouse=True)
def _reset():
    cancel_signal.reset_all_for_tests()
    yield
    cancel_signal.reset_all_for_tests()


@pytest.fixture
def sse_log(monkeypatch):
    """A list collecting sse_callback invocations.
    time.sleep is patched to return immediately — Event.wait must also be mocked.
    """
    monkeypatch.setattr(sp.time, "sleep", lambda s: None)

    # Patch Event.wait to return False (=timeout) immediately so the countdown
    # finishes at once instead of running in real time.
    import threading
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: self.is_set())

    log = []

    def callback(event_type, payload):
        log.append((event_type, payload))

    return log, callback


def test_emits_status_update_and_initial_countdown_immediately(sse_log):
    log, cb = sse_log
    sp._run_wait_countdown(wait_seconds=10, download_id=1, sse_callback=cb)

    # The first two events are status_update + the immediate first countdown
    assert log[0][0] == "status_update"
    assert log[0][1]["status"] == "waiting"
    assert log[1][0] == "waiting"
    assert log[1][1]["remaining"] == 10
    assert log[1][1]["total"] == 10


def test_emits_wait_countdown_complete_at_end(sse_log):
    log, cb = sse_log
    sp._run_wait_countdown(wait_seconds=3, download_id=1, sse_callback=cb)

    # The last one is wait_countdown_complete
    assert log[-1][0] == "wait_countdown_complete"
    assert log[-1][1]["id"] == 1


def test_payload_has_no_localized_text(sse_log):
    """The SSE payload is structured data only — no localized message text allowed."""
    log, cb = sse_log
    sp._run_wait_countdown(wait_seconds=10, download_id=1, sse_callback=cb)

    for event_type, payload in log:
        # The message field must be absent entirely (the frontend builds it via i18n)
        assert "message" not in payload, \
            f"{event_type} payload 에 message 가 있으면 i18n 이 깨짐: {payload}"


def test_periodic_updates_at_5sec_intervals_and_final_5sec(sse_log):
    """20-second wait — emits when remaining is 20 (immediate), 15, 10, 5, 4, 3, 2, 1."""
    log, cb = sse_log
    sp._run_wait_countdown(wait_seconds=20, download_id=1, sse_callback=cb)

    waiting_events = [p for t, p in log if t == "waiting"]
    remainings = [p["remaining"] for p in waiting_events]
    # First countdown (20) + 5-second steps (15, 10, 5) + final 5 seconds (4, 3, 2, 1)
    assert remainings == [20, 15, 10, 5, 4, 3, 2, 1]


def test_cancel_signal_aborts_wait(monkeypatch):
    """When cancel_signal is set, the countdown aborts immediately (returns True)."""
    monkeypatch.setattr(sp.time, "sleep", lambda s: None)

    cancel_signal.signal_cancel(99)

    log = []
    cancelled = sp._run_wait_countdown(
        wait_seconds=60, download_id=99,
        sse_callback=lambda t, p: log.append((t, p)),
    )
    assert cancelled is True
    # status_update and the first waiting are emitted, but wait_countdown_complete is not
    types = [t for t, _ in log]
    assert "status_update" in types
    assert "waiting" in types
    assert "wait_countdown_complete" not in types


def test_zero_wait_returns_immediately():
    cancelled = sp._run_wait_countdown(
        wait_seconds=0, download_id=1, sse_callback=None,
    )
    assert cancelled is False


def test_no_download_id_falls_back_to_simple_sleep(monkeypatch):
    """Without download_id, cancellation is impossible — wait with a plain sleep."""
    sleeps = []
    monkeypatch.setattr(sp.time, "sleep", lambda s: sleeps.append(s))

    log = []
    cancelled = sp._run_wait_countdown(
        wait_seconds=10, download_id=None,
        sse_callback=lambda t, p: log.append((t, p)),
    )
    assert cancelled is False
    # A single plain time.sleep(wait_seconds) call
    assert sleeps == [10]


def test_sse_callback_failure_does_not_abort_countdown(monkeypatch):
    """Even if the SSE callback raises, the countdown runs to completion."""
    monkeypatch.setattr(sp.time, "sleep", lambda s: None)
    import threading
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: self.is_set())

    def flaky_cb(event_type, payload):
        raise RuntimeError("SSE broke")

    cancelled = sp._run_wait_countdown(
        wait_seconds=5, download_id=1, sse_callback=flaky_cb,
    )
    assert cancelled is False
