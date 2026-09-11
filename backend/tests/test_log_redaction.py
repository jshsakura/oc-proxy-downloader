# -*- coding: utf-8 -*-
"""Credentials must not outlive the request in docker logs.

EventSource cannot send an Authorization header, so the SSE stream takes its
JWT as ``?token=`` — and ``log_requests`` printed the full request URL. A
leaked log line was a live session token (seen in production 2026-09-11:
``GET /api/events?token=eyJhbGciOi...``).
"""

import pytest

from api.middleware import _masked_url


class TestMaskedUrl:
    def test_sse_jwt_is_masked(self):
        url = "http://oc-proxy.example.com/api/events?token=eyJhbGciOiJIUzI1NiJ9.payload.sig"
        masked = _masked_url(url)
        assert "eyJhbGciOiJIUzI1NiJ9" not in masked
        assert "token=***" in masked

    def test_plain_params_survive(self):
        url = "http://x/api/downloads/working?page=1&page_size=15"
        assert _masked_url(url) == url

    def test_masked_alongside_plain_params(self):
        masked = _masked_url("http://x/api/events?token=abc&stream=1")
        assert masked == "http://x/api/events?token=***&stream=1"

    @pytest.mark.parametrize("name", [
        "token", "Token", "TOKEN", "password", "api_key", "apikey", "secret",
    ])
    def test_credential_shaped_names_all_masked(self, name):
        masked = _masked_url(f"http://x/api/events?{name}=hunter2")
        assert "hunter2" not in masked

    def test_url_without_query_untouched(self):
        assert _masked_url("http://x/api/health") == "http://x/api/health"


class TestNoUnmaskedRequestUrlPrints:
    """Every print of a request URL must go through the mask.

    The first fix covered middleware.py's 3 sites and missed the global
    exception handlers in core/app_factory.py — an SSE cancellation was
    printing the full ``/api/events?token=<JWT>`` there (2026-09-11 review).
    This scans the whole backend so a new unmasked print cannot slip in again.
    """

    def test_every_request_url_print_is_masked(self):
        import pathlib

        backend_root = pathlib.Path(__file__).resolve().parent.parent
        offenders = []
        for path in backend_root.rglob("*.py"):
            rel = str(path.relative_to(backend_root))
            if rel.startswith("tests/") or "__pycache__" in rel:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if "print(" in line and "request.url" in line and "_masked_url" not in line:
                    offenders.append(f"{rel}:{lineno}")
        assert offenders == []
