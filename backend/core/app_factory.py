# -*- coding: utf-8 -*-
import asyncio
import os
import signal
import sys
import atexit
from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

from core.version import CURRENT_VERSION

from services.sse_manager import sse_manager
from services.download_service import download_service
from api.middleware import log_requests
from api.routes import downloads, settings, events, auth, locales
from api.routes.proxy import router as proxy_router
from api.routes.history import router as history_router
from api.routes.system import router as system_router
from api.routes.audit import router as audit_router
from core.db import engine
from core.models import Base
from core.i18n import load_all_translations
from core.db import get_db
from sqlalchemy import text

# Authentication settings
AUTH_USERNAME = os.getenv('AUTH_USERNAME')
AUTH_PASSWORD = os.getenv('AUTH_PASSWORD')
AUTHENTICATION_ENABLED = bool(AUTH_USERNAME and AUTH_PASSWORD)


SHUTDOWN_TIMEOUT_SEC = 5.0
TASK_CANCEL_TIMEOUT_SEC = 3.0


async def _shutdown_step(label: str, coro_fn, timeout: float = SHUTDOWN_TIMEOUT_SEC):
    """Run one service-shutdown step safely.

    timeout/cancelled are treated as normal flow and other exceptions are only
    logged as WARNING — one step's failure must not block the next shutdown step.
    """
    try:
        await asyncio.wait_for(coro_fn(), timeout=timeout)
        print(f"[LOG] {label} stopped")
    except asyncio.TimeoutError:
        print(f"[WARNING] {label} stop timeout")
    except asyncio.CancelledError:
        print(f"[LOG] {label} stop cancelled - normal during shutdown")
    except Exception as e:
        print(f"[WARNING] {label} stop error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage the application lifecycle"""
    print("[LOG] *** 애플리케이션 시작 ***")

    # Initialize the translation cache
    load_all_translations()

    # Create DB tables
    Base.metadata.create_all(bind=engine)
    print("[LOG] Database tables created")

    # Create requested_at index for period queries (idempotent)
    with engine.connect() as conn:
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_download_requests_requested_at ON download_requests(requested_at)"))
        conn.commit()

    # Run database migrations
    await _run_migrations()

    # Start the services
    await sse_manager.start()
    await download_service.start()
    print("[LOG] Services started")

    yield

    # Cleanup work
    print("[LOG] *** 애플리케이션 종료 시작 ***")

    await _shutdown_step("Download service", download_service.stop)
    await _shutdown_step("SSE manager", sse_manager.stop)

    # Clean up running tasks (exclude the current task to avoid infinite recursion)
    try:
        current_task = asyncio.current_task()
        tasks = [t for t in asyncio.all_tasks()
                 if not t.done() and t != current_task]
        if tasks:
            print(f"[LOG] Cancelling {len(tasks)} remaining tasks...")
            for t in tasks:
                t.cancel()
            await _shutdown_step(
                "Task cancellation",
                lambda: asyncio.gather(*tasks, return_exceptions=True),
                timeout=TASK_CANCEL_TIMEOUT_SEC,
            )
    except Exception as e:
        print(f"[WARNING] Task cleanup error: {e}")

    print("[LOG] *** 애플리케이션 종료 완료 ***")


def create_app() -> FastAPI:
    """Create the FastAPI application"""

    # Create the FastAPI app
    app = FastAPI(
        title="OC Proxy Downloader",
        description="1fichier 다운로드 서비스 (웹소켓 제거, SSE + asyncio)",
        version=CURRENT_VERSION.lstrip("v"),
        lifespan=lifespan
    )

    # Robust ASGI error-handling middleware
    @app.middleware("http")
    async def catch_all_errors(request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except asyncio.CancelledError:
            # A normal cancellation is simply re-raised
            print("[LOG] Request cancelled - normal during shutdown")
            raise
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)

            print(f"[ERROR] ASGI 미들웨어에서 에러 포착: {error_type}")

            # Special handling for anyio.WouldBlock or stream errors
            if "wouldblock" in error_msg.lower() or "stream" in error_msg.lower():
                print("[ERROR] 스트림 에러 - 안전하게 처리됨")
                return JSONResponse(
                    status_code=499,
                    content={"error": "Stream error handled"}
                )

            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error", "type": error_type}
            )

    # Add middleware
    app.middleware("http")(log_requests)

    # Set up the API router
    api_router = APIRouter()

    # Register the routers
    api_router.include_router(auth.router)
    api_router.include_router(downloads.router)
    api_router.include_router(history_router)
    api_router.include_router(settings.router)
    api_router.include_router(proxy_router)
    api_router.include_router(events.router)
    api_router.include_router(locales.router)
    api_router.include_router(system_router)
    api_router.include_router(audit_router)

    app.include_router(api_router)

    # Add a global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Global exception handler - prevents the server from stopping"""
        error_msg = str(exc)
        error_type = type(exc).__name__

        # CancelledError is part of normal shutdown, so it is not treated as an error
        if isinstance(exc, asyncio.CancelledError):
            print(f"[LOG] Task cancelled (normal during shutdown): {request.url}")
            return JSONResponse(
                status_code=499,  # Client Closed Request
                content={"message": "Request cancelled"}
            )

        print(f"[ERROR] 전역 예외 핸들러 활성화: {error_type}")
        print(f"[ERROR] 오류 세부: {error_msg}")
        print(f"[ERROR] 요청 URL: {request.url}")

        # Detailed logging for decompression errors
        if "decompressing" in error_msg.lower():
            print(f"[ERROR] 압축 해제 오류 감지 - 서버 안정성 유지")
        elif "stream" in error_msg.lower() and "closed" in error_msg.lower():
            print(f"[ERROR] 스트림 연결 오류 감지 - 서버 안정성 유지")
        elif "wouldblock" in error_msg.lower():
            print(f"[ERROR] SSE 스트림 블록 오류 - 정상적인 shutdown 과정")

        print(f"[LOG] 예외를 처리하여 서버 계속 실행 중...")

        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": "서버에서 오류가 발생했지만 서버는 정상 작동 중입니다",
                "type": error_type,
                "details": error_msg if len(error_msg) < 200 else f"{error_msg[:200]}..."
            }
        )
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Request validation error handler"""
        print(f"[ERROR] 요청 검증 오류: {exc}")
        print(f"[ERROR] 요청 URL: {request.url}")
        return JSONResponse(
            status_code=422,
            content={"error": "Validation Error", "details": exc.errors()}
        )

    # Static file serving (auto-detects PyInstaller, Docker, and local environments)
    # Configure the frontend static file path (EXE/Docker integration)
    if getattr(sys, 'frozen', False):
        # PyInstaller-bundled environment (EXE) - use the static folder
        bundle_dir = sys._MEIPASS
        frontend_path = os.path.join(bundle_dir, "static")
        print(f"[LOG] PyInstaller detected, serving from: {frontend_path}")
    elif os.environ.get("CONFIG_PATH"):
        # Docker environment - use the static folder
        frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
        print(f"[LOG] Docker environment, serving from: {frontend_path}")
    else:
        # Local development environment - use the dist folder (for integration testing)
        frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist")
        print(f"[LOG] Local development, serving from: {frontend_path}")

    # Check that the path exists
    if not frontend_path or not os.path.exists(frontend_path):
        print(f"[WARNING] Frontend path not found: {frontend_path}")
        frontend_path = None

    if frontend_path and os.path.exists(frontend_path):
        # Check that the Vite build assets directory is named 'assets'
        assets_dir = os.path.join(frontend_path, "assets")
        if os.path.exists(assets_dir):
            app.mount(
                "/assets", StaticFiles(directory=assets_dir), name="assets")
        else:
            print(f"[WARNING] 'assets' directory not found in {frontend_path}")

        @app.get("/{full_path:path}")
        async def serve_frontend(full_path: str):
            """Serve frontend files"""
            # Exclude API requests
            if full_path.startswith("api/"):
                return JSONResponse(
                    status_code=404,
                    content={"error": "This is an API route, not a frontend asset."}
                )

            # The requested file path
            requested_file_path = os.path.join(frontend_path, full_path)

            # If the path has no file name, or the root is requested, return index.html
            if not os.path.basename(full_path) or not "." in os.path.basename(full_path):
                return FileResponse(os.path.join(frontend_path, "index.html"))

            # If the file exists, return that file
            if os.path.exists(requested_file_path) and os.path.isfile(requested_file_path):
                return FileResponse(requested_file_path)

            # If the file is missing, return index.html for SPA routing
            else:
                return FileResponse(os.path.join(frontend_path, "index.html"))
    else:
        # When the frontend was not found in either path
        warning_message = f"[WARNING] Frontend not found. Looked in {docker_path} (for Docker) and {local_dev_path} (for Local Dev)."
        print(warning_message)

        @app.get("/")
        async def root():
            return {"message": "OC Proxy Downloader API", "version": CURRENT_VERSION.lstrip("v")}

    print(f"[LOG] FastAPI app created - Auth: {AUTHENTICATION_ENABLED}")
    return app


async def _run_migrations():
    """Run database migrations.

    SQLite can only add columns via ALTER TABLE (no drop/type change). Every added
    column must be nullable or have a default value. The call is idempotent —
    already-existing columns are filtered out via PRAGMA table_info and SKIPped.
    """
    # (column_name, the DDL fragment appended after ALTER TABLE)
    required_columns = [
        ("started_at", "DATETIME"),
        # Failure classification / retry policy (added 2026-05)
        ("failure_kind", "VARCHAR"),
        ("attempt_count", "INTEGER DEFAULT 0"),
        ("next_retry_at", "DATETIME"),
        ("last_probed_at", "DATETIME"),
        ("attempts_json", "TEXT"),
    ]

    try:
        db = next(get_db())
        try:
            result = db.execute(text("PRAGMA table_info(download_requests)"))
            existing = {row[1] for row in result.fetchall()}

            for col_name, ddl in required_columns:
                if col_name in existing:
                    continue
                print(f"[LOG] Adding {col_name} column to download_requests")
                db.execute(text(
                    f"ALTER TABLE download_requests ADD COLUMN {col_name} {ddl}"
                ))
                db.commit()
                print(f"[LOG] Migration completed: {col_name} column added")

            # Index for the frequently used filter (failure + next retry time) — idempotent
            db.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_download_requests_failure_kind "
                "ON download_requests(failure_kind)"
            ))
            db.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_download_requests_next_retry_at "
                "ON download_requests(next_retry_at)"
            ))
            db.commit()
        except Exception as e:
            print(f"[ERROR] Migration failed: {e}")
            db.rollback()
        finally:
            db.close()

    except Exception as e:
        print(f"[ERROR] Migration setup failed: {e}")
