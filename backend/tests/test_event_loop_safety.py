# -*- coding: utf-8 -*-
"""Structural guards that keep the API answering while work is in flight.

Every outage in this app so far has had the same shape: something blocking ended
up where it starves everything else. These tests encode the two rules that
prevent it, and they scan the tree rather than a hand-written list, so a new
route or a new pool is covered the day it is added.
"""

import ast
import pathlib

import pytest

ROUTES_DIR = pathlib.Path("api/routes")


def _route_handlers(path: pathlib.Path):
    """Every function in ``path`` that FastAPI serves, with its node."""
    # Explicit encoding: the sources carry Korean comments, and read_text() would
    # otherwise use the platform default — cp1252 on the Windows release runner,
    # which cannot decode them.
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if any(ast.unparse(d).startswith("router.") for d in node.decorator_list):
            yield node


def _awaits_something(node: ast.AST) -> bool:
    return any(
        isinstance(n, (ast.Await, ast.AsyncFor, ast.AsyncWith)) for n in ast.walk(node)
    )


@pytest.mark.parametrize(
    "route_file", sorted(ROUTES_DIR.glob("*.py")), ids=lambda p: p.name
)
def test_no_route_blocks_the_event_loop(route_file):
    """An `async def` handler that never awaits runs its blocking work — SQLite
    queries, file reads, psutil — directly on the event loop. One lock contention
    there stops every request in the app, not just its own, which is exactly how
    the UI ended up frozen with a healthy backend behind it.

    A handler declared `def` is dispatched to anyio's threadpool instead, so it
    cannot take the loop down no matter how slow it gets.
    """
    offenders = [
        node.name
        for node in _route_handlers(route_file)
        if isinstance(node, ast.AsyncFunctionDef) and not _awaits_something(node)
    ]

    assert offenders == [], (
        f"{route_file.name}: async handlers that never await must be declared "
        f"`def` so they run off the event loop — {offenders}"
    )


# Session calls that go to SQLite and therefore wait on its lock.
_BLOCKING_SESSION_CALLS = {"commit", "refresh", "query", "add", "delete", "flush", "execute"}

# async handlers that still touch the session directly on the event loop. This
# list may shrink, never grow: each entry is a handler that stalls every other
# request for as long as SQLite makes it wait. The guard above could not see
# them — it only catches handlers that never await at all, which is why
# add_download passed it while taking 20s per call in production.
_KNOWN_LOOP_DB_HANDLERS = {
    "audit.py": {"probe_single"},
    "downloads.py": {
        "start_download", "resume_download", "retry_download", "stop_download",
        "start_batch_downloads", "delete_download", "bulk_delete_downloads",
        "toggle_proxy_mode", "stop_all_downloads", "restart_failed_downloads",
        "stop_all_local_downloads", "restart_failed_local_downloads",
        "stop_all_proxy_downloads", "restart_failed_proxy_downloads",
    },
    "proxy.py": {"get_proxy_status"},
}


def _handlers_touching_the_session(node: ast.AST) -> bool:
    """True if the handler calls db.<blocking>() outside a thread hop."""
    return any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr in _BLOCKING_SESSION_CALLS
        and ast.unparse(n).startswith("db.")
        for n in ast.walk(node)
    )


@pytest.mark.parametrize(
    "route_file", sorted(ROUTES_DIR.glob("*.py")), ids=lambda p: p.name
)
def test_no_new_async_handler_queries_on_the_event_loop(route_file):
    """A running download commits progress constantly, so the SQLite write lock
    is usually held. An `async def` handler that queries or commits directly
    waits for that lock *on the loop*, freezing every other request — the
    failure that made every board send time out. Hop to a thread
    (asyncio.to_thread) or declare the handler `def`.
    """
    offenders = {
        node.name
        for node in _route_handlers(route_file)
        if isinstance(node, ast.AsyncFunctionDef) and _handlers_touching_the_session(node)
    }
    known = _KNOWN_LOOP_DB_HANDLERS.get(route_file.name, set())

    assert offenders - known == set(), (
        f"{route_file.name}: new async handler(s) doing DB work on the event loop — "
        f"{sorted(offenders - known)}"
    )
    assert known - offenders == set(), (
        f"{route_file.name}: {sorted(known - offenders)} no longer blocks — "
        f"remove it from _KNOWN_LOOP_DB_HANDLERS so it cannot regress"
    )


def test_slow_parses_cannot_consume_the_shared_pool():
    """Captcha solves hold a thread for minutes. On the asyncio default executor —
    which every run_in_executor caller shares — a couple of them left nothing for
    the rest of the app, so they get a pool of their own."""
    from core.executors import CAPTCHA_PARSE_EXECUTOR, parse_executor_for

    assert parse_executor_for("https://datanodes.to/x") is CAPTCHA_PARSE_EXECUTOR
    assert parse_executor_for("https://1fichier.com/?x") is None


def test_every_browser_host_is_routed_to_the_captcha_pool():
    """Adding a flow without routing its parses would silently reintroduce the
    starvation, so the two lists are checked against each other."""
    from core.browser_solver import BROWSER_FLOW_HOSTS
    from core.executors import CAPTCHA_PARSE_EXECUTOR, parse_executor_for

    for host in BROWSER_FLOW_HOSTS:
        assert parse_executor_for(f"https://{host}/file") is CAPTCHA_PARSE_EXECUTOR


def test_a_captcha_solve_cannot_outlive_the_parse_that_owns_it():
    """The outer cap is an asyncio.wait_for: it abandons the await but cannot stop
    the thread. If a solve could run past it, it would keep holding its queue slot
    after its download had already been failed."""
    from core.browser_solver import (
        LOCK_WAIT_SEC,
        MIN_SOLVE_BUDGET_SEC,
        SOLVE_BUDGET_SEC,
    )
    from core.download_core import SPECIAL_HOSTER_PARSE_TIMEOUT_SEC

    assert SOLVE_BUDGET_SEC < SPECIAL_HOSTER_PARSE_TIMEOUT_SEC
    assert LOCK_WAIT_SEC + MIN_SOLVE_BUDGET_SEC <= SOLVE_BUDGET_SEC


def test_waiting_for_a_turn_does_not_park_a_worker():
    """Queue waits used to hold a pool thread for 150s. KIND_QUEUED reschedules
    for free, so the wait exists only to catch a slot freeing up immediately."""
    from core.browser_solver import LOCK_WAIT_SEC

    assert LOCK_WAIT_SEC <= 10, "a long wait here starves the pool for no benefit"
