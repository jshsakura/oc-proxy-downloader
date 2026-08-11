# -*- coding: utf-8 -*-
"""What each hoster's page says when the file is gone.

Every rule here was read off a live response — a fabricated file id per host,
so whatever came back *is* that host's "file is gone" page. Nothing is guessed,
because a wrong dead marker pins a working link and the retry path then refuses
to touch it.

Two findings shape the rules:

* Send.now answers **200** for a missing file and only says so in the title, so
  the HTTP status alone cannot be trusted.
* GoFile serves a JavaScript shell with no file information in the HTML at all,
  so it has no marker and stays undecidable here — reporting "unknown" is the
  honest answer, and better than the alternative of calling a live file dead.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from core.hoster_sites import BUNKR_HOSTS


# Substrings that only appear once the file is gone. Matched against the page's
# visible text, case-insensitively.
DEAD_MARKERS: Dict[str, Tuple[str, ...]] = {
    "datanodes.to": (
        "file not found",
        "could not be found",
    ),
    "megaup.net": (
        "file not found",
        "no longer available",
    ),
    "pixeldrain.com": (
        "404, file not found",
    ),
    "mediafire.com": (
        "invalid or deleted file",
        "the key you provided for file access was invalid",
    ),
    "send.now": (
        "the file you were looking for doesn't exist",
        "404 - the file doesn't exist",
    ),
}

# Bunkr rotates through a long list of domains; the page is the same on all of
# them, so the markers are registered against every one the registry knows.
_BUNKR_MARKERS = (
    "resource not found",
    "removed by the original uploader",
)
for _host in BUNKR_HOSTS:
    DEAD_MARKERS[_host] = _BUNKR_MARKERS


# Hosts whose page cannot be judged from HTML. Kept explicit so "no marker" is a
# deliberate decision rather than an oversight — see the GoFile note above.
UNDECIDABLE_HOSTS = frozenset({"gofile.io"})

# A page that still shows the file's own details is alive. Generic enough to
# hold across hosts: a file page names a size, a "file is gone" page does not.
ALIVE_MARKERS: Tuple[str, ...] = (
    "downloaded",      # datanodes: "Downloaded 60 times"
    "download file",   # megaup
    "file info",
)


def dead_markers_for(host: str) -> Tuple[str, ...]:
    """Dead markers registered for ``host``, matching parent domains too."""
    bare = (host or "").lower().removeprefix("www.")
    if bare in DEAD_MARKERS:
        return DEAD_MARKERS[bare]
    for domain, markers in DEAD_MARKERS.items():
        if bare.endswith(f".{domain}"):
            return markers
    return ()


def is_undecidable(host: str) -> bool:
    bare = (host or "").lower().removeprefix("www.")
    return bare in UNDECIDABLE_HOSTS or any(
        bare.endswith(f".{domain}") for domain in UNDECIDABLE_HOSTS
    )


def find_dead_marker(host: str, visible_text: str) -> Optional[str]:
    """The dead marker present in ``visible_text``, or None."""
    lowered = (visible_text or "").lower()
    for marker in dead_markers_for(host):
        if marker in lowered:
            return marker
    return None


def looks_like_a_file_page(visible_text: str) -> bool:
    lowered = (visible_text or "").lower()
    return any(marker in lowered for marker in ALIVE_MARKERS)
