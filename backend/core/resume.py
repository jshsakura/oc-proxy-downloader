# -*- coding: utf-8 -*-
"""Range-resume rules for the download path.

Two things a server does to a ``Range`` request cost us finished downloads, and
the reasoning for both lives here rather than inline at the two call sites:

1. **A ``200`` answering a ``Range`` request means the range was ignored** — the
   body is the whole file, starting at byte zero. Appending it to the existing
   ``.part`` doubles the file, and reading the total as
   ``Content-Length + initial_size`` inflates it by exactly the bytes already on
   disk. The completeness check then rejects a perfectly good file, forever.

2. **A ``416`` means the ``.part`` is already at or past the end.** RFC 7233 has
   the server state the resource's real length in ``Content-Range: bytes */N``,
   which is enough to tell a finished download from a corrupt over-long one
   without fetching a single byte.
"""

import re

PARTIAL_CONTENT = 206
RANGE_NOT_SATISFIABLE = 416

# Matches the complete-length after the slash in either Content-Range form:
# "bytes */1234" (unsatisfied) and "bytes 0-99/1234" (satisfied). A "*" total
# means the server does not know the length, and deliberately does not match.
_COMPLETE_LENGTH = re.compile(r"/\s*(\d+)\s*$")


def effective_initial_size(status: int, requested_offset: int) -> int:
    """Bytes already on disk that the response body actually continues from.

    Only ``206`` resumes where we asked. Anything else restarts the body at byte
    zero, so what is on disk must be overwritten rather than appended to.
    """
    if requested_offset <= 0:
        return 0
    return requested_offset if status == PARTIAL_CONTENT else 0


def total_size_from_content_length(content_length, initial_size: int):
    """The resource's full length, or ``None`` when the header is unusable.

    ``initial_size`` must already be the *effective* offset — a resumed body
    states only the remainder, so the bytes on disk are added back.
    """
    if content_length is None:
        return None
    text = str(content_length).strip()
    if not text.isdigit():
        return None
    return int(text) + max(initial_size, 0)


def complete_length(content_range):
    """The total length a ``Content-Range`` header states, if it states one."""
    if not content_range:
        return None
    match = _COMPLETE_LENGTH.search(str(content_range))
    return int(match.group(1)) if match else None


def is_part_already_complete(content_range, part_size: int) -> bool:
    """Whether a ``416`` response proves the ``.part`` on disk is the whole file.

    Without a stated length we cannot make that claim, so the caller re-downloads
    instead of finalizing a file it has not verified.
    """
    total = complete_length(content_range)
    return total is not None and total == part_size
