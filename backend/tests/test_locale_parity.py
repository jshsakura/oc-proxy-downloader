# -*- coding: utf-8 -*-
"""Locale files must stay in parity with the English reference (en.json).

Every locales/*.json must have the exact same key set as en.json and preserve
the same {placeholder} tokens per value, so no translation drops a key or
breaks string interpolation. Also guards that each locale has a display name.
"""

import json
import re
from pathlib import Path

import pytest

from core import i18n

LOCALES_DIR = Path(i18n.LOCALES_DIR)
REFERENCE = "en"
_PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z0-9_]+\}")


def _load(lang):
    with open(LOCALES_DIR / f"{lang}.json", encoding="utf-8") as f:
        return json.load(f)


def _placeholders(text):
    return sorted(_PLACEHOLDER_RE.findall(text)) if isinstance(text, str) else []


REFERENCE_TRANSLATIONS = _load(REFERENCE)
LOCALE_CODES = sorted(
    p.stem for p in LOCALES_DIR.glob("*.json") if p.stem != REFERENCE
)


def test_reference_locale_is_non_empty():
    assert len(REFERENCE_TRANSLATIONS) > 0


@pytest.mark.parametrize("lang", LOCALE_CODES)
def test_locale_has_same_keys_as_reference(lang):
    translations = _load(lang)
    reference_keys = set(REFERENCE_TRANSLATIONS)
    locale_keys = set(translations)
    missing = reference_keys - locale_keys
    extra = locale_keys - reference_keys
    assert not missing, f"{lang}.json missing keys: {sorted(missing)[:10]}"
    assert not extra, f"{lang}.json has extra keys: {sorted(extra)[:10]}"


@pytest.mark.parametrize("lang", LOCALE_CODES)
def test_locale_preserves_placeholders(lang):
    translations = _load(lang)
    mismatched = {
        key: (_placeholders(REFERENCE_TRANSLATIONS[key]), _placeholders(value))
        for key, value in translations.items()
        if key in REFERENCE_TRANSLATIONS
        and _placeholders(REFERENCE_TRANSLATIONS[key]) != _placeholders(value)
    }
    assert not mismatched, f"{lang}.json placeholder mismatch: {dict(list(mismatched.items())[:5])}"


@pytest.mark.parametrize("lang", LOCALE_CODES)
def test_locale_has_display_name(lang):
    assert lang in i18n.LANGUAGE_NAMES, f"add a display name for '{lang}' to LANGUAGE_NAMES"
