# -*- coding: utf-8 -*-
import asyncio
import signal
import atexit
from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from services.sse_manager import sse_manager
from services.download_service import download_service
from api.middleware import log_requests
from api.routes import downloads, settings, events, auth
from api.routes.proxy import router as proxy_router
from core.db import engine
from core.models import Base
from core.i18n import load_all_translations

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

    # 미들웨어 추가
    app.middleware("http")(log_requests)

    # API 라우터 설정
    api_router = APIRouter()

    # 라우터들 등록
    api_router.include_router(auth.router)
    api_router.include_router(downloads.router)
    api_router.include_router(settings.router)
    api_router.include_router(proxy_router)
    api_router.include_router(events.router)

    app.include_router(api_router)

    # 정적 파일 서빙
    frontend_path = os.path.join(os.path.dirname(
        os.path.dirname(os.path.dirname(__file__))), "frontend", "dist")
    if os.path.exists(frontend_path):
        app.mount(
            "/assets", StaticFiles(directory=os.path.join(frontend_path, "assets")), name="assets")

        @app.get("/{full_path:path}")
        async def serve_frontend(full_path: str):
            """프론트엔드 파일 서빙"""
            if full_path.startswith("api/"):
                return {"error": "API endpoint not found"}

            if full_path in ["", "index.html"] or not "." in full_path:
                return FileResponse(os.path.join(frontend_path, "index.html"))
            else:
                file_path = os.path.join(frontend_path, full_path)
                if os.path.exists(file_path):
                    return FileResponse(file_path)
                else:
                    return FileResponse(os.path.join(frontend_path, "index.html"))
    else:
        print(f"[WARNING] Frontend not found at {frontend_path}")

        @app.get("/")
        async def root():
            return {"message": "OC Proxy Downloader API", "version": "2.0.0"}

    print(f"[LOG] FastAPI app created - Auth: {AUTHENTICATION_ENABLED}")
    return app
