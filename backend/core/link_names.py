# -*- coding: utf-8 -*-
"""Find a file's real name while its row still waits in the queue.

A link is registered by its address alone, so until its download starts the row
shows only the id the address carried. Rows can wait for hours behind a host
limit, and a list of "name not found" rows tells the user nothing.

1fichier hides the name on its file page once this IP has spent its free
quota, but its public link checker still answers ``url;name;size`` for every
link, and ``url;;;NOT FOUND`` for a deleted one. Other hosts get the same light
page read the downloader already makes before a download.
"""

from __future__ import annotations

import html
import re
from typing import Dict, Iterable, Optional

import cloudscraper

from core.hoster_parsers import fetch_special_hoster_file_info_sync
from core.simple_parser import derive_display_name


FICHIER_CHECK_URL = "https://1fichier.com/check_links.pl"
FICHIER_CHECK_TIMEOUT_SEC = 30

_FICHIER_CHECK_LINE = re.compile(
    r"1fichier\.com/\?([A-Za-z0-9]+)[^;<\s]*;([^;<\n]*);([^<\n]*)"
)


def fichier_file_id(url: str) -> str:
    """The lowercase 1fichier file id of ``url``, or ``""`` for another host."""
    name = derive_display_name(url or "")
    return name.split(":", 1)[1].lower() if name.startswith("1fichier:") else ""


def parse_fichier_check(body: str) -> Dict[str, Optional[Dict[str, object]]]:
    """Map each file id in a link-checker answer to its info.

    A live file maps to ``{"name", "size_bytes"}``, a deleted one to ``None``.
    An id the answer does not mention is left out: nothing was learned about it.
    """
    found: Dict[str, Optional[Dict[str, object]]] = {}
    # Unescape first: an entity such as ``&amp;`` carries the ``;`` that
    # separates the fields.
    for file_id, name, rest in _FICHIER_CHECK_LINE.findall(html.unescape(body or "")):
        name = name.strip()
        if name:
            info: Dict[str, object] = {"name": name}
            size = rest.strip()
            if size.isdigit():
                info["size_bytes"] = int(size)
            found[file_id.lower()] = info
        elif "NOT FOUND" in rest.upper():
            found[file_id.lower()] = None
    return found


def fetch_fichier_names_sync(urls: Iterable[str]) -> Dict[str, Optional[Dict[str, object]]]:
    """Ask 1fichier's link checker about ``urls`` in one request."""
    links = [url for url in urls if fichier_file_id(url)]
    if not links:
        return {}
    scraper = cloudscraper.create_scraper()
    response = scraper.post(
        FICHIER_CHECK_URL,
        data={"links[]": links},
        timeout=FICHIER_CHECK_TIMEOUT_SEC,
    )
    response.raise_for_status()
    return parse_fichier_check(response.text)


def fetch_page_name_sync(url: str) -> Dict[str, object]:
    """Read the name from another host's file page. ``{}`` when it has none."""
    return fetch_special_hoster_file_info_sync(url) or {}
