# -*- coding: utf-8 -*-
"""Frontend i18n guards.

1. Every $t('key') used in the frontend must exist in en.json (no missing keys).
2. No hardcoded Korean text may remain in .svelte markup (comments, <style>,
   and console.* debug lines are ignored) — everything user-facing must go
   through $t().
"""

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
EN_JSON = REPO_ROOT / "backend" / "locales" / "en.json"

# Match only complete literal keys: $t('key') or $t('key', {...}).
# A trailing ) or , after the quote excludes dynamic keys like $t('kind_' + x).
_T_KEY_RE = re.compile(r"""\$t\(\s*['"]([a-zA-Z0-9_]+)['"]\s*[),]""")
_HANGUL_RE = re.compile(r"[가-힣]")

EN_KEYS = set(json.loads(EN_JSON.read_text(encoding="utf-8")))
SVELTE_FILES = sorted(FRONTEND_SRC.rglob("*.svelte"))
FRONTEND_FILES = sorted(FRONTEND_SRC.rglob("*.svelte")) + sorted(FRONTEND_SRC.rglob("*.js"))


def _strip_noise(text):
    """Remove comments, <style> blocks, and console.* lines so only live markup/logic remains."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    # Strip console.* debug calls (may span multiple lines).
    text = re.sub(r"console\.\w+\([\s\S]*?\);", "", text)
    # Strip line/inline // comments, but keep :// in URLs intact.
    text = re.sub(r"(?<!:)//[^\n]*", "", text)
    kept = [line for line in text.splitlines() if "console." not in line]
    return "\n".join(kept)


@pytest.mark.parametrize("path", FRONTEND_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_t_keys_exist_in_en_json(path):
    used = set(_T_KEY_RE.findall(path.read_text(encoding="utf-8")))
    missing = sorted(used - EN_KEYS)
    assert not missing, f"{path.name} uses $t keys missing from en.json: {missing}"


@pytest.mark.parametrize("path", SVELTE_FILES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_hardcoded_korean_in_markup(path):
    cleaned = _strip_noise(path.read_text(encoding="utf-8"))
    offenders = [
        line.strip()
        for line in cleaned.splitlines()
        if _HANGUL_RE.search(line)
    ]
    assert not offenders, (
        f"{path.name} has hardcoded Korean (move it to i18n via $t): {offenders[:5]}"
    )
