# -*- coding: utf-8 -*-
"""The release-site tag glued onto a filename, and how to take it off.

Uploaders sign their releases in the name itself — ``...-NSP-ES-Ziperto.rar``,
``... - NxBrew.zip``. Which site or host a download came from is already shown
next to the row as a badge (see ``core.hoster_labels``), so carrying it inside
the filename says the same thing twice and follows the file onto disk and onto
the NAS.

One list, used both for page titles (``core.hoster_common``) and for the stored
filename, so adding a site lights up both with no second edit.
"""

import re

# Tags actually observed in filenames and page titles. Kept deliberately short:
# every entry is a real signature seen in the wild, not a guess, because each
# one is a chance to eat part of a legitimate name.
SITE_TAGS = ("Ziperto", "NxBrew", "MegaUp", "Rapidgator")

_TAG = r"(?:" + "|".join(SITE_TAGS) + r")"

# Separator run between the name and the tag: " - ", "-", "_", ".", or nothing.
_SEP = r"[\s._+-]*"

# A trailing extension chain: ".rar", ".part1.rar", ".r01", ".001", ".tar.gz".
# ``part\d+`` is spelled out because it is longer than the 4 characters a
# plain extension gets.
_EXT_CHAIN = r"(?:\.(?:part\d+|[A-Za-z0-9]{1,4}))+$"

# The tag, with its leading separator and optional brackets, when it sits at the
# very end of the name or immediately before the extension chain. The lookbehind
# keeps "Supersonic" safe when the separator run matches empty.
_FILENAME_SITE_TAG_RE = re.compile(
    rf"{_SEP}[\[\(]?(?:by{_SEP})?(?<![A-Za-z0-9]){_TAG}[\]\)]?(?={_EXT_CHAIN}|$)",
    re.I,
)


def strip_site_tag(name: str) -> str:
    """Return ``name`` without its trailing release-site tag.

    ``FOO-NSP-ES-Ziperto.part1.rar`` → ``FOO-NSP-ES.part1.rar``. A name that
    carries no tag comes back unchanged, and a name that is *only* a tag is
    left alone — a row labelled ``.rar`` would be worse than the tag.
    """
    if not name:
        return name

    cleaned = _FILENAME_SITE_TAG_RE.sub("", name, count=1)
    stem = cleaned.split(".", 1)[0].strip()
    if not stem:
        return name
    return cleaned
