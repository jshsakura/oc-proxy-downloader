# -*- coding: utf-8 -*-
import asyncio
import signal
import atexit
from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

from services.sse_manager import sse_manager
from services.download_service import download_service
from api.middleware import log_requests
from api.routes import downloads, settings, events, auth, locales
from api.routes.proxy import router as proxy_router
from api.routes.history import router as history_router
from core.db import engine
from core.models import Base
from core.i18n import load_all_translations
from core.db import get_db
from sqlalchemy import text

# 인증 설정
import os
AUTH_USERNAME = os.getenv('AUTH_USERNAME')
AUTH_PASSWORD = os.getenv('AUTH_PASSWORD')
AUTHENTICATION_ENABLED = bool(AUTH_USERNAME and AUTH_PASSWORD)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 수명주기 관리"""
    print("[LOG] *** 애플리케이션 시작 ***")

    # 번역 캐시 초기화
    load_all_translations()

    # DB 테이블 생성
    Base.metadata.create_all(bind=engine)
    print("[LOG] Database tables created")

    # 데이터베이스 마이그레이션 실행
    await _run_migrations()

    # 서비스들 시작
    await sse_manager.start()
    await download_service.start()
    print("[LOG] Services started")

    yield

    # 정리 작업
    print("[LOG] *** 애플리케이션 종료 시작 ***")

    try:
        # 서비스들 정지 (타임아웃 설정)
        await asyncio.wait_for(download_service.stop(), timeout=5.0)
        print("[LOG] Download service stopped")
    except asyncio.TimeoutError:
        print("[WARNING] Download service stop timeout")
    except asyncio.CancelledError:
        print("[LOG] Download service stop cancelled - normal during shutdown")
    except Exception as e:
        print(f"[WARNING] Download service stop error: {e}")

    try:
        await asyncio.wait_for(sse_manager.stop(), timeout=5.0)
        print("[LOG] SSE manager stopped")
    except asyncio.TimeoutError:
        print("[WARNING] SSE manager stop timeout")
    except asyncio.CancelledError:
        print("[LOG] SSE manager stop cancelled - normal during shutdown")
    except Exception as e:
        print(f"[WARNING] SSE manager stop error: {e}")

    # 실행 중인 태스크들 정리 (현재 태스크 제외하여 무한 재귀 방지)
    try:
        current_task = asyncio.current_task()
        tasks = [task for task in asyncio.all_tasks() 
                if not task.done() and task != current_task]
        if tasks:
            print(f"[LOG] Cancelling {len(tasks)} remaining tasks...")
            # 각 태스크를 개별적으로 취소하고 예외 처리
            for task in tasks:
                try:
                    task.cancel()
                except Exception as e:
                    print(f"[WARNING] Failed to cancel task {task}: {e}")
            
            # 타임아웃을 설정하여 무한 대기 방지
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=3.0
                )
                print("[LOG] Tasks cancelled")
            except asyncio.TimeoutError:
                print("[WARNING] Task cancellation timeout")
            except asyncio.CancelledError:
                print("[LOG] Task cancellation interrupted - this is normal during shutdown")
            except Exception as e:
                print(f"[WARNING] Unexpected error during task cancellation: {e}")
    except Exception as e:
        print(f"[WARNING] Task cleanup error: {e}")

    print("[LOG] *** 애플리케이션 종료 완료 ***")


def create_app() -> FastAPI:
    """FastAPI 애플리케이션 생성"""

    # FastAPI 앱 생성
    app = FastAPI(
        title="OC Proxy Downloader",
        description="1fichier 다운로드 서비스 (웹소켓 제거, SSE + asyncio)",
        version="2.0.0",
        lifespan=lifespan
    )

    # 강력한 ASGI 에러 처리 미들웨어
    @app.middleware("http")
    async def catch_all_errors(request: Request, call_next):
        try:
            response = await call_next(request)
            return response
        except asyncio.CancelledError:
            # 정상적인 취소는 그냥 재발생시킴
            print("[LOG] Request cancelled - normal during shutdown")
            raise
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)

            print(f"[ERROR] ASGI 미들웨어에서 에러 포착: {error_type}")

            # anyio.WouldBlock이나 스트림 에러는 특별 처리
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

    # 미들웨어 추가
    app.middleware("http")(log_requests)

    # API 라우터 설정
    api_router = APIRouter()

    # 라우터들 등록
    api_router.include_router(auth.router)
    api_router.include_router(downloads.router)
    api_router.include_router(history_router)
    api_router.include_router(settings.router)
    api_router.include_router(proxy_router)
    api_router.include_router(events.router)
    api_router.include_router(locales.router)

    app.include_router(api_router)
    
    # 전역 예외 핸들러 추가
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """전역 예외 핸들러 - 서버 정지 방지"""
        error_msg = str(exc)
        error_type = type(exc).__name__

        # CancelledError는 정상적인 shutdown 과정이므로 에러로 처리하지 않음
        if isinstance(exc, asyncio.CancelledError):
            print(f"[LOG] Task cancelled (normal during shutdown): {request.url}")
            return JSONResponse(
                status_code=499,  # Client Closed Request
                content={"message": "Request cancelled"}
            )

        print(f"[ERROR] 전역 예외 핸들러 활성화: {error_type}")
        print(f"[ERROR] 오류 세부: {error_msg}")
        print(f"[ERROR] 요청 URL: {request.url}")

        # 압축 해제 오류 세부 로깅
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
        """요청 검증 오류 핸들러"""
        print(f"[ERROR] 요청 검증 오류: {exc}")
        print(f"[ERROR] 요청 URL: {request.url}")
        return JSONResponse(
            status_code=422,
            content={"error": "Validation Error", "details": exc.errors()}
        )

    # 정적 파일 서빙 (Docker 및 로컬 환경 자동 감지)
    docker_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    local_dev_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist")

    frontend_path = None
    if os.path.exists(docker_path):
        frontend_path = docker_path
        print(f"[LOG] Serving frontend from Docker path: {frontend_path}")
    elif os.path.exists(local_dev_path):
        frontend_path = local_dev_path
        print(f"[LOG] Serving frontend from Local Dev path: {frontend_path}")

    if frontend_path and os.path.exists(frontend_path):
        # Vite 빌드 에셋 디렉토리 이름이 'assets'인지 확인
        assets_dir = os.path.join(frontend_path, "assets")
        if os.path.exists(assets_dir):
            app.mount(
                "/assets", StaticFiles(directory=assets_dir), name="assets")
        else:
            print(f"[WARNING] 'assets' directory not found in {frontend_path}")

        @app.get("/{full_path:path}")
        async def serve_frontend(full_path: str):
            """프론트엔드 파일 서빙"""
            # API 요청은 제외
            if full_path.startswith("api/"):
                return JSONResponse(
                    status_code=404,
                    content={"error": "This is an API route, not a frontend asset."}
                )

            # 요청된 파일 경로
            requested_file_path = os.path.join(frontend_path, full_path)

            # 경로에 파일 이름이 없거나, 루트를 요청하면 index.html 반환
            if not os.path.basename(full_path) or not "." in os.path.basename(full_path):
                return FileResponse(os.path.join(frontend_path, "index.html"))
            
            # 파일이 존재하면 해당 파일 반환
            if os.path.exists(requested_file_path) and os.path.isfile(requested_file_path):
                return FileResponse(requested_file_path)
            
            # 파일이 없으면 SPA 라우팅을 위해 index.html 반환
            else:
                return FileResponse(os.path.join(frontend_path, "index.html"))
    else:
        # 두 경로 모두에서 프론트엔드를 찾지 못한 경우
        warning_message = f"[WARNING] Frontend not found. Looked in {docker_path} (for Docker) and {local_dev_path} (for Local Dev)."
        print(warning_message)

        @app.get("/")
        async def root():
            return {"message": "OC Proxy Downloader API", "version": "2.0.0"}

    print(f"[LOG] FastAPI app created - Auth: {AUTHENTICATION_ENABLED}")
    return app


async def _run_migrations():
    """데이터베이스 마이그레이션 실행"""
    try:
        db = next(get_db())

        # started_at 컬럼이 없는 경우 추가
        try:
            # 컬럼 존재 여부 확인
            result = db.execute(text("PRAGMA table_info(download_requests)"))
            columns = [row[1] for row in result.fetchall()]

            if 'started_at' not in columns:
                print("[LOG] Adding started_at column to download_requests table")
                db.execute(text("ALTER TABLE download_requests ADD COLUMN started_at DATETIME"))
                db.commit()
                print("[LOG] Migration completed: started_at column added")
            else:
                print("[LOG] started_at column already exists")

        except Exception as e:
            print(f"[ERROR] Migration failed: {e}")
            db.rollback()
        finally:
            db.close()

    except Exception as e:
        print(f"[ERROR] Migration setup failed: {e}")
