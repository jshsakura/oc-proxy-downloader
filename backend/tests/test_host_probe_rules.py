# -*- coding: utf-8 -*-
"""Per-host verdicts, checked against pages these hosts actually served.

Each body below was captured from the live host by requesting a fabricated file
id, so it is that host's real "file is gone" page — not an invented fixture. A
guessed marker is worse than no marker: it pins a working link as dead and the
retry path then refuses to touch it, which is exactly how 248 rows got stuck.

Two of the captures overturn the obvious implementation:

* Send.now answers **HTTP 200** for a missing file — status alone would call it
  alive.
* GoFile serves a JavaScript shell with no file information in the HTML, so
  there is nothing to read and "unknown" is the only honest answer.
"""

import asyncio

import pytest

from core.error_messages import KIND_DEAD, KIND_TRANSIENT, KIND_UNKNOWN
from services import link_probe
from services.host_probe_rules import find_dead_marker, looks_like_a_file_page
from services.link_probe import KIND_ALIVE, probe_url


# --- captured responses ----------------------------------------------------

DEAD_PAGES = {
    "https://datanodes.to/zzq9x1aa22bb": (404, """<html><head><title>Download</title></head><body>
        Home Upload App Pricing Login Get started AD UNK File Not Found Join us now!
        Register File info UNK The file you were looking for could not be found,
        sorry for any inconvenience</body></html>"""),
    "https://megaup.net/zzq9/nope.rar": (404, """<html><head><title>Error - MegaUp</title></head><body>
        Home Contact DMCA FAQ Premium Login Register File Not Found The file you are
        trying to download is no longer available!</body></html>"""),
    "https://pixeldrain.com/u/zzq9x1aa": (404, """<html><head><title>404, File Not Found ~ pixeldrain</title></head>
        <body>menu Home Get Premium Login 404, File Not Found! This file...</body></html>"""),
    "https://www.mediafire.com/file/zzq9/nope.rar/file": (404, """<html><head><title>File sharing made simple</title></head>
        <body>MediaFire My Account Invalid or Deleted File. Well, looks like we can't go
        any further</body></html>"""),
    "https://bunkr.si/f/zzq9x1aa22bb": (404, """<html><head><title>Not Found | BUNKR</title></head><body>
        Resource not found The requested page has been removed by the original uploader
        or has been removed by an Admin.</body></html>"""),
    # The one that breaks status-based logic: 200 for a file that is gone.
    "https://send.now/zzq9x1aa22bb": (200, """<html><head><title>404 - The file doesn't exist</title></head>
        <body>SEND Main Navigation Upload Pricing The file you were looking for doesn't
        exist. Close Upload new</body></html>"""),
}

ALIVE_PAGES = {
    "https://datanodes.to/bcni98t4r5a1": (200, """<html><head><title>Download R-Type Tactics part1 rar</title></head>
        <body>Home Upload App Pricing FILE Downloading R-Type Tactics I-II Cosmos
        [01003A8019D74000][v0].rar 6.0 GB Downloaded 60 times Added Jul 28, 2026</body></html>"""),
    "https://megaup.net/8b79/LRA.rar": (200, """<html><head><title>LRA-(Korea)-NSwTcH-NSP.rar - MegaUp</title></head>
        <body>Home Contact DMCA FAQ Premium LRA-(Korea)-NSwTcH-NSP.rar (85.90 MB)
        DOWNLOAD FILE WAIT</body></html>"""),
}

GOFILE_SHELL = (200, """<html><head><title>Gofile — Cloud Storage Made Simple</title></head>
    <body>Skip to content Gofile needs JavaScript to run. Please enable it and reload
    the page.</body></html>""")


class _FakeResponse:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text


def _serve(pages):
    """Stand in for the network so the verdicts are the only thing under test."""
    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            status, body = pages[url]
            return _FakeResponse(status, body)

    return lambda **kwargs: _Client()


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """The 3s inter-request throttle is real behaviour, not something to wait on."""
    async def _instant():
        return None

    monkeypatch.setattr(link_probe._throttle, "wait", _instant)


class TestDeadPages:

    @pytest.mark.parametrize("url", list(DEAD_PAGES))
    def test_a_gone_file_is_pinned_dead(self, url, monkeypatch):
        monkeypatch.setattr(link_probe.httpx, "AsyncClient", _serve(DEAD_PAGES))

        probe = asyncio.run(probe_url(url))

        assert probe.kind == KIND_DEAD
        assert probe.definitive is True

    def test_send_now_is_caught_despite_answering_200(self, monkeypatch):
        """The capture that rules out judging by status code alone."""
        url = "https://send.now/zzq9x1aa22bb"
        monkeypatch.setattr(link_probe.httpx, "AsyncClient", _serve(DEAD_PAGES))

        probe = asyncio.run(probe_url(url))

        assert probe.raw_status == 200
        assert probe.kind == KIND_DEAD


class TestLivePages:

    @pytest.mark.parametrize("url", list(ALIVE_PAGES))
    def test_a_file_page_reads_as_alive(self, url, monkeypatch):
        monkeypatch.setattr(link_probe.httpx, "AsyncClient", _serve(ALIVE_PAGES))

        probe = asyncio.run(probe_url(url))

        assert probe.kind == KIND_ALIVE

    def test_no_alive_page_trips_a_dead_marker(self):
        """The markers must not fire on the pages they will most often see."""
        for url, (_, body) in ALIVE_PAGES.items():
            host = url.split("/")[2]
            assert find_dead_marker(host, body) is None, url


class TestUndecidable:

    def test_gofile_is_not_guessed_at(self, monkeypatch):
        """Its HTML carries no file information at all. Calling this alive would
        be a coin flip, and calling it dead would delete a working link from the
        queue."""
        url = "https://gofile.io/d/zzq9x1"
        monkeypatch.setattr(link_probe.httpx, "AsyncClient", _serve({url: GOFILE_SHELL}))

        probe = asyncio.run(probe_url(url))

        assert probe.kind == KIND_UNKNOWN
        assert probe.definitive is False

    def test_a_javascript_shell_is_not_mistaken_for_a_file_page(self):
        assert looks_like_a_file_page(GOFILE_SHELL[1]) is False


class TestTransientIsNeverPinned:

    @pytest.mark.parametrize("status", [500, 502, 503])
    def test_a_host_outage_stays_retryable(self, status, monkeypatch):
        url = "https://datanodes.to/abc"
        monkeypatch.setattr(link_probe.httpx, "AsyncClient",
                            _serve({url: (status, "<html>bad gateway</html>")}))

        probe = asyncio.run(probe_url(url))

        assert probe.kind == KIND_TRANSIENT
        assert probe.definitive is False

    def test_a_page_we_cannot_read_stays_undecided(self, monkeypatch):
        """No dead marker and nothing that looks like a file page — say so
        rather than picking a side."""
        url = "https://datanodes.to/abc"
        monkeypatch.setattr(link_probe.httpx, "AsyncClient",
                            _serve({url: (200, "<html><body>maintenance</body></html>")}))

        probe = asyncio.run(probe_url(url))

        assert probe.kind == KIND_UNKNOWN
        assert probe.definitive is False
