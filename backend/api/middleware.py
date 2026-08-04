# -*- coding: utf-8 -*-
import hmac
import os
import time
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

from core.auth import AuthManager
from core.config import get_or_create_api_token


API_PREFIX = "/api/"

# A long-lived token for server-to-server callers (oc-scraper's "전송"), separate
# from the human login: set API_TOKEN and the same value goes in the caller's
# X-API-Key header. Rotating it never touches the login, and a leaked token can be
# revoked on its own. Empty/unset → integration token auth is simply off.
API_TOKEN_ENV = "API_TOKEN"
API_KEY_HEADER = "X-API-Key"

# Reachable before a token exists: the login call itself, the probe the UI uses to
# find out whether a login is even required, and the UI strings shown on that
# screen. Everything else under /api/ needs a valid token once auth is turned on.
AUTH_EXEMPT_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/status",
})
AUTH_EXEMPT_PREFIXES = ("/api/locales",)

# EventSource cannot send an Authorization header, so the SSE stream accepts the
# token as a query parameter instead. Restricted to that one route: query strings
# leak into logs and referrers far more easily than headers do.
QUERY_TOKEN_PATHS = frozenset({"/api/events"})


def _is_exempt(path: str) -> bool:
    return (
        not path.startswith(API_PREFIX)
        or path in AUTH_EXEMPT_PATHS
        or path.startswith(AUTH_EXEMPT_PREFIXES)
    )


def _presented_token(request: Request) -> str:
    header = request.headers.get("Authorization") or ""
    if header.startswith("Bearer "):
        return header[len("Bearer "):].strip()
    if request.url.path in QUERY_TOKEN_PATHS:
        return (request.query_params.get("token") or "").strip()
    return ""


def _valid_api_token(request: Request) -> bool:
    """Accept the API token in the X-API-Key header (server-to-server).

    The token is generated and stored in the app config (get_or_create_api_token),
    shown and rotated from the Settings UI — not an env var. An env API_TOKEN is
    still honoured as an override for deployments that prefer to inject it.
    Compared in constant time so a wrong token can't be recovered by timing.
    """
    presented = (request.headers.get(API_KEY_HEADER) or "").strip()
    if not presented:
        return False
    env_token = (os.environ.get(API_TOKEN_ENV) or "").strip()
    if env_token and hmac.compare_digest(presented, env_token):
        return True
    stored = (get_or_create_api_token() or "").strip()
    return bool(stored) and hmac.compare_digest(presented, stored)


async def require_api_auth(request: Request, call_next):
    """Reject unauthenticated API calls whenever authentication is configured.

    The login endpoint issued tokens that nothing ever checked: every route was
    reachable without one, so the credentials only gated the UI while the API
    itself — settings, stored secrets, download control — stayed wide open to
    anyone who could reach the port. When AUTH_USERNAME/AUTH_PASSWORD are unset
    authentication is disabled by design and this middleware stands aside.

    Two credential forms are accepted: the browser's Bearer JWT, and a static
    X-API-Key token for server-to-server callers (see ``_valid_api_token``).
    """
    if not AuthManager.is_authentication_enabled() or _is_exempt(request.url.path):
        return await call_next(request)

    token = _presented_token(request)
    if (token and AuthManager.verify_token(token) is not None) or _valid_api_token(request):
        return await call_next(request)

    return JSONResponse(
        status_code=401,
        content={"detail": "Authentication required"},
        headers={"WWW-Authenticate": "Bearer"},
    )


async def log_requests(request: Request, call_next):
    """Request logging middleware"""
    start_time = time.time()

    # Request log
    print(f"[LOG] {request.method} {request.url}")

    try:
        response = await call_next(request)

        # Calculate response time
        process_time = time.time() - start_time

        # Response log (slow requests only)
        if process_time > 1.0:
            print(f"[LOG] {request.method} {request.url} - {response.status_code} ({process_time:.2f}s)")
            
        response.headers["X-Process-Time"] = str(process_time)
        return response
        
    except Exception as e:
        process_time = time.time() - start_time
        print(f"[ERROR] {request.method} {request.url} - Error: {e} ({process_time:.2f}s)")
        
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )