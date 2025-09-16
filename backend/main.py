# -*- coding: utf-8 -*-
"""
OC Proxy Downloader - 새 아키텍처
- 웹소켓 완전 제거
- SSE + asyncio 기반
- 모듈화된 구조
"""
import sys
import os
import signal
import traceback
from pathlib import Path
from dotenv import load_dotenv
from utils.logging import setup_logging, replace_print
from core.app_factory import create_app

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
setup_logging()
replace_print()

# 메인 애플리케이션 생성 (.env 로딩 후에)
app = create_app()


def monitor_process_health():
    """프로세스 상태 모니터링 - 좀비 프로세스 방지"""
    try:
        import psutil
        import os

        current_pid = os.getpid()
        process = psutil.Process(current_pid)

        # 메모리 사용량 체크
        memory_info = process.memory_info()
        if memory_info.rss > 500 * 1024 * 1024:  # 500MB 초과시
            print(f"[WARNING] High memory usage: {memory_info.rss / 1024 / 1024:.1f}MB")

        # 자식 프로세스 체크
        children = process.children(recursive=True)
        if len(children) > 10:
            print(f"[WARNING] Too many child processes: {len(children)}")

        return True
    except ImportError:
        # psutil이 없어도 동작하도록
        return True
    except Exception as e:
        print(f"[LOG] Process monitoring error (ignored): {e}")
        return True


def force_cleanup_threads():
    """모든 스레드 강제 정리 - reentrant call 방지"""
    try:
        import threading
        import time

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


if __name__ == "__main__":
    import uvicorn
    import atexit
    import signal

    print("=" * 60)
    print("🚀 OC Proxy Downloader v2.0")
    print("   - SSE + asyncio ✅")
    print("=" * 60)

    # 종료 시 스레드 정리 등록 (다중 등록 방지)
    atexit.register(force_cleanup_threads)

    # 강제 종료 핸들러 설정
    def signal_handler(sig, frame):
        print(f"\n[LOG] 종료 신호 수신 ({sig}) - 강제 종료 중...")
        force_cleanup_threads()
        os._exit(0)  # 강제 종료

    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # 종료 요청

    try:
        # 개발 서버 실행 - 기본 설정
        config = uvicorn.Config(
            "main:app",
            host="0.0.0.0",
            port=8000,
            reload=False,
            log_level="critical",
            loop="asyncio",
            workers=1,
            access_log=False,
        )
        server = uvicorn.Server(config)

        print("[LOG] 서버 시작 - 기본 설정")

        server.run()
    except KeyboardInterrupt:
        print("[LOG] KeyboardInterrupt - 정상 종료")
    except Exception as fatal_error:
        print(f"[FATAL] 치명적 오류 발생: {fatal_error}")
        print(f"[FATAL] 서버를 다시 시작해주세요")
        traceback.print_exc()
    finally:
        force_cleanup_threads()
