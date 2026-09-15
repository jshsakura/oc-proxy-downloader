"""The SPA shell must never pin an obsolete content-hashed bundle."""

from fastapi.testclient import TestClient

from core.app_factory import create_app


def test_index_html_is_never_cached():
    response = TestClient(create_app()).get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["expires"] == "0"


def test_spa_fallback_is_never_cached():
    response = TestClient(create_app()).get("/downloads/history")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"
