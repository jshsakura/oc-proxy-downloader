# -*- coding: utf-8 -*-
"""Thread-safe pool that propagates download-cancel signals in memory.

Previously the countdown loop queried the DB every second to check
``status == stopped``, but with N downloads waiting concurrently this
caused N DB round-trips per second, which was a heavy load.

Instead, a stop request sets a ``threading.Event`` via
``signal_cancel(id)``, and the countdown loop wakes up via
``event.wait(timeout=1.0)``. The DB is used only to record persistent
state (completed/failed/stopped).

Race-safe:
- Even if ``signal_cancel`` is called *before* the countdown starts, the
  Event for that key is created and set in advance, so ``get_event``
  returns an Event that is already ready to wake.
- When the countdown finishes or the download completes/fails, ``clear``
  cleans it up.
"""

from __future__ import annotations

import threading
from typing import Dict, Optional


_events: Dict[int, threading.Event] = {}
_lock = threading.Lock()


def get_event(download_id: int) -> threading.Event:
    """Return the cancel Event for ``download_id``. Create it if missing."""
    with _lock:
        event = _events.get(download_id)
        if event is None:
            event = threading.Event()
            _events[download_id] = event
        return event


def signal_cancel(download_id: int) -> None:
    """Immediately wake the countdown/wait loop for ``download_id``.

    If no Event exists at call time, one is created and set in advance, so
    that even a later ``get_event`` call returns it already woken.
    """
    with _lock:
        event = _events.get(download_id)
        if event is None:
            event = threading.Event()
            _events[download_id] = event
        event.set()


def clear(download_id: int) -> None:
    """Remove the Event for ``download_id`` from the pool.

    Called to prevent memory leaks once a download has finished
    (completed/failed/stopped).
    """
    with _lock:
        _events.pop(download_id, None)


def is_cancelled(download_id: int) -> bool:
    """Check whether ``download_id`` has already received a cancel signal (for polling)."""
    with _lock:
        event = _events.get(download_id)
        return event is not None and event.is_set()


def reset_all_for_tests() -> None:
    """Reset global state for tests. Do not call from production code."""
    with _lock:
        _events.clear()
