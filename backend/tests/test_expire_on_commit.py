# -*- coding: utf-8 -*-
"""A commit must not silently re-SELECT every row it just wrote.

SQLAlchemy's default ``expire_on_commit=True`` marks every instance stale at
commit, so the *next attribute read* issues a fresh SELECT. A download commits
constantly — progress, status, retry bookkeeping — and reads its own row right
after almost every one, so the default cost one extra query per commit per
object across ~233 sites.

Turning it off is only safe because this codebase never leaned on that implicit
refresh: every place that needs to see another session's write calls
``db_async.refresh`` explicitly. ``TestStoppedChecksRefreshFirst`` is what keeps
that true — without expiry, a forgotten refresh stops being a wasted query and
becomes a download that ignores the stop button.
"""

import ast
import pathlib

import pytest
from sqlalchemy import event

from core.db import SessionLocal, engine
from core.models import Base, DownloadRequest, StatusEnum


@pytest.fixture(autouse=True, scope="module")
def _schema():
    """The isolated test database starts empty; these tests write a real row."""
    Base.metadata.create_all(bind=engine)


class TestSessionConfiguration:
    def test_commit_does_not_expire_instances(self):
        assert SessionLocal.kw["expire_on_commit"] is False

    def test_autoflush_stays_off(self):
        # Unrelated to expiry, but the same sessionmaker call — an accidental
        # flip here would put a write on the event loop from any lazy read.
        assert SessionLocal.kw["autoflush"] is False


class TestNoReselectAfterCommit:
    """The measurement, not the setting: count the SELECTs a commit provokes."""

    @staticmethod
    def _count_selects(session, action):
        seen = []

        def before_execute(conn, clauseelement, multiparams, params, execution_options):
            statement = str(clauseelement)
            if statement.lstrip().upper().startswith("SELECT"):
                seen.append(statement)

        event.listen(session.get_bind(), "before_execute", before_execute)
        try:
            action()
        finally:
            event.remove(session.get_bind(), "before_execute", before_execute)
        return seen

    def test_reading_a_row_after_committing_it_costs_no_query(self):
        session = SessionLocal()
        try:
            row = DownloadRequest(url="https://example.invalid/x", status=StatusEnum.pending)
            session.add(row)
            session.commit()

            selects = self._count_selects(session, lambda: row.status)

            assert selects == [], (
                "reading an attribute after commit re-queried the row; "
                f"expire_on_commit is back on — {selects}"
            )
        finally:
            session.rollback()
            session.close()

    def test_an_explicit_refresh_still_re_reads(self):
        # The escape hatch has to keep working, or the stopped-checks below are
        # guarding nothing.
        session = SessionLocal()
        try:
            row = DownloadRequest(url="https://example.invalid/y", status=StatusEnum.pending)
            session.add(row)
            session.commit()

            selects = self._count_selects(session, lambda: session.refresh(row))

            assert selects, "db.refresh must still issue a SELECT"
        finally:
            session.rollback()
            session.close()


# --- the guard --------------------------------------------------------------
# Files whose downloads read their own row to notice another session's stop.
_FILES = (
    pathlib.Path("core/download_core.py"),
    pathlib.Path("core/proxy_manager.py"),
)
# How far back to look for the refresh. A stopped-check is always guarded within
# a statement or two; a wider window would let a refresh from an unrelated branch
# count and quietly defeat the test.
_LOOKBACK_LINES = 12


def _stopped_checks(tree) -> list:
    """Line numbers comparing some instance's ``.status`` to ``stopped``."""
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        text = ast.unparse(node)
        if ".status ==" in text and "StatusEnum.stopped" in text:
            hits.append(node.lineno)
    return hits


def _freshness_lines(tree) -> set:
    """Lines that make an instance current: a refresh, or a fetch from the DB."""
    fresh = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr in {"refresh", "first", "one", "one_or_none", "get"}:
            # A call can span lines; every line it covers counts as fresh.
            fresh.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return fresh


@pytest.mark.parametrize("relative_path", _FILES, ids=lambda p: p.name)
def test_a_stopped_check_reads_a_fresh_row(relative_path):
    """Without expire_on_commit, a stale read ignores the stop button.

    A stop lands in a *different* session. Nothing in this session's identity map
    changes, so the row has to be re-read deliberately before it is trusted.
    """
    path = pathlib.Path(__file__).resolve().parent.parent / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"))

    fresh = _freshness_lines(tree)
    offenders = [
        line for line in _stopped_checks(tree)
        if not any(candidate in fresh for candidate in range(line - _LOOKBACK_LINES, line))
    ]

    assert offenders == [], (
        f"{relative_path.name}: these lines compare status to stopped without "
        f"re-reading the row first, so a stop from another session is invisible "
        f"— lines {offenders}. Add `await db_async.refresh(db, req)` before the check."
    )
