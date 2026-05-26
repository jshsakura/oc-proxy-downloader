# -*- coding: utf-8 -*-
"""Pure MEGA crypto primitives — no network, no app dependencies.

MEGA encrypts files client-side: the decryption key travels in the share-link
fragment (after ``#``) and never reaches MEGA's servers. These helpers implement
MEGA's published algorithm (the same one in its open SDK / web client):

- keys/IVs are handled as tuples of unsigned 32-bit big-endian words ("a32"),
- the file key is the XOR-fold of an 8-word blob into a 4-word AES key,
- file attributes (the filename) are AES-CBC encrypted with a ``MEGA{...}`` JSON
  body, and file contents are AES-CTR encrypted with a chained CBC-MAC.

Adapted from the MEGA protocol (ref: odwyersoftware/mega.py, Apache-2.0).
"""

import base64
import json
import struct
from typing import Dict, Iterator, Tuple

from Crypto.Cipher import AES

A32 = Tuple[int, ...]

# MEGA streams contents in growing chunks: 128 KiB, ramping by 128 KiB up to a
# 1 MiB cap. The CBC-MAC is computed per chunk, so downloads MUST be split on
# exactly these boundaries for the integrity check to validate.
_CHUNK_START = 0x20000   # 128 KiB
_CHUNK_MAX = 0x100000    # 1 MiB


def a32_to_bytes(a: A32) -> bytes:
    """Pack big-endian 32-bit words into bytes."""
    return struct.pack(f">{len(a)}I", *a)


def bytes_to_a32(b: bytes) -> A32:
    """Unpack bytes into big-endian 32-bit words (zero-padded to a multiple of 4)."""
    if len(b) % 4:
        b += b"\0" * (4 - len(b) % 4)
    return struct.unpack(f">{len(b) // 4}I", b)


def base64_url_decode(data: str) -> bytes:
    """Decode MEGA's URL-safe, unpadded base64 variant."""
    data += "==" [(2 - len(data) * 3) % 4:]
    data = data.replace("-", "+").replace("_", "/").replace(",", "")
    return base64.b64decode(data)


def base64_to_a32(s: str) -> A32:
    return bytes_to_a32(base64_url_decode(s))


def unpack_file_key(file_key: A32) -> Tuple[A32, A32, A32]:
    """Split a MEGA 8-word file key into (aes_key, iv, meta_mac).

    The AES key is the XOR-fold of the two halves; the IV and meta-MAC come from
    the upper half. Raises ValueError for anything that isn't an 8-word file key
    (e.g. a folder key), so callers fail clearly rather than mis-decrypting.
    """
    if len(file_key) != 8:
        raise ValueError(f"expected an 8-word file key, got {len(file_key)} words")
    aes_key = (
        file_key[0] ^ file_key[4],
        file_key[1] ^ file_key[5],
        file_key[2] ^ file_key[6],
        file_key[3] ^ file_key[7],
    )
    iv = file_key[4:6] + (0, 0)
    meta_mac = file_key[6:8]
    return aes_key, iv, meta_mac


def decrypt_attr(attr: bytes, aes_key: A32) -> Dict[str, str]:
    """Decrypt MEGA file attributes (AES-CBC, zero IV) into a dict.

    The plaintext is ``MEGA`` followed by a JSON object, e.g. ``MEGA{"n":"a.rar"}``.
    Returns ``{}`` when the prefix is absent (wrong key / corrupt data).
    """
    cipher = AES.new(a32_to_bytes(aes_key), AES.MODE_CBC, b"\0" * 16)
    plain = cipher.decrypt(attr).decode("latin-1").rstrip("\0")
    if plain[:6] != 'MEGA{"':
        return {}
    return json.loads(plain[4:])


def get_chunks(size: int) -> Iterator[Tuple[int, int]]:
    """Yield ``(offset, length)`` pairs over MEGA's chunk boundaries."""
    offset = 0
    step = _CHUNK_START
    while offset + step < size:
        yield offset, step
        offset += step
        if step < _CHUNK_MAX:
            step += _CHUNK_START
    yield offset, size - offset
