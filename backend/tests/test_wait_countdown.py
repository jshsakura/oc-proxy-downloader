# -*- coding: utf-8 -*-
"""``simple_parser._run_wait_countdown`` 단위 테스트.

검증 포인트:
- waiting 진입 시 status_update + 첫 카운트다운 즉시 발송 (UI 공백 없게)
- 5초 단위 + 마지막 5초 1초 단위 카운트다운
- 종료 시 wait_countdown_complete 발송
- cancel_signal set 되면 즉시 중단
- SSE payload 에 한글 텍스트 없음 (구조화 데이터만)
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
    """sse_callback 호출 기록을 모은 리스트.
    time.sleep 도 즉시 진행되도록 패치 — Event.wait 도 같이 모킹해야 함.
    """
    monkeypatch.setattr(sp.time, "sleep", lambda s: None)

    # Event.wait 를 즉시 False (=timeout) 반환하도록 패치해서 카운트다운이
    # 실시간이 아니라 즉시 끝나게 한다.
    import threading
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: self.is_set())

    log = []

    def callback(event_type, payload):
        log.append((event_type, payload))

    return log, callback


def test_emits_status_update_and_initial_countdown_immediately(sse_log):
    log, cb = sse_log
    sp._run_wait_countdown(wait_seconds=10, download_id=1, sse_callback=cb)

    # 첫 두 이벤트는 status_update + 즉시 첫 카운트다운
    assert log[0][0] == "status_update"
    assert log[0][1]["status"] == "waiting"
    assert log[1][0] == "waiting"
    assert log[1][1]["remaining"] == 10
    assert log[1][1]["total"] == 10


def test_emits_wait_countdown_complete_at_end(sse_log):
    log, cb = sse_log
    sp._run_wait_countdown(wait_seconds=3, download_id=1, sse_callback=cb)

    # 마지막은 wait_countdown_complete
    assert log[-1][0] == "wait_countdown_complete"
    assert log[-1][1]["id"] == 1


def test_payload_has_no_localized_text(sse_log):
    """SSE payload 는 구조화 데이터만 — 한글 메시지 텍스트가 들어가면 안 됨."""
    log, cb = sse_log
    sp._run_wait_countdown(wait_seconds=10, download_id=1, sse_callback=cb)

    for event_type, payload in log:
        # message 필드 자체가 없어야 한다 (프론트가 i18n 으로 만든다)
        assert "message" not in payload, \
            f"{event_type} payload 에 message 가 있으면 i18n 이 깨짐: {payload}"


def test_periodic_updates_at_5sec_intervals_and_final_5sec(sse_log):
    """20초 대기 — remaining 이 20(즉시), 15, 10, 5, 4, 3, 2, 1 일 때 발송."""
    log, cb = sse_log
    sp._run_wait_countdown(wait_seconds=20, download_id=1, sse_callback=cb)

    waiting_events = [p for t, p in log if t == "waiting"]
    remainings = [p["remaining"] for p in waiting_events]
    # 첫 카운트다운(20) + 5초 단위(15, 10, 5) + 마지막 5초(4, 3, 2, 1)
    assert remainings == [20, 15, 10, 5, 4, 3, 2, 1]


def test_cancel_signal_aborts_wait(monkeypatch):
    """cancel_signal 이 set 되면 카운트다운 즉시 중단 (True 반환)."""
    monkeypatch.setattr(sp.time, "sleep", lambda s: None)

    cancel_signal.signal_cancel(99)

    log = []
    cancelled = sp._run_wait_countdown(
        wait_seconds=60, download_id=99,
        sse_callback=lambda t, p: log.append((t, p)),
    )
    assert cancelled is True
    # status_update 와 첫 waiting 은 발송되지만, wait_countdown_complete 는 없음
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
    """download_id 없으면 cancel 불가 — 단순 sleep 으로 대기."""
    sleeps = []
    monkeypatch.setattr(sp.time, "sleep", lambda s: sleeps.append(s))

    log = []
    cancelled = sp._run_wait_countdown(
        wait_seconds=10, download_id=None,
        sse_callback=lambda t, p: log.append((t, p)),
    )
    assert cancelled is False
    # 단순 time.sleep(wait_seconds) 한 번 호출
    assert sleeps == [10]


def test_sse_callback_failure_does_not_abort_countdown(monkeypatch):
    """SSE 콜백이 예외를 던져도 카운트다운은 끝까지 진행."""
    monkeypatch.setattr(sp.time, "sleep", lambda s: None)
    import threading
    monkeypatch.setattr(threading.Event, "wait", lambda self, timeout=None: self.is_set())

    def flaky_cb(event_type, payload):
        raise RuntimeError("SSE broke")

    cancelled = sp._run_wait_countdown(
        wait_seconds=5, download_id=1, sse_callback=flaky_cb,
    )
    assert cancelled is False
