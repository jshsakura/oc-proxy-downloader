# -*- coding: utf-8 -*-
"""Fill in real file names for rows that still wait under their link's id.

A row learns its name when its download starts, and a row behind a host limit
can wait for hours first. Until then the list showed "name not found" for every
one of them. This loop looks the names up ahead of time: one request covers
every waiting 1fichier link, and other hosts get a light page read each.
"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from core import db_async
from core.db import SessionLocal
from core.download_core import _apply_hoster_file_info, _name_needs_resolution
from core.hoster_common import HosterParseError
from core.link_names import (
    fetch_fichier_names_sync,
    fetch_page_name_sync,
    fichier_file_id,
)
from core.models import DownloadRequest, StatusEnum


NAME_SWEEP_INTERVAL_SEC = 30
# A row whose lookup found nothing is asked again after this long. A host page
# can be briefly unreachable, and a name is worth a second look, not a stream.
NAME_RETRY_AFTER_SEC = 1800
# Page reads are one request per row; three per sweep keeps any one host far
# below anything it would notice.
PAGE_LOOKUPS_PER_SWEEP = 3
FICHIER_LINKS_PER_CHECK = 50

WAITING_STATUSES = (StatusEnum.pending, StatusEnum.stopped, StatusEnum.failed)

# Its own single thread: a page read can fall back to FlareSolverr and take
# minutes, which must not occupy the pool the API answers from.
_NAME_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="name-lookup")


def lookup_url(req) -> str:
    return req.original_url or req.url or ""


def pick_unnamed(rows, tried: Dict[int, float], now: float) -> List:
    """Rows still showing an id instead of a name and not asked about lately."""
    return [
        row for row in rows
        if _name_needs_resolution(row.file_name)
        and now - tried.get(row.id, float("-inf")) >= NAME_RETRY_AFTER_SEC
    ]


def _renamed(row, info) -> bool:
    """Apply what was found; true only when the row got a real name from it.

    A dead page can hand back just the code it was opened with, which fills in a
    size at most and is no name worth reporting.
    """
    before = row.file_name
    return _apply_hoster_file_info(row, info) and row.file_name != before


class NameResolver:
    def __init__(self):
        self._tried: Dict[int, float] = {}
        self._task: Optional[asyncio.Task] = None

    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    def stop(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _loop(self):
        while True:
            await asyncio.sleep(NAME_SWEEP_INTERVAL_SEC)
            # One failed sweep must not end the loop; the next tick tries again.
            try:
                await self.sweep()
            except Exception as e:
                print(f"[WARNING] 파일명 미리 찾기 실패: {e}")

    async def sweep(self):
        with SessionLocal() as db:
            rows = await db_async.all_rows(
                db.query(DownloadRequest)
                .filter(DownloadRequest.status.in_(WAITING_STATUSES))
                .order_by(DownloadRequest.id.asc())
            )
            todo = pick_unnamed(rows, self._tried, time.monotonic())
            if not todo:
                return
            fichier = [r for r in todo if fichier_file_id(lookup_url(r))]
            pages = [r for r in todo if not fichier_file_id(lookup_url(r))]
            named = await self._name_fichier_rows(fichier[:FICHIER_LINKS_PER_CHECK])
            named += await self._name_page_rows(pages[:PAGE_LOOKUPS_PER_SWEEP])
            if named:
                await db_async.commit(db)
                print(f"[LOG] 파일명 미리 찾음: {', '.join(named)}")

    async def _name_fichier_rows(self, rows) -> List[str]:
        if not rows:
            return []
        now = time.monotonic()
        for row in rows:
            self._tried[row.id] = now
        found = await asyncio.get_running_loop().run_in_executor(
            _NAME_EXECUTOR, fetch_fichier_names_sync, [lookup_url(r) for r in rows]
        )
        named = []
        for row in rows:
            info = found.get(fichier_file_id(lookup_url(row)))
            if info and _renamed(row, info):
                named.append(row.file_name)
        return named

    async def _name_page_rows(self, rows) -> List[str]:
        named = []
        loop = asyncio.get_running_loop()
        for row in rows:
            self._tried[row.id] = time.monotonic()
            try:
                info = await loop.run_in_executor(
                    _NAME_EXECUTOR, fetch_page_name_sync, lookup_url(row)
                )
            except HosterParseError as e:
                # The host said slow down (429). Leave the rest for later.
                print(f"[WARNING] 파일명 미리 찾기 중단 (id={row.id}): {e}")
                break
            if _renamed(row, info):
                named.append(row.file_name)
        return named


name_resolver = NameResolver()
