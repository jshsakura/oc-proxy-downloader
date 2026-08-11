# -*- coding: utf-8 -*-
"""Every shipped module must import.

The Windows build collects ``backend/**/*.py`` wholesale into the EXE, so a
module that cannot be imported travels with the release and waits. One already
had: ``core/notifications.py`` imported a name that does not exist anywhere in
``core.download_core``, and read four columns the model has never had
(``download_speed``, ``eta``, ``created_at``, ``completed_at``). Nothing
imported it, so nothing noticed — it was deleted rather than repaired.

Import is the cheapest check there is, and it catches the class of breakage
that only shows up when a rarely-taken path finally runs.
"""

import importlib
import pathlib

import pytest


BACKEND = pathlib.Path(__file__).resolve().parent.parent
# main.py starts a server on import; the packaged entry point is exercised by
# the build itself, not here.
SKIP_DIRS = {"tests", "__pycache__", "config"}


def _shipped_modules():
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if rel.name == "main.py":
            continue
        yield ".".join(rel.with_suffix("").parts)


MODULES = list(_shipped_modules())


def test_the_backend_has_modules_to_check():
    """A glob that quietly matches nothing would make every test below pass."""
    assert len(MODULES) > 30


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(module)
