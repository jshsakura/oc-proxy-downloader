# -*- coding: utf-8 -*-
"""Move a file to its next link when the current one is stuck.

A collector can register one file with several links on different hosts. The
row starts on the first; when that link is deleted, cannot be parsed, or sits
behind a host's wait such as a spent 1fichier quota, the row moves to the next
link instead of failing or waiting. Only when every link has been used does
the row end as the last one ended.
"""

from __future__ import annotations

import datetime
import json
import os
from typing import List, Optional

from core.hoster_parsers import should_preserve_original_url
from core.link_admission import enqueue_link_error
from core.link_containers import is_container_url
from core.models import StatusEnum
from core.simple_parser import clean_1fichier_url
from services.ouo_unwrap_service import is_ouo_url


MAX_MIRRORS = 10
# A row scheduled further out than this is waiting on a host, not on its turn.
WAIT_FAILOVER_SEC = 120


def original_url_for(url: str) -> Optional[str]:
    """The ``original_url`` a row registered with ``url`` keeps."""
    keep = (
        is_ouo_url(url) or is_container_url(url)
        or "1fichier.com" in url or should_preserve_original_url(url)
    )
    return url if keep else None


def clean_mirrors(url: str, mirrors) -> List[str]:
    """Usable alternative links, in order, without the main link or repeats."""
    if not isinstance(mirrors, list):
        return []
    cleaned: List[str] = []
    for mirror in mirrors:
        if not isinstance(mirror, str) or not mirror.strip():
            continue
        mirror = mirror.strip()
        if not is_ouo_url(mirror):
            mirror = clean_1fichier_url(mirror)
        if enqueue_link_error(mirror) or mirror == url or mirror in cleaned:
            continue
        cleaned.append(mirror)
    return cleaned[:MAX_MIRRORS]


def remaining_mirrors(req) -> List[str]:
    try:
        mirrors = json.loads(getattr(req, "mirror_urls", None) or "[]")
    except ValueError:
        return []
    return [m for m in mirrors if isinstance(m, str)] if isinstance(mirrors, list) else []


def needs_failover(req, now: datetime.datetime, active_ids) -> bool:
    """True when ``req`` is stuck on its link and another link is left."""
    if not remaining_mirrors(req) or req.id in active_ids:
        return False
    if req.status == StatusEnum.failed:
        return True
    if req.status == StatusEnum.pending and req.next_retry_at:
        return (req.next_retry_at - now).total_seconds() > WAIT_FAILOVER_SEC
    return False


def switch_to_next_mirror(req, now: datetime.datetime) -> str:
    """Put ``req`` on its next link and queue it now. Returns that link."""
    mirrors = remaining_mirrors(req)
    previous, nxt = req.url, mirrors[0]
    req.mirror_urls = json.dumps(mirrors[1:]) if len(mirrors) > 1 else None
    # A partial file from the previous host need not be the same bytes.
    if req.save_path and req.save_path.endswith(".part") and os.path.exists(req.save_path):
        os.remove(req.save_path)
    req.save_path = None
    req.downloaded_size = 0
    req.total_size = 0
    req.url = nxt
    req.original_url = original_url_for(nxt)
    req.status = StatusEnum.pending
    req.failure_kind = None
    req.attempt_count = 0
    req.next_retry_at = now
    req.finished_at = None
    left = len(mirrors) - 1
    req.error = f"다른 링크로 바꿔 다시 시도합니다 (남은 링크 {left}개)"
    print(f"[LOG] 다음 링크로 전환: id={req.id} {previous} → {nxt} (남은 {left}개)")
    return nxt
