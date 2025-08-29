# -*- coding: utf-8 -*-
"""
OC Proxy Downloader - Standalone EXE 버전
모든 것을 하나의 EXE 파일에 포함하여 배포
"""

import sys
import os
import threading
import time
import webbrowser
from pathlib import Path

# UTF-8 인코딩 설정
if sys.platform.startswith('win'):
    try:
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

# PyInstaller 실행 환경 감지
if getattr(sys, 'frozen', False):
    # PyInstaller로 패키징된 경우
    BASE_DIR = Path(sys._MEIPASS)
    EXE_DIR = Path(sys.executable).parent
    STATIC_DIR = BASE_DIR / "frontend" / "build"
    
    # Windows 기본 다운로드 폴더 사용
    import os
    user_home = Path.home()
    DOWNLOADS_DIR = user_home / "Downloads"
    CONFIG_DIR = EXE_DIR / "config"
else:
    # 개발 환경
    BASE_DIR = Path(__file__).parent.parent
    STATIC_DIR = BASE_DIR / "frontend" / "build"
    DOWNLOADS_DIR = BASE_DIR / "downloads"
    CONFIG_DIR = BASE_DIR / "backend" / "config"

# 필요한 폴더 생성
DOWNLOADS_DIR.mkdir(exist_ok=True)
CONFIG_DIR.mkdir(exist_ok=True)

# 환경 변수 설정
os.environ['DOWNLOAD_PATH'] = str(DOWNLOADS_DIR)
os.environ['CONFIG_PATH'] = str(CONFIG_DIR)
os.environ['LOG_LEVEL'] = 'WARNING'

print(f"[LOG] 실행 환경: {'EXE' if getattr(sys, 'frozen', False) else '개발'}")
print(f"[LOG] 다운로드 폴더: {DOWNLOADS_DIR}")
print(f"[LOG] 설정 폴더: {CONFIG_DIR}")

# 기존 backend 모듈들을 sys.path에 추가
backend_path = BASE_DIR / "backend" if not getattr(sys, 'frozen', False) else BASE_DIR
sys.path.insert(0, str(backend_path))

# 이제 기존 backend 코드를 import
try:
    # FastAPI 및 관련 모듈들
    import uvicorn
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Form, UploadFile, File
    from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.middleware.cors import CORSMiddleware
    
    # DB 관련
    from sqlalchemy.orm import Session
    from sqlalchemy import desc, asc
    
    # 기타
    import json
    import queue
    import asyncio
    from typing import List, Optional
    import datetime
    
    print("[LOG] 모듈 import 완료")
    
except ImportError as e:
    print(f"[ERROR] 모듈 import 실패: {e}")
    print("[ERROR] 필요한 패키지가 설치되지 않았습니다.")
    input("Press Enter to exit...")
    sys.exit(1)

# DB 및 모델 초기화
from core.db import engine, get_db
from core.models import Base, DownloadRequest, StatusEnum, UserProxy
from core.shared import status_queue, download_manager

print("[LOG] DB 모델 로딩 완료")

# DB 테이블 생성
Base.metadata.create_all(bind=engine)
print("[LOG] 데이터베이스 초기화 완료")

# FastAPI 앱 생성
app = FastAPI(
    title="OC Proxy Downloader - Standalone",
    description="1fichier 파일 다운로드를 위한 독립 실행 애플리케이션",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket 연결 관리
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[LOG] WebSocket 연결됨. 총 연결 수: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"[LOG] WebSocket 연결 해제됨. 총 연결 수: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        if self.active_connections:
            disconnected = []
            for connection in self.active_connections:
                try:
                    await connection.send_text(message)
                except:
                    disconnected.append(connection)
            
            for connection in disconnected:
                self.disconnect(connection)

manager = ConnectionManager()

# WebSocket 메시지 브로드캐스트 스레드
def websocket_broadcaster():
    async def broadcast_loop():
        while True:
            try:
                message = status_queue.get(timeout=1)
                await manager.broadcast(message)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[ERROR] WebSocket 브로드캐스트 오류: {e}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(broadcast_loop())

# 백그라운드 스레드 시작
broadcast_thread = threading.Thread(target=websocket_broadcaster, daemon=True)
broadcast_thread.start()

# 정적 파일 서빙
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    
    @app.get("/")
    async def read_root():
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        else:
            return {"message": "OC Proxy Downloader Standalone", "static_dir": str(STATIC_DIR)}
else:
    @app.get("/")
    async def read_root():
        return {"message": "OC Proxy Downloader Standalone - Frontend not found", "looking_for": str(STATIC_DIR)}

# 기본 API 엔드포인트들
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/api/settings")
async def get_settings():
    return {
        "app_name": "OC Proxy Downloader - Standalone",
        "version": "1.0.0",
        "status": "running",
        "downloads_dir": str(DOWNLOADS_DIR),
        "config_dir": str(CONFIG_DIR)
    }

# 기존 backend/main.py의 모든 API 엔드포인트들 포함
try:
    # main.py에서 API 라우터들을 가져오기
    from main import *
    print("[LOG] Backend API 라우터 로딩 완료")
except ImportError as e:
    print(f"[WARNING] Backend API import 실패, 기본 API만 사용: {e}")
    
    # 기본 API들만 정의
    @app.post("/api/download")
    async def add_download(data: dict):
        return {"message": "API not fully loaded", "data": data}
        
    @app.get("/api/downloads")
    async def get_downloads():
        return {"downloads": [], "message": "API not fully loaded"}

def open_browser():
    """5초 후 브라우저 열기"""
    time.sleep(5)
    try:
        webbrowser.open('http://localhost:8759')
        print("[LOG] 브라우저가 열렸습니다: http://localhost:8759")
    except Exception as e:
        print(f"[ERROR] 브라우저 열기 실패: {e}")
        print("[LOG] 수동으로 브라우저에서 http://localhost:8759 을 열어주세요.")

def main():
    """메인 함수"""
    print("🚀 OC Proxy Downloader Standalone 시작")
    print("=" * 50)
    
    # 브라우저 자동 열기
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    try:
        # Uvicorn 서버 실행 (EXE 전용 포트 8759)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=8759,
            log_level="warning",
            access_log=False
        )
    except KeyboardInterrupt:
        print("\n[LOG] 사용자에 의해 종료됨")
    except Exception as e:
        print(f"[ERROR] 서버 실행 오류: {e}")
        input("Press Enter to exit...")
    finally:
        download_manager.terminate_all_downloads()

if __name__ == "__main__":
    main()