# -*- coding: utf-8 -*-
"""
OC Proxy Downloader - Windows Standalone Executable
"""
import sys
import os
import webbrowser
import threading
import time
import signal
import traceback
from pathlib import Path

# PyInstaller 환경에서 경로 설정
if hasattr(sys, '_MEIPASS'):
    # PyInstaller로 빌드된 exe 실행 시
    base_path = Path(sys._MEIPASS)
    backend_path = base_path / "backend"
else:
    # 개발 환경에서 직접 실행 시
    base_path = Path(__file__).parent.parent
    backend_path = base_path / "backend"

# Python 경로에 backend 추가
sys.path.insert(0, str(backend_path))

# 환경 변수 설정
os.environ["PYTHONPATH"] = str(backend_path)

def open_browser():
    """3초 후 브라우저 열기"""
    time.sleep(3)
    webbrowser.open("http://localhost:8000")

def signal_handler(sig, frame):
    """종료 시그널 처리"""
    print("\n[INFO] 애플리케이션을 종료합니다...")
    sys.exit(0)

def main():
    print("🚀 OC Proxy Downloader를 시작합니다...")
    print("📂 Frontend 파일을 확인합니다...")

    try:
        # Frontend 파일 확인
        if hasattr(sys, '_MEIPASS'):
            frontend_dist = Path(sys._MEIPASS) / "frontend" / "dist"
        else:
            frontend_dist = base_path / "frontend" / "dist"

        if not frontend_dist.exists():
            print(f"❌ Frontend 빌드 파일을 찾을 수 없습니다: {frontend_dist}")
            print("   먼저 'npm run build'를 실행해주세요.")
            input("Press Enter to exit...")
            return

        print("✅ Frontend 파일 확인 완료!")
        print("🌐 웹 서버를 시작합니다...")

        # 브라우저 자동 열기 (별도 스레드)
        browser_thread = threading.Thread(target=open_browser)
        browser_thread.daemon = True
        browser_thread.start()

        # 시그널 핸들러 등록
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        print("✅ 서버가 시작되었습니다!")
        print("🌐 브라우저에서 http://localhost:8000 을 여는 중...")
        print("⚠️  이 창을 닫으면 애플리케이션이 종료됩니다.")
        print("📋 종료하려면 Ctrl+C를 누르세요.")

        # Backend 메인 모듈 임포트 및 실행
        from main import main as backend_main
        backend_main()

    except KeyboardInterrupt:
        print("\n[INFO] 사용자에 의해 종료되었습니다.")
    except Exception as e:
        print(f"❌ 오류가 발생했습니다: {e}")
        print(f"📋 상세 오류:\n{traceback.format_exc()}")
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()