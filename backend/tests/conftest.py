# -*- coding: utf-8 -*-
"""Shared pytest configuration.

Adds the backend directory to sys.path so that ``core.*`` / ``services.*``
and friends can be imported.

It also isolates ``CONFIG_DIR`` to a temporary directory during the test run
so that unit tests do not overwrite operational files in the real
``backend/config/`` such as ``parse_debug_*.html``, ``config.json``, and
``downloads.db``. (An incident that actually happened: ``_save_parse_debug``
wrote test-fixture HTML to the operational debug file, leaving the user unable
to trace the cause of a failure.)
"""

import os
import sys
import tempfile

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Set the environment variables before core.config is imported.
# Tests must always be isolated from the real operational config directory, so
# force-override both (CONFIG_PATH / OC_CONFIG_DIR). The config module checks
# OC_CONFIG_DIR first, so setting only that value is enough, but we set both
# explicitly to be safe.
_TEST_CONFIG_DIR = tempfile.mkdtemp(prefix="oc_test_config_")
os.environ["OC_CONFIG_DIR"] = _TEST_CONFIG_DIR
os.environ.pop("CONFIG_PATH", None)
