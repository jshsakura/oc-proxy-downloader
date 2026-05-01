# -*- coding: utf-8 -*-
"""
OC Proxy Downloader - 새 아키텍처
- 웹소켓 완전 제거
- SSE + asyncio 기반
- 모듈화된 구조
"""
import sys
import os

# 스탠드얼론 환경 설정 (최우선 - 모든 임포트보다 먼저!)
if getattr(sys, 'frozen', False):
    from pathlib import Path
    # 실행 파일과 같은 디렉토리에 config 폴더 생성
    exe_dir = Path(sys.executable).parent
    config_dir = exe_dir / "config"
    config_dir.mkdir(exist_ok=True)
    os.environ['OC_CONFIG_DIR'] = str(config_dir)
    print(f"Loading OC Proxy Downloader...")
    print(f"[LOG] Standalone config directory: {config_dir}")

# Python 경로 설정 (Docker 환경 대응)
# 이 코드는 다른 모듈보다 먼저 실행되어야 합니다.
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import signal
import traceback
import threading
import time
import uvicorn
import atexit
import httpx
import json
import webbrowser
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from utils.logging import setup_logging, replace_print
from core.app_factory import create_app

# .env 파일 로드
if getattr(sys, 'frozen', False):
    # 스탠드얼론: exe 디렉토리에서 찾기
    env_path = Path(sys.executable).parent / ".env"
else:
    # 개발환경: 루트 디렉토리에서 찾기
    project_root = Path(__file__).parent.parent
    env_path = project_root / ".env"

if env_path.exists():
    load_dotenv(env_path)
    print(f"[LOG] Loaded .env from: {env_path}")
else:
    print("[INFO] No .env file found")

# 로깅 설정 (.env 로딩 후에)
setup_logging()
replace_print()

# 스탠드얼론 환경에서 로딩 표시
def show_loading():
    """Display loading animation"""
    if not getattr(sys, 'frozen', False):
        return  # Skip in development environment

    import threading
    import time

    loading_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    stop_loading = threading.Event()

    def loading_animation():
        i = 0
        while not stop_loading.is_set():
            char = loading_chars[i % len(loading_chars)]
            print(f"\r{char} Starting OC Proxy Downloader...", end="", flush=True)
            time.sleep(0.1)
            i += 1

    thread = threading.Thread(target=loading_animation, daemon=True)
    thread.start()
    return stop_loading

# 로딩 시작
loading_stop = show_loading()

# 메인 애플리케이션 생성 (.env 로딩 후에)
app = create_app()

# 로딩 완료
if loading_stop:
    loading_stop.set()
    print("\r✅ OC Proxy Downloader Ready!          ")  # Clear previous text with spaces


def monitor_process_health():
    """기본 프로세스 상태 체크 - 단순화"""
    try:
        # 기본적인 상태만 체크
        return True
    except Exception as e:
        print(f"[LOG] Process monitoring error (ignored): {e}")
        return True


def force_cleanup_threads():
    """모든 스레드 강제 정리 - reentrant call 방지"""
    try:
        print("[LOG] Starting thread cleanup...")

        # 짧은 대기로 정상 종료 기회 제공
        time.sleep(0.2)

        # 현재 스레드 확인
        active_threads = threading.enumerate()

        # 정리할 스레드 타입들
        cleanup_threads = []
        for t in active_threads:
            if (('AnyIO worker thread' in t.name) or
                ('Download' in t.name) or
                ('ThreadPoolExecutor' in str(type(t))) or
                ('_thread' in str(type(t)).lower())) and not t.daemon:
                cleanup_threads.append(t)

        if cleanup_threads:
            print(f"[LOG] Found {len(cleanup_threads)} threads to cleanup")

            # 강제 종료 시도 (daemon으로 변경)
            for thread in cleanup_threads:
                try:
                    thread.daemon = True
                    print(f"[LOG] Set daemon=True for {thread.name}")
                except:
                    pass

        print("[LOG] Thread cleanup completed")
    except:
        # 예외 발생 시 조용히 무시 (reentrant call 방지)
        pass


def main():
    """메인 서버 시작 함수"""
    print("=" * 60)
    print("🚀 OC Proxy Downloader v2.0")
    print("   - SSE + asyncio ✅")
    print("=" * 60)

    # 종료 시 스레드 정리 등록 (다중 등록 방지)
    atexit.register(force_cleanup_threads)

    # 강제 종료 핸들러 설정
    def signal_handler(sig, frame):
        print(f"\n[LOG] 종료 신호 수신 ({sig}) - 즉시 강제 종료...")
        try:
            # 빠른 정리
            sys.exit(0)
        except:
            os._exit(0)  # 강제 종료

    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # 종료 요청

    # Windows에서 Ctrl+Break도 처리
    if hasattr(signal, 'SIGBREAK'):
        signal.signal(signal.SIGBREAK, signal_handler)

    try:
        # 개발 서버 실행 - 빠른 종료 설정
        # 환경별 포트 설정
        port = int(os.environ.get('OC_PORT', '8888' if getattr(sys, 'frozen', False) else '8000'))

        config = uvicorn.Config(
            app,  # PyInstaller 환경에서는 직접 app 객체 전달
            host="0.0.0.0",
            port=port,
            reload=False,
            log_level="critical",
            loop="asyncio",
            workers=1,
            access_log=False,
            lifespan="on",  # 빠른 시작/종료
            timeout_keep_alive=5,  # 연결 타임아웃 단축
            timeout_graceful_shutdown=3,  # 종료 타임아웃 단축
        )
        server = uvicorn.Server(config)

        # Additional loading message for standalone only
        if getattr(sys, 'frozen', False):
            print("🌐 Starting web server...")
        else:
            print("[LOG] Starting server - default configuration")

        # 브라우저 자동 열기 (도커가 아닌 환경에서만)
        if not os.getenv('DOCKER_CONTAINER'):
            def open_browser():
                """Open browser after server starts"""
                time.sleep(2)  # Wait for server start
                try:
                    url = f"http://localhost:{port}"
                    print(f"[LOG] Opening browser: {url}")
                    webbrowser.open(url)
                except Exception as e:
                    print(f"[WARNING] Failed to open browser: {e}")
                    print(f"[INFO] Please manually access http://localhost:{port} in your browser")

            # 브라우저 열기를 별도 스레드에서 실행
            browser_thread = threading.Thread(target=open_browser, daemon=True)
            browser_thread.start()
        else:
            print("[INFO] Docker/Standalone environment - Browser auto-open disabled")

        server.run()
    except KeyboardInterrupt:
        print("[LOG] KeyboardInterrupt - Normal shutdown")
    except Exception as fatal_error:
        print(f"[FATAL] Fatal error occurred: {fatal_error}")
        print(f"[FATAL] Please restart the server")
        traceback.print_exc()
    finally:
        force_cleanup_threads()


if __name__ == "__main__":
    main()
