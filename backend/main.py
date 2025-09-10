# -*- coding: utf-8 -*-
"""
OC Proxy Downloader - 새 아키텍처
- 웹소켓 완전 제거
- SSE + asyncio 기반
- 모듈화된 구조
"""
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# .env 파일 로드 (루트 디렉토리에서 찾기)
project_root = Path(__file__).parent.parent
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"[LOG] Loaded .env from: {env_path}")
else:
    # 백엔드 디렉토리에서도 찾아보기
    backend_env = Path(__file__).parent / ".env"
    if backend_env.exists():
        load_dotenv(backend_env)
        print(f"[LOG] Loaded .env from: {backend_env}")
    else:
        print("[WARNING] No .env file found")

# Python 경로 설정 (Docker 환경 대응)
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# 로깅 설정 (.env 로딩 후에)
from utils.logging import setup_logging, replace_print
setup_logging()
replace_print()

# 메인 애플리케이션 생성 (.env 로딩 후에)
from core.app_factory import create_app
app = create_app()


def force_cleanup_threads():
    """AnyIO worker thread 강제 정리"""
    import threading
    import time

    print("[LOG] Starting thread cleanup...")

    # 1초 대기로 정상 종료 기회 제공
    time.sleep(1)

    # 현재 스레드 확인
    active_threads = threading.enumerate()
    anyio_threads = [
        t for t in active_threads if 'AnyIO worker thread' in t.name and not t.daemon]

    if anyio_threads:
        print(
            f"[LOG] Found {len(anyio_threads)} AnyIO worker threads to cleanup")

        # 강제 종료 시도 (daemon으로 변경)
        for thread in anyio_threads:
            try:
                thread.daemon = True
                print(f"[LOG] Set daemon=True for {thread.name}")
            except:
                pass

    print("[LOG] Thread cleanup completed")


if __name__ == "__main__":
    import uvicorn
    import atexit
    import signal

    print("=" * 60)
    print("🚀 OC Proxy Downloader v2.0")
    print("   - SSE + asyncio ✅")
    print("=" * 60)

    # 종료 시 스레드 정리 등록
    atexit.register(force_cleanup_threads)

    # 시그널 핸들러
    def signal_handler(signum, frame):
        print(f"[LOG] Received signal {signum}, starting cleanup...")
        force_cleanup_threads()
        # exit(0) 대신 KeyboardInterrupt 발생시켜 uvicorn이 graceful shutdown 하도록 함
        import os
        os._exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # 개발 서버 실행
        config = uvicorn.Config(
            "main:app",
            host="0.0.0.0",
            port=8000,
            reload=False,  # reload=False로 변경 (AnyIO 스레드 문제 방지)
            log_level="info",
            loop="asyncio",  # asyncio 루프 명시
            workers=1,  # 단일 워커 (스레드 문제 방지)
        )
        server = uvicorn.Server(config)
        server.run()
    except KeyboardInterrupt:
        print("[LOG] KeyboardInterrupt received")
    finally:
        force_cleanup_threads()
