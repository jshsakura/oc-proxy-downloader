# -*- coding: utf-8 -*-
"""Thread pools for blocking work, kept apart by how long the work runs.

Hoster parsing is synchronous (cloudscraper / Playwright), so it runs through
``run_in_executor``. Most parses finish in seconds, but a captcha solve drives a
real browser and can hold its thread for minutes. Sharing one pool between them
meant a couple of captcha links could occupy every worker, and since the asyncio
*default* executor is what every other ``run_in_executor`` caller uses too — the
status endpoints included — the whole backend stopped answering while the UI sat
on loading skeletons.

Captcha-capable hosts therefore parse on their own pool. Its size matches the
browser cap, so the queue forms here instead of inside the shared pool.
"""

from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Optional
from urllib.parse import urlparse

from core.browser_solver import BROWSER_FLOW_HOSTS, DEFAULT_MAX_CONCURRENT_BROWSERS


__all__ = ['CAPTCHA_PARSE_EXECUTOR', 'parse_executor_for']


CAPTCHA_PARSE_EXECUTOR = ThreadPoolExecutor(
    max_workers=DEFAULT_MAX_CONCURRENT_BROWSERS,
    thread_name_prefix="captcha-parse",
)


def parse_executor_for(url: str) -> Optional[Executor]:
    """The pool a parse of ``url`` belongs in.

    ``None`` selects the asyncio default executor, which is right for parses that
    return quickly. Hosts known to need a browser get the dedicated pool so their
    minutes-long solves never touch the pool the rest of the app depends on.
    """
    host = (urlparse(url or "").hostname or "").lower().removeprefix("www.")
    return CAPTCHA_PARSE_EXECUTOR if host in BROWSER_FLOW_HOSTS else None
