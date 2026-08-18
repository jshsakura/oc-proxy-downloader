# -*- coding: utf-8 -*-
"""The release-site tag comes off the filename.

The badge beside a row already says where a download came from, so the same
answer glued into the name is noise — and unlike the badge it follows the file
onto disk and onto the NAS. Stripping happens on the column, not at each of the
dozen places a name is assigned, which is what these tests pin.
"""

import pytest

from core.site_tags import SITE_TAGS, strip_site_tag
from core.models import DownloadRequest


class TestTagAtTheEnd:

    @pytest.mark.parametrize("name,expected", [
        # The shape that made up a quarter of real history.
        ("DIRCTQUD-(US)-NSwTcH-[BASE]-NSP-ES-Ziperto.rar",
         "DIRCTQUD-(US)-NSwTcH-[BASE]-NSP-ES.rar"),
        ("CFTRANIP-NSwTcH-[BASE]-NSP-(eShop)-Ziperto.rar",
         "CFTRANIP-NSwTcH-[BASE]-NSP-(eShop).rar"),
        ("Game - NxBrew.zip", "Game.zip"),
        ("Game by NxBrew.rar", "Game.rar"),
        ("Game_Rapidgator.7z", "Game.7z"),
        ("Game-MegaUp.nsp", "Game.nsp"),
        # No extension at all — still a name a user reads.
        ("Game-Ziperto", "Game"),
    ])
    def test_the_tag_and_its_separator_both_go(self, name, expected):
        assert strip_site_tag(name) == expected


class TestMultipartArchives:
    """A split archive keeps its part number: renaming ``.part2.rar`` to
    ``.rar`` would collide with part 1 and lose the file."""

    @pytest.mark.parametrize("name,expected", [
        ("WANDRSTP-NSwTcH-[BASE]-NSP-ES-Ziperto.part1.rar",
         "WANDRSTP-NSwTcH-[BASE]-NSP-ES.part1.rar"),
        ("COMBFRCS-(EU)-NSwTcH-[BASE]-NSP-(eShop)-Ziperto.part2.rar",
         "COMBFRCS-(EU)-NSwTcH-[BASE]-NSP-(eShop).part2.rar"),
        ("Game-Ziperto.r01", "Game.r01"),
    ])
    def test_the_part_suffix_survives(self, name, expected):
        assert strip_site_tag(name) == expected


class TestNamesLeftAlone:

    @pytest.mark.parametrize("name", [
        "Volcano Princess [01007CB025C58800][v131072][1.0.2][UPD].rar",
        "Let's! Revolution! [0100C7601CD2E000][v0][Base].rar",
        "exren3rgg1m9",
        "",
    ])
    def test_a_name_with_no_tag_is_untouched(self, name):
        assert strip_site_tag(name) == name

    @pytest.mark.parametrize("name", [
        "Supersonic.rar",          # ends in a tag only as a substring
        "MegaUpload Adventure.rar",
    ])
    def test_a_tag_inside_a_word_is_not_a_tag(self, name):
        assert strip_site_tag(name) == name

    @pytest.mark.parametrize("name", ["Ziperto.rar", "[Ziperto].rar"])
    def test_a_name_that_is_only_a_tag_keeps_it(self, name):
        """Stripping would leave a bare ".rar" — worse to read than the tag."""
        assert strip_site_tag(name) == name

    def test_none_is_passed_through(self):
        assert strip_site_tag(None) is None


class TestTheColumnNormalises:
    """Every assignment path — preparse, hoster page, Content-Disposition,
    resume — goes through the column, so none of them can reintroduce a tag."""

    def test_a_name_set_at_construction_is_clean(self):
        req = DownloadRequest(url="https://datanodes.to/abc",
                              file_name="TOTS-NSwTcH-[BASE]-NSP-(eShop)-Ziperto.rar")
        assert req.file_name == "TOTS-NSwTcH-[BASE]-NSP-(eShop).rar"

    def test_a_later_assignment_is_clean_too(self):
        req = DownloadRequest(url="https://datanodes.to/abc")
        req.file_name = "IZMBI-NSwTcH-[BASE]-NSP-(eShop)-Ziperto.rar"
        assert req.file_name == "IZMBI-NSwTcH-[BASE]-NSP-(eShop).rar"

    def test_an_unset_name_stays_none(self):
        req = DownloadRequest(url="https://datanodes.to/abc")
        assert req.file_name is None


class TestOneListForBothStrippers:

    def test_the_page_title_stripper_reads_the_same_tags(self):
        """A hand-kept second copy drifts the first time a site is added."""
        from core.hoster_common import _TITLE_SITE_SUFFIX_RE

        for tag in SITE_TAGS:
            assert _TITLE_SITE_SUFFIX_RE.sub("", f"Some Game - {tag}") == "Some Game"
