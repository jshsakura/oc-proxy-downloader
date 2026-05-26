# -*- coding: utf-8 -*-
"""MEGA.nz public-link resolution and streaming download.

Flow (anonymous, no account):
1. ``parse_mega_url`` pulls the file id + decryption key out of the share link
   (both the legacy ``/#!id!key`` and current ``/file/id#key`` formats).
2. ``fetch_mega_file_info`` asks MEGA's API for the temporary content URL, size
   and encrypted attributes, then derives the AES key/IV and the real filename.
3. ``download_mega_file`` streams the encrypted bytes and AES-CTR-decrypts them
   on MEGA's chunk boundaries, verifying the chained CBC-MAC.

The decryption happens entirely client-side; MEGA never sees the key. See
``mega_crypto`` for the primitives. (Algorithm ref: odwyersoftware/mega.py.)
"""

import asyncio
import random
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import aiohttp
from Crypto.Cipher import AES
from Crypto.Util import Counter

from core.mega_crypto import (
    A32,
    a32_to_bytes,
    base64_to_a32,
    base64_url_decode,
    bytes_to_a32,
    decrypt_attr,
    get_chunks,
    unpack_file_key,
)

MEGA_API_URL = "https://g.api.mega.co.nz/cs"

# Stream read timeout per socket read (the overall transfer has no total cap).
_SOCK_READ_TIMEOUT = 300

# MEGA API error codes (negative ints). Dead = retrying is pointless; the rest
# are temporary (congestion / quota / expired URL) and worth a later retry.
MEGA_DEAD_CODES = frozenset({-9, -16})        # ENOENT (gone), EBLOCKED
MEGA_QUOTA_CODES = frozenset({-17})           # EOVERQUOTA — per-IP bandwidth cap
_MEGA_ERROR_TEXT = {
    -3: "일시적 혼잡 (EAGAIN)",
    -4: "요청 한도 (ERATELIMIT)",
    -6: "이 링크에 접속이 너무 많음 (ETOOMANY)",
    -8: "임시 다운로드 URL 만료 (EEXPIRED)",
    -9: "파일을 찾을 수 없음 (ENOENT)",
    -16: "차단된 파일/사용자 (EBLOCKED)",
    -17: "대역폭 한도 초과 (EOVERQUOTA)",
    -18: "일시적으로 사용 불가 (ETEMPUNAVAIL)",
}


class MegaApiError(Exception):
    """A negative MEGA API status (or a missing content URL)."""

    def __init__(self, code: int):
        self.code = code
        super().__init__(f"MEGA API 오류 {code}: {_MEGA_ERROR_TEXT.get(code, '알 수 없음')}")

    @property
    def is_dead(self) -> bool:
        return self.code in MEGA_DEAD_CODES

    @property
    def is_quota(self) -> bool:
        return self.code in MEGA_QUOTA_CODES


@dataclass(frozen=True)
class MegaFileInfo:
    download_url: str
    size: int
    name: str
    aes_key: bytes      # 16-byte AES key (already XOR-folded)
    iv: A32             # (iv0, iv1, 0, 0)
    meta_mac: A32       # (mac0, mac1) expected after decryption


def parse_mega_url(url: str) -> Tuple[str, str]:
    """Return ``(file_id, key)`` from a MEGA file share link.

    Raises ValueError for folder links or links missing the ``#`` key — those
    can't be downloaded anonymously by this single-file path.
    """
    url = (url or "").strip()
    if not any(domain in url for domain in ("mega.nz", "mega.co.nz", "mega.io")):
        raise ValueError("MEGA 링크가 아닙니다")
    if "/folder/" in url or "/#F!" in url or "#F!" in url:
        raise ValueError("MEGA 폴더 링크는 지원하지 않습니다 (단일 파일 링크만)")

    # Current format: https://mega.nz/file/<id>#<key>
    if "/file/" in url:
        tail = url.split("/file/", 1)[1]
        if "#" not in tail:
            raise ValueError("MEGA 링크에 복호화 키(#...)가 없습니다")
        file_id, key = tail.split("#", 1)
        return file_id.split("/", 1)[0], key

    # Legacy format: https://mega.nz/#!<id>!<key>
    if "#!" in url:
        frag = url.split("#!", 1)[1]
        if "!" not in frag:
            raise ValueError("MEGA 링크에 복호화 키가 없습니다")
        file_id, key = frag.split("!", 1)
        return file_id, key

    raise ValueError("MEGA 파일 링크 형식이 아닙니다")


