# -*- coding: utf-8 -*-
"""A storage-plan badge is not a file size.

A datanodes download was recorded as exactly 2.00 TiB with ``file_size='2tb'``.
``_extract_largest_size_from_text`` scanned the raw markup and took the biggest
match, so a plan badge in the page chrome beat the real file every time — the
lowercase, space-less ``2tb`` gives away that it came from an attribute or a
path, not from anything a reader sees. A 2 TiB row then makes every disk-space
judgement wrong and shows an absurd size in the grid.
"""

import pytest

from core.hoster_common import (
    MAX_PLAUSIBLE_FILE_BYTES,
    _extract_largest_size_from_text,
    _extract_size_from_text,
    size_to_bytes,
)


class TestPageFurnitureIsIgnored:

    def test_a_plan_badge_does_not_beat_the_real_file(self):
        html = """
        <html><body>
          <div class="plan"><span>2TB</span> storage for life</div>
          <div class="file">movie.rar <strong>2.19 GB</strong></div>
        </body></html>
        """

        assert _extract_largest_size_from_text(html) == "2.19 GB"

    def test_a_size_inside_a_class_name_is_not_a_size(self):
        html = '<html><body><div class="plan2tb"></div><p>1.50 GB</p></body></html>'

        assert _extract_largest_size_from_text(html) == "1.50 GB"

    def test_a_size_inside_an_image_path_is_not_a_size(self):
        html = '<html><body><img src="/img/6tb.png"><p>800 MB</p></body></html>'

        assert _extract_largest_size_from_text(html) == "800 MB"

    def test_a_size_in_a_script_is_not_a_size(self):
        html = '<html><body><script>var plan="10 TB";</script><p>3.00 GB</p></body></html>'

        assert _extract_largest_size_from_text(html) == "3.00 GB"

    def test_an_implausible_size_is_refused_outright(self):
        """With no real size on the page, reporting nothing beats reporting 6 TiB
        — a zero total leaves the download unsized, a fake one fills the disk."""
        html = "<html><body><div>Upgrade to 6 TB</div></body></html>"

        assert _extract_largest_size_from_text(html) == ""
        assert _extract_size_from_text(html) == ""


class TestRealSizesStillParse:

    @pytest.mark.parametrize("text,expected", [
        ("movie.rar 2.19 GB", "2.19 GB"),
        ("<strong>850 MB</strong>", "850 MB"),
        ("File size: 7.20 GB", "7.20 GB"),
        ("size 512 KB", "512 KB"),
    ])
    def test_ordinary_sizes_are_unchanged(self, text, expected):
        assert _extract_size_from_text(text) == expected

    def test_a_bare_string_needs_no_markup(self):
        """size_to_bytes is called on stored display strings too, not only pages."""
        assert size_to_bytes("2.19 GB") == int(2.19 * 1024 ** 3)

    def test_the_largest_real_size_still_wins(self):
        html = "<html><body><p>part1 700 MB</p><p>part2 4.50 GB</p></body></html>"

        assert _extract_largest_size_from_text(html) == "4.50 GB"

    def test_the_cap_sits_above_anything_these_hosters_serve(self):
        """Switch releases top out around 10-30 GB; the cap must not clip them."""
        assert MAX_PLAUSIBLE_FILE_BYTES > 100 * 1024 ** 3
        assert _extract_largest_size_from_text("<p>64.00 GB</p>") == "64.00 GB"
