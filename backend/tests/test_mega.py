# -*- coding: utf-8 -*-
"""Unit tests for the MEGA crypto primitives and the streaming decrypt path.

These never touch the network: the download test encrypts a known plaintext
with the same AES-CTR scheme MEGA uses, serves it through a fake stream, and
asserts the module decrypts it back byte-for-byte and validates the MAC.
"""

import json
import os

import pytest
from Crypto.Cipher import AES
from Crypto.Util import Counter

from core import mega_crypto as mc
from core import mega_hoster as mh


# ---------------------------------------------------------------------------
# mega_crypto primitives
# ---------------------------------------------------------------------------

class TestCryptoPrimitives:
    def test_a32_bytes_roundtrip(self):
        words = (1, 2, 0xDEADBEEF, 4)
        assert mc.bytes_to_a32(mc.a32_to_bytes(words)) == words

    def test_base64_url_decode_handles_missing_padding(self):
        # MEGA strips '=' padding and uses -/_ instead of +//.
        raw = b"hello mega"
        import base64
        enc = base64.b64encode(raw).decode().replace("+", "-").replace("/", "_").rstrip("=")
        assert mc.base64_url_decode(enc) == raw

    def test_unpack_file_key_xor_fold(self):
        fk = (0, 0, 0, 0, 1, 2, 3, 4)  # upper half XORs into the key
        aes_key, iv, meta_mac = mc.unpack_file_key(fk)
        assert aes_key == (1, 2, 3, 4)
        assert iv == (1, 2, 0, 0)
        assert meta_mac == (3, 4)

    def test_unpack_file_key_rejects_non_file_key(self):
        with pytest.raises(ValueError):
            mc.unpack_file_key((1, 2, 3, 4))  # folder-length key

    def test_decrypt_attr_roundtrip(self):
        aes_key = (1, 2, 3, 4)
        payload = ('MEGA' + json.dumps({"n": "file.rar"})).encode("latin-1")
        payload += b"\0" * ((16 - len(payload) % 16) % 16)
        enc = AES.new(mc.a32_to_bytes(aes_key), AES.MODE_CBC, b"\0" * 16).encrypt(payload)
        assert mc.decrypt_attr(enc, aes_key) == {"n": "file.rar"}

    def test_decrypt_attr_wrong_prefix_returns_empty(self):
        aes_key = (9, 9, 9, 9)
        enc = AES.new(mc.a32_to_bytes(aes_key), AES.MODE_CBC, b"\0" * 16).encrypt(b"\0" * 16)
        assert mc.decrypt_attr(enc, aes_key) == {}

    def test_get_chunks_cover_size_without_gaps(self):
        size = 700_000
        chunks = list(mc.get_chunks(size))
        assert chunks[0] == (0, 0x20000)               # first chunk is 128 KiB
        assert sum(length for _o, length in chunks) == size
        # contiguous, non-overlapping
        expected_offset = 0
        for offset, length in chunks:
            assert offset == expected_offset
            expected_offset += length


# ---------------------------------------------------------------------------
# parse_mega_url
# ---------------------------------------------------------------------------

class TestParseUrl:
    def test_new_format(self):
        fid, key = mh.parse_mega_url("https://mega.nz/file/AbCdEfGh#TheSecretKey123")
        assert fid == "AbCdEfGh"
        assert key == "TheSecretKey123"

    def test_legacy_format(self):
        fid, key = mh.parse_mega_url("https://mega.nz/#!7V8zGDiK!VbkkCyKey")
        assert fid == "7V8zGDiK"
        assert key == "VbkkCyKey"

    def test_folder_link_rejected(self):
        with pytest.raises(ValueError):
            mh.parse_mega_url("https://mega.nz/folder/AbCd#key")

    def test_missing_key_rejected(self):
        with pytest.raises(ValueError):
            mh.parse_mega_url("https://mega.nz/file/AbCdEfGh")

    def test_non_mega_rejected(self):
        with pytest.raises(ValueError):
            mh.parse_mega_url("https://example.com/file/x#y")


# ---------------------------------------------------------------------------
# MegaApiError classification
# ---------------------------------------------------------------------------

