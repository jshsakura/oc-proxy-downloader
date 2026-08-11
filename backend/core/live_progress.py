# -*- coding: utf-8 -*-
"""Live transfer speed, kept where a list refetch can still find it.

The transfer loop computes a smoothed speed and pushes it over SSE, and the
grid merges that into the row it already has. Then the grid refetches — which
it does on almost every SSE event — and the row is replaced by the API payload,
which has no speed in it. The number vanished until the next tick, so an active
download showed a blank speed column most of the time.

Speed is a live reading, not history: it is meaningless a minute later and has
no business in the database. It lives here instead, keyed by download id, and
the list endpoints read from it so a refetch keeps what the stream established.
"""

from __future__ import annotations

import threading
from typing import Dict


# Written from the transfer loop (worker threads / the event loop) and read by
# request handlers, so it is guarded.
_lock = threading.Lock()
_speeds: Dict[int, float] = {}


def record_speed(download_id: int, bytes_per_second: float) -> None:
    """Note the current speed of a running download."""
    if not download_id:
        return
    with _lock:
        _speeds[int(download_id)] = max(0.0, float(bytes_per_second or 0))


def speed_of(download_id: int) -> int:
    """Current speed in bytes/sec, or 0 when nothing is being transferred."""
    with _lock:
        return int(_speeds.get(int(download_id), 0))


def clear(download_id: int) -> None:
    """Drop a download's reading — it stopped, failed or finished.

    Leaving a stale number behind is worse than showing none: the grid would
    keep advertising throughput for a download that is no longer moving.
    """
    with _lock:
        _speeds.pop(int(download_id), None)


def snapshot() -> Dict[int, int]:
    """All current readings, for a list response."""
    with _lock:
        return {k: int(v) for k, v in _speeds.items()}