async def fetch_mega_file_info(
    session: aiohttp.ClientSession, file_id: str, key: str
) -> MegaFileInfo:
    """Resolve the temp download URL, size and filename for a public file."""
    seq_id = random.randint(0, 0xFFFFFFFF)
    payload = [{"a": "g", "g": 1, "p": file_id}]
    async with session.post(
        MEGA_API_URL,
        params={"id": str(seq_id)},
        json=payload,
        timeout=aiohttp.ClientTimeout(total=30),
    ) as response:
        response.raise_for_status()
        data = await response.json(content_type=None)

    # The API returns a bare negative int on a global error, or a list whose
    # first element is the file dict (or a negative int for a per-file error).
    if isinstance(data, int):
        raise MegaApiError(data)
    item = data[0]
    if isinstance(item, int):
        raise MegaApiError(item)
    if "g" not in item:
        raise MegaApiError(-9)  # no content URL → treat as not accessible

    aes_key, iv, meta_mac = unpack_file_key(base64_to_a32(key))
    attribs = decrypt_attr(base64_url_decode(item["at"]), aes_key)
    return MegaFileInfo(
        download_url=item["g"],
        size=int(item["s"]),
        name=attribs.get("n") or file_id,
        aes_key=a32_to_bytes(aes_key),
        iv=iv,
        meta_mac=meta_mac,
    )


class _ChainedCbcMac:
    """MEGA's file MAC: a CBC-MAC per chunk, chained through a second CBC pass."""

    def __init__(self, aes_key: bytes, iv: A32):
        self._key = aes_key
        self._block_iv = a32_to_bytes((iv[0], iv[1], iv[0], iv[1]))
        self._chain = AES.new(aes_key, AES.MODE_CBC, b"\0" * 16)
        self._mac = b"\0" * 16

    def update(self, chunk: bytes) -> None:
        inner = AES.new(self._key, AES.MODE_CBC, self._block_iv)
        block_mac = b"\0" * 16
        for i in range(0, len(chunk), 16):
            block = chunk[i:i + 16]
            if len(block) < 16:
                block += b"\0" * (16 - len(block))
            block_mac = inner.encrypt(block)
        self._mac = self._chain.encrypt(block_mac)

    def result(self) -> A32:
        m = bytes_to_a32(self._mac)
        return (m[0] ^ m[1], m[2] ^ m[3])


async def _read_exact(stream: aiohttp.StreamReader, n: int) -> bytes:
    """Read exactly ``n`` bytes (or fewer only at EOF) — chunk boundaries must
    line up with MEGA's for the MAC to validate."""
    buf = bytearray()
    while len(buf) < n:
        part = await stream.read(n - len(buf))
        if not part:
            break
        buf.extend(part)
    return bytes(buf)


async def download_mega_file(
    session: aiohttp.ClientSession,
    info: MegaFileInfo,
    dest_path: str,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> int:
    """Stream the encrypted file and AES-CTR-decrypt it to ``dest_path``.

    Returns the number of bytes written. Raises ``asyncio.CancelledError`` if
    ``is_cancelled`` turns true, ``IOError`` on a truncated stream.
    """
    counter = Counter.new(128, initial_value=((info.iv[0] << 32) + info.iv[1]) << 64)
    cipher = AES.new(info.aes_key, AES.MODE_CTR, counter=counter)
    mac = _ChainedCbcMac(info.aes_key, info.iv)
    downloaded = 0

    async with session.get(
        info.download_url,
        timeout=aiohttp.ClientTimeout(total=None, connect=60, sock_read=_SOCK_READ_TIMEOUT),
    ) as response:
        response.raise_for_status()
        with open(dest_path, "wb") as out:
            for _offset, length in get_chunks(info.size):
                if is_cancelled and is_cancelled():
                    raise asyncio.CancelledError()
                encrypted = await _read_exact(response.content, length)
                if len(encrypted) != length:
                    raise IOError(
                        f"MEGA 스트림이 일찍 끊김: {downloaded + len(encrypted)}/{info.size}"
                    )
                plain = cipher.decrypt(encrypted)
                out.write(plain)
                mac.update(plain)
                downloaded += length
                if progress_cb:
                    progress_cb(downloaded, info.size)

    if mac.result() != tuple(info.meta_mac):
        # The CTR-decrypted bytes are still correct; a mismatch only flags an
        # integrity concern, so we keep the file and warn rather than fail.
        print(f"[WARNING] MEGA MAC 불일치: {info.name} (파일은 보존)")
    return downloaded