class TestApiError:
    def test_dead_codes(self):
        assert mh.MegaApiError(-9).is_dead
        assert mh.MegaApiError(-16).is_dead
        assert not mh.MegaApiError(-9).is_quota

    def test_quota_code(self):
        assert mh.MegaApiError(-17).is_quota
        assert not mh.MegaApiError(-17).is_dead


# ---------------------------------------------------------------------------
# Streaming decrypt (fake stream, no network)
# ---------------------------------------------------------------------------

class _FakeStream:
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    async def read(self, n: int) -> bytes:
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


class _FakeResponse:
    def __init__(self, data: bytes):
        self.content = _FakeStream(data)

    def raise_for_status(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, data: bytes):
        self._data = data

    def get(self, url, **kwargs):
        return _FakeResponse(self._data)


def _encrypt_ctr(plaintext: bytes, aes_key: bytes, iv) -> bytes:
    counter = Counter.new(128, initial_value=((iv[0] << 32) + iv[1]) << 64)
    return AES.new(aes_key, AES.MODE_CTR, counter=counter).encrypt(plaintext)


def _expected_meta_mac(plaintext: bytes, aes_key: bytes, iv) -> tuple:
    mac = mh._ChainedCbcMac(aes_key, iv)
    for offset, length in mc.get_chunks(len(plaintext)):
        mac.update(plaintext[offset:offset + length])
    return mac.result()


@pytest.mark.asyncio
async def test_streaming_decrypt_roundtrip(tmp_path):
    aes_key = mc.a32_to_bytes((11, 22, 33, 44))
    iv = (55, 66, 0, 0)
    plaintext = os.urandom(400_000)  # spans 128K + 256K + tail chunks
    encrypted = _encrypt_ctr(plaintext, aes_key, iv)

    info = mh.MegaFileInfo(
        download_url="https://example/dl",
        size=len(plaintext),
        name="sample.bin",
        aes_key=aes_key,
        iv=iv,
        meta_mac=_expected_meta_mac(plaintext, aes_key, iv),
    )
    dest = tmp_path / "out.bin"
    progress = []
    written = await mh.download_mega_file(
        _FakeSession(encrypted), info, str(dest),
        progress_cb=lambda d, t: progress.append((d, t)),
    )

    assert written == len(plaintext)
    assert dest.read_bytes() == plaintext          # CTR decrypt is correct
    assert progress[-1] == (len(plaintext), len(plaintext))


@pytest.mark.asyncio
async def test_streaming_decrypt_cancel(tmp_path):
    aes_key = mc.a32_to_bytes((1, 2, 3, 4))
    iv = (7, 8, 0, 0)
    plaintext = os.urandom(300_000)
    info = mh.MegaFileInfo(
        download_url="x", size=len(plaintext), name="c.bin",
        aes_key=aes_key, iv=iv, meta_mac=(0, 0),
    )
    with pytest.raises(__import__("asyncio").CancelledError):
        await mh.download_mega_file(
            _FakeSession(_encrypt_ctr(plaintext, aes_key, iv)),
            info, str(tmp_path / "c.bin"),
            is_cancelled=lambda: True,
        )


class TestErrorClassification:
    """MegaApiError → message → central classifier must land on the right kind."""

    def test_dead_maps_to_dead_kind(self):
        from core.error_messages import classify_failure_text, KIND_DEAD
        msg = mh.mega_error_message(mh.MegaApiError(-9))
        assert classify_failure_text(msg) == KIND_DEAD

    def test_quota_maps_to_rate_limited(self):
        from core.error_messages import classify_failure_text, KIND_RATE_LIMITED
        msg = mh.mega_error_message(mh.MegaApiError(-17))
        assert classify_failure_text(msg) == KIND_RATE_LIMITED

    def test_transient_maps_to_transient(self):
        from core.error_messages import classify_failure_text, KIND_TRANSIENT
        msg = mh.mega_error_message(mh.MegaApiError(-3))
        assert classify_failure_text(msg) == KIND_TRANSIENT

    def test_is_mega_url(self):
        assert mh.is_mega_url("https://mega.nz/file/abc#key")
        assert mh.is_mega_url("https://mega.nz/#!abc!key")
        assert not mh.is_mega_url("https://mega.nz/folder/abc#key")
        assert not mh.is_mega_url("https://1fichier.com/?x")
