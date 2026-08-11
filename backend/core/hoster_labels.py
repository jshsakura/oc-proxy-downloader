# -*- coding: utf-8 -*-
"""The hoster name to show next to a download.

Which host a link came from decides what the user can expect — a 1fichier free
slot waits, DataNodes needs a captcha, MEGA is quota-bound — so the grid shows
it. The mapping lives here rather than in the frontend because HOSTER_REGISTRY
is the authority on which hosts are supported and under what name; a second
copy in Svelte would drift the first time a host is added.
"""

from __future__ import annotations

from typing import Optional

from core.hoster_common import _host
from core.hoster_parsers import _HOST_TO_SPEC


# A stable slug per host family, used to colour the badge. Kept separate from
# the display label because the label is prose that may be reworded, while this
# is a key a stylesheet keys off. The palette itself lives in the stylesheet —
# colour is presentation, and it mirrors oc-scraper's host palette so the same
# host looks the same in both apps.
_SLUGS = {
    "1fichier.com": "1fichier",
    "mega.nz": "mega",
    "mega.co.nz": "mega",
    "ouo.io": "ouo",
    "ouo.press": "ouo",
    "megaup.net": "megaup",
    "datanodes.to": "datanodes",
    "rapidgator.net": "rapidgator",
    "gofile.io": "gofile",
    "send.now": "sendnow",
    "mediafire.com": "mediafire",
    "pixeldrain.com": "pixeldrain",
    "multiup.io": "multiup",
    "vikingfile.com": "vikingfile",
}


def hoster_slug(url: Optional[str]) -> str:
    """Stable key for ``url``'s host family, or "" when unknown."""
    host = _host(url or "")
    if not host:
        return ""
    bare = host.removeprefix("www.")
    for domain, slug in _SLUGS.items():
        if bare == domain or bare.endswith(f".{domain}"):
            return slug
    # Bunkr rotates domains; they all share one badge.
    if bare.startswith("bunkr") or ".bunkr" in bare:
        return "bunkr"
    return ""


# Hosts handled outside HOSTER_REGISTRY (they have their own parse paths).
_EXTRA_LABELS = {
    "1fichier.com": "1fichier",
    "mega.nz": "MEGA",
    "mega.co.nz": "MEGA",
    "ouo.io": "ouo",
    "ouo.press": "ouo",
}


def hoster_label(url: Optional[str]) -> str:
    """Display name for ``url``'s host, or "" when there is no host.

    Matches subdomains too: a resolved 1fichier link points at a download node
    like ``a-7.1fichier.com``, and labelling that as the raw hostname would tell
    the user nothing they wanted to know.

    Falls back to the bare hostname for anything unsupported, which beats
    "Unknown" — it says exactly where the link points.
    """
    host = _host(url or "")
    if not host:
        return ""

    bare = host.removeprefix("www.")

    for domain, label in _EXTRA_LABELS.items():
        if bare == domain or bare.endswith(f".{domain}"):
            return label

    spec = _HOST_TO_SPEC.get(host) or _HOST_TO_SPEC.get(bare)
    if spec is not None:
        return spec.name
    for domain, candidate in _HOST_TO_SPEC.items():
        if bare.endswith(f".{domain}"):
            return candidate.name
    return bare
