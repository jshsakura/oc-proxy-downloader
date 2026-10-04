"""The grid's "n/m" retry counter must use the backend's real attempt caps.

The frontend kept its own copy of the caps and it had drifted: it showed
transient retries as "1/3" and rate limits as "1/2" while the backend allowed
two attempts and one. A counter that promises retries the app will not make is
worse than no counter.
"""
import re
from pathlib import Path

from core.error_messages import _MAX_AUTO_RETRY_ATTEMPTS

GRID_JS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "grid.js"


def _frontend_limits() -> dict:
    source = GRID_JS.read_text(encoding="utf-8")
    block = re.search(r"AUTO_RETRY_LIMITS\s*=\s*Object\.freeze\(\{(.*?)\}\)", source, re.S)
    assert block, "AUTO_RETRY_LIMITS not found in grid.js"
    return {key: int(value) for key, value in re.findall(r"(\w+)\s*:\s*(\d+)", block.group(1))}


def test_counter_matches_every_kind_that_retries_automatically():
    expected = {kind: cap for kind, cap in _MAX_AUTO_RETRY_ATTEMPTS.items() if cap > 1}
    assert _frontend_limits() == expected
