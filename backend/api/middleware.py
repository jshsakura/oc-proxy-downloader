# -*- coding: utf-8 -*-
import time
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

from core.auth import AuthManager


API_PREFIX = "/api/"

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


async def require_api_auth(request: Request, call_next):
    """Reject unauthenticated API calls whenever authentication is configured.

    The login endpoint issued tokens that nothing ever checked: every route was
    reachable without one, so the credentials only gated the UI while the API
    itself — settings, stored secrets, download control — stayed wide open to
    anyone who could reach the port. When AUTH_USERNAME/AUTH_PASSWORD are unset
    authentication is disabled by design and this middleware stands aside.
    """
    if not AuthManager.is_authentication_enabled() or _is_exempt(request.url.path):
        return await call_next(request)

    token = _presented_token(request)
    if not token or AuthManager.verify_token(token) is None:
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


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