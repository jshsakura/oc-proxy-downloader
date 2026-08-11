# -*- coding: utf-8 -*-
"""The host badge shown next to a filename.

Which host a link came from is what tells the user what to expect — a 1fichier
free slot waits, DataNodes needs a captcha, MEGA is quota-bound. The mapping is
derived from HOSTER_REGISTRY on purpose: a hand-kept copy in the frontend would
drift the first time a host is added.
"""

import pytest

from core.hoster_labels import hoster_label
from core.hoster_parsers import HOSTER_REGISTRY


class TestKnownHosts:

    @pytest.mark.parametrize("url,expected", [
        ("https://1fichier.com/?abc", "1fichier"),
        ("https://datanodes.to/xyz", "DataNodes"),
        ("https://www.mediafire.com/file/x", "MediaFire"),
        ("https://megaup.net/abc", "MegaUp"),
        ("https://gofile.io/d/abc", "GoFile"),
        ("https://mega.nz/file/abc", "MEGA"),
        ("https://pixeldrain.com/u/abc", "Pixeldrain"),
    ])
    def test_registry_and_extra_hosts_get_their_display_name(self, url, expected):
        assert hoster_label(url) == expected

    @pytest.mark.parametrize("url,expected", [
        ("https://a-7.1fichier.com/p12345", "1fichier"),
        ("https://cdn.datanodes.to/f/abc", "DataNodes"),
        ("https://www.datanodes.to/abc", "DataNodes"),
    ])
    def test_a_download_node_is_labelled_as_its_family(self, url, expected):
        """A resolved 1fichier link points at a node like a-7.1fichier.com.
        Showing that hostname would answer a question nobody asked."""
        assert hoster_label(url) == expected

    def test_every_registry_host_resolves_to_its_registered_name(self):
        """Adding a host to the registry must light up its badge with no second
        edit — that is the whole reason this lives in the backend."""
        for spec in HOSTER_REGISTRY:
            for host in spec.hostnames:
                assert hoster_label(f"https://{host}/file") == spec.name


class TestUnknownAndEmpty:

    def test_an_unsupported_host_shows_its_hostname(self):
        """More useful than "Unknown": it says exactly where the link points."""
        assert hoster_label("https://multiup.io/download/a/b") == "multiup.io"

    @pytest.mark.parametrize("url", ["", None, "not a url", "/relative/path"])
    def test_nothing_to_label_yields_an_empty_string(self, url):
        assert hoster_label(url) == ""


class TestSlugs:
    """The badge colour keys off a slug, not the label.

    A label is prose — "Send.now" could be reworded tomorrow — while the
    stylesheet needs something stable to hang a colour on. Splitting them keeps
    a copy-edit from silently turning a badge grey.
    """

    @pytest.mark.parametrize("url,slug", [
        ("https://1fichier.com/?abc", "1fichier"),
        ("https://a-7.1fichier.com/p123", "1fichier"),
        ("https://datanodes.to/x", "datanodes"),
        ("https://megaup.net/x", "megaup"),
        ("https://mega.nz/file/x", "mega"),
        ("https://gofile.io/d/x", "gofile"),
        ("https://send.now/x", "sendnow"),
        ("https://pixeldrain.com/u/x", "pixeldrain"),
        ("https://www.mediafire.com/file/x", "mediafire"),
    ])
    def test_known_hosts_get_a_stable_slug(self, url, slug):
        from core.hoster_labels import hoster_slug

        assert hoster_slug(url) == slug

    @pytest.mark.parametrize("domain", ["bunkr.si", "bunkr.ru", "bunkrr.su", "bunkr.media"])
    def test_every_bunkr_domain_shares_one_slug(self, domain):
        """Bunkr rotates domains; one badge colour has to cover all of them."""
        from core.hoster_labels import hoster_slug

        assert hoster_slug(f"https://{domain}/f/x") == "bunkr"

    @pytest.mark.parametrize("url", ["https://example.com/x", "", None, "nonsense"])
    def test_an_unknown_host_has_no_slug(self, url):
        """Empty means "use the default colour" — not a guessed one."""
        from core.hoster_labels import hoster_slug

        assert hoster_slug(url) == ""
