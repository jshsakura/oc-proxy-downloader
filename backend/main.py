from core.config import get_config, save_config, get_download_path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, BackgroundTasks, HTTPException, Body, APIRouter
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, HttpUrl
from core.models import Base, DownloadRequest, StatusEnum, ProxyStatus
from core.db import engine, get_db
from core.common import get_all_proxies, convert_size
import requests
import os
import datetime
import random
import lxml.html
import time
import asyncio
from core.i18n import get_message
from sqlalchemy import or_, desc, asc
import queue
import cloudscraper
import re
from urllib.parse import urlparse, unquote
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
import threading
from concurrent.futures import ThreadPoolExecutor, Future
import weakref
import multiprocessing
from typing import Optional
from core.downloader import router as downloader_router

# Get the absolute path to the frontend/dist directory
backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(backend_dir)
frontend_dist_path = os.path.join(project_root, "frontend", "dist")

# 다운로드 스레드 관리
class DownloadManager:
    def __init__(self):
        self.active_downloads = {}  # {download_id: Thread}

    def start_download(self, download_id, func, *args, **kwargs):
        self.cancel_download(download_id)
        t = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
        t.start()
        self.active_downloads[download_id] = t

    def cancel_download(self, download_id):
        # 스레드는 강제 종료가 불가하므로, 상태 플래그를 활용하거나,
        # 다운로드 함수 내에서 req.status == paused/failed 등을 체크하여 자연스럽게 종료되도록 해야 함
        # 여기서는 단순히 관리 목록에서만 제거
        self.active_downloads.pop(download_id, None)

    def is_download_active(self, download_id):
        t = self.active_downloads.get(download_id)
        return t and t.is_alive()

    def terminate_all_downloads(self):
        print("[LOG] 모든 다운로드 스레드 관리 목록에서 제거 (스레드는 강제 종료 불가)")
        self.active_downloads.clear()

# 전역 다운로드 매니저 인스턴스
download_manager = DownloadManager()


Base.metadata.create_all(bind=engine)

app = FastAPI()
api_router = APIRouter(prefix="/api")
api_router.include_router(downloader_router)

# WebSocket 연결 관리
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                print(f"[LOG] WebSocket broadcast error: {e}")
                disconnected.append(connection)
        
        # 끊어진 연결 제거
        for connection in disconnected:
            self.active_connections.remove(connection)

manager = ConnectionManager()

status_queue = queue.Queue()

async def status_broadcaster():
    while True:
        msg = await asyncio.to_thread(status_queue.get)
        await manager.broadcast(msg)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(status_broadcaster())

@app.on_event("startup")
async def on_startup():
    # 서버 재시작 시 진행 중이던 다운로드를 모두 paused로 변경
    db = next(get_db())
    affected = db.query(DownloadRequest).filter(
        DownloadRequest.status.in_([StatusEnum.downloading, StatusEnum.proxying])
    ).update({"status": "paused"})
    db.commit()
    print(f"[LOG] 서버 재시작: {affected}개의 진행 중 다운로드를 paused로 변경")

@app.on_event("shutdown")
def shutdown_event():
    print("[LOG] FastAPI 서버 종료: 모든 백그라운드 다운로드 스레드 관리 목록 비움")
    download_manager.terminate_all_downloads()


@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(10)  # keep alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

def notify_status_update(db: Session, download_id: int, lang: str = "ko"):
    import json
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item:
        item_dict = item.as_dict()
        item_dict["status"] = item.status # Send raw status to frontend
        print(f"[LOG] Notifying status update for {download_id}: {item_dict}") # Add this log
        status_queue.put(json.dumps({"type": "status_update", "data": item_dict}))

async def notify_proxy_try(download_id: int, proxy: str):
    import json
    await manager.broadcast(json.dumps({"id": download_id, "proxy": proxy, "type": "proxy_try"}))

class DownloadRequestCreate(BaseModel):
    url: HttpUrl
    password: Optional[str] = None
    use_proxy: Optional[bool] = True

def get_unused_proxies(db: Session):
    """사용하지 않은 프록시 목록을 반환 (성공한 프록시 우선)"""
    # 최근 24시간 내에 사용된 프록시들
    cutoff_time = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
    
    used_proxies = db.query(ProxyStatus).filter(
        ProxyStatus.last_used_at > cutoff_time
    ).all()
    
    used_proxy_addresses = {f"{p.ip}:{p.port}" for p in used_proxies}
    
    # 전체 프록시 목록에서 사용된 것들 제외
    all_proxies = get_all_proxies()
    unused_proxies = [p for p in all_proxies if p not in used_proxy_addresses]
    
    # 과거에 성공했던 프록시들을 우선적으로 배치
    successful_proxies = db.query(ProxyStatus).filter(
        ProxyStatus.last_status == 'success',
        ProxyStatus.last_used_at <= cutoff_time  # 24시간 지난 성공 프록시들
    ).order_by(desc(ProxyStatus.last_used_at)).all()
    
    priority_proxies = [f"{p.ip}:{p.port}" for p in successful_proxies if f"{p.ip}:{p.port}" in unused_proxies]
    other_proxies = [p for p in unused_proxies if p not in priority_proxies]
    
    # 성공했던 프록시를 앞에 배치
    final_proxies = priority_proxies + other_proxies
    
    print(f"[LOG] 전체 프록시: {len(all_proxies)}개, 사용된 프록시: {len(used_proxy_addresses)}개")
    print(f"[LOG] 미사용 프록시: {len(unused_proxies)}개 (우선순위: {len(priority_proxies)}개)")
    
    return final_proxies

def mark_proxy_used(db: Session, proxy_addr: str, success: bool):
    """프록시 사용 기록을 DB에 저장"""
    try:
        ip, port = proxy_addr.split(':')
        port = int(port)
        
        # 기존 레코드 찾기 또는 새로 생성
        proxy_status = db.query(ProxyStatus).filter(
            ProxyStatus.ip == ip,
            ProxyStatus.port == port
        ).first()
        
        if not proxy_status:
            proxy_status = ProxyStatus(ip=ip, port=port)
            db.add(proxy_status)
        
        proxy_status.last_used_at = datetime.datetime.utcnow()
        proxy_status.last_status = 'success' if success else 'fail'
        
        if not success:
            proxy_status.last_failed_at = datetime.datetime.utcnow()
        
        db.commit()
        print(f"[LOG] 프록시 {proxy_addr} 사용 기록 저장: {'성공' if success else '실패'}")
        
    except Exception as e:
        print(f"[LOG] 프록시 사용 기록 저장 실패: {e}")
        db.rollback()

def reset_proxy_usage(db: Session):
    """모든 프록시 사용 기록 초기화 (모든 프록시를 다 써버렸을 때)"""
    try:
        db.query(ProxyStatus).delete()
        db.commit()
        print(f"[LOG] 모든 프록시 사용 기록 초기화 완료")
    except Exception as e:
        print(f"[LOG] 프록시 사용 기록 초기화 실패: {e}")
        db.rollback()

def test_proxy(proxy_addr, timeout=5):
    """프록시가 작동하는지 빠르게 테스트"""
    try:
        proxy_config = {"http": proxy_addr, "https": proxy_addr}
        # 간단한 HTTP 요청으로 프록시 테스트
        response = requests.get("http://httpbin.org/ip", proxies=proxy_config, timeout=timeout)
        return response.status_code == 200
    except:
        return False

def parse_direct_link(url, password=None, proxies=None, req_id=None):
    """1fichier에서 직접 다운로드 링크를 파싱하는 함수 (개선된 버전)"""
    from core.parser import fichier_parser
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'Referer': str(url),
    }
    
    payload = {'dl_no_ssl': 'on', 'dlinline': 'on'}
    if password:
        payload['pass'] = password
    
    # 먼저 로컬 연결로 시도 (가장 빠르고 안정적)
    print(f"[LOG] 로컬 연결로 1fichier 파싱 시도...")
    scraper = cloudscraper.create_scraper()
    try:
        r = scraper.post(url, data=payload, headers=headers, timeout=10, verify=False)
        print(f"[LOG] 로컬 연결 응답코드: {r.status_code}")
        
        if r.status_code == 200:
            print(f"[LOG] 로컬 HTML 응답 길이: {len(r.text)} 문자")
            direct_link = fichier_parser.parse_download_link(r.text, str(url))
            if direct_link:
                print(f"[LOG] ✅ 로컬 연결로 다운로드 링크 발견: {direct_link}")
                
                # 파일 정보도 추출
                file_info = fichier_parser.extract_file_info(r.text)
                if file_info.get('name'):
                    print(f"[LOG] 파일명: {file_info['name']}")
                if file_info.get('size'):
                    print(f"[LOG] 파일 크기: {file_info['size']}")
                
                return direct_link
            else:
                print(f"[LOG] ❌ 로컬 연결에서 다운로드 링크를 찾을 수 없음")
        else:
            print(f"[LOG] ❌ 로컬 연결 HTTP 오류: {r.status_code}")
        
    except Exception as e:
        print(f"[LOG] ❌ 로컬 연결 예외 발생: {e}")
    
    # 로컬 연결 실패 시에만 프록시 시도
    print(f"[LOG] 로컬 연결 실패. 프록시로 시도...")
    
    # DB 세션 생성 (프록시 추적용)
    db_session = next(get_db())
    
    try:
        # 사용하지 않은 프록시 목록 가져오기
        unused_proxies = get_unused_proxies(db_session)
        
        if not unused_proxies:
            print(f"[LOG] 사용 가능한 프록시가 없음. 프록시 사용 기록 초기화...")
            reset_proxy_usage(db_session)
            unused_proxies = get_all_proxies()
        
        # 프록시 개수 제한 (최대 5개만 시도)
        max_proxies = 5
        tested_proxies = 0
        
        for proxy_addr in unused_proxies:
            if tested_proxies >= max_proxies:
                print(f"[LOG] 최대 프록시 시도 횟수({max_proxies})에 도달. 중단.")
                break
                
            if req_id:  # 요청 ID가 있으면 상태 확인
                db_check = next(get_db())
                try:
                    current_req = db_check.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
                    if current_req and current_req.status == "paused":
                        print(f"[LOG] 다운로드 {req_id} 일시정지됨. 프록시 파싱 중단.")
                        return None
                finally:
                    db_check.close()

            # 프록시 빠른 테스트
            print(f"[LOG] 프록시 {proxy_addr} 연결 테스트...")
            if not test_proxy(proxy_addr, timeout=3):
                print(f"[LOG] ❌ 프록시 {proxy_addr} 연결 실패. 건너뜀.")
                mark_proxy_used(db_session, proxy_addr, False)  # 실패 기록
                continue
            
            tested_proxies += 1
            proxy_config = {"http": proxy_addr, "https": proxy_addr}
            success = False
            
            try:
                print(f"[LOG] 프록시 {proxy_addr}로 1fichier 파싱 시도...")
                r = scraper.post(url, data=payload, headers=headers, proxies=proxy_config, timeout=8, verify=False)
                print(f"[LOG] 프록시 {proxy_addr} 응답코드: {r.status_code}")
                
                if r.status_code == 200:
                    print(f"[LOG] HTML 응답 길이: {len(r.text)} 문자")
                    
                    # 새로운 파서 사용
                    direct_link = fichier_parser.parse_download_link(r.text, str(url))
                    if direct_link:
                        print(f"[LOG] ✅ 프록시 {proxy_addr}로 다운로드 링크 발견: {direct_link}")
                        
                        # 파일 정보도 추출
                        file_info = fichier_parser.extract_file_info(r.text)
                        if file_info.get('name'):
                            print(f"[LOG] 파일명: {file_info['name']}")
                        if file_info.get('size'):
                            print(f"[LOG] 파일 크기: {file_info['size']}")
                        
                        success = True
                        mark_proxy_used(db_session, proxy_addr, True)  # 성공 기록
                        return direct_link
                    else:
                        print(f"[LOG] ❌ 프록시 {proxy_addr}에서 다운로드 링크를 찾을 수 없음")
                else:
                    print(f"[LOG] ❌ 프록시 {proxy_addr} HTTP 오류: {r.status_code}")
                    
            except Exception as e:
                print(f"[LOG] ❌ 프록시 {proxy_addr} 예외 발생: {e}")
            
            # 성공하지 못한 경우 실패 기록
            if not success:
                mark_proxy_used(db_session, proxy_addr, False)
    
    finally:
        db_session.close()
    
    print(f"[LOG] ❌ 모든 방법으로 다운로드 링크 파싱 실패")
    return None

def get_or_parse_direct_link(req, proxies=None, use_proxy=True):
    """다운로드 요청에서 직접 링크를 가져오거나 파싱하는 함수 (개선된 버전)"""
    if req.direct_link:
        print(f"[LOG] 기존 direct_link 사용: {req.direct_link}")
        return req.direct_link
    
    # 새로운 파서 사용
    return parse_direct_link(req.url, req.password, proxies=proxies, req_id=req.id)

def exit_if_parent_dead():
    """부모 프로세스가 종료되면 자식 프로세스도 종료하는 함수"""
    parent_pid = os.getppid()
    while True:
        if os.getppid() != parent_pid:
            print("[LOG] 부모 프로세스가 종료됨. 자식 프로세스도 종료.")
            os._exit(0)
        time.sleep(1)

def download_1fichier_file(request_id: int, lang: str = "ko", use_proxy: bool = True):
    # 부모 감시 스레드 시작 (자식 프로세스에서만 동작)
    if os.getppid() != os.getpid():
        threading.Thread(target=exit_if_parent_dead, daemon=True).start()
    print(f"[LOG] Entering download_1fichier_file for request_id: {request_id}")
    
    # 시작 시간 기록
    start_time = time.time()
    max_duration = 300  # 5분
    
    db = next(get_db()) # Get a new session for this background task
    req = None # Initialize req to None
    try:
        req = db.query(DownloadRequest).filter(DownloadRequest.id == request_id).first()
        if req is None:
            print(f"[LOG] DownloadRequest not found: {request_id}")
            return

        download_path = get_download_path()
        print(f"[LOG] Download path: {download_path}")

        # Check if file already exists to resume download
        file_path = download_path / (req.file_name if req is not None and req.file_name is not None else f"download_{request_id}")
        initial_downloaded_size = 0
        if file_path.exists():
            initial_downloaded_size = file_path.stat().st_size
            print(f"[LOG] Resuming download for {req.id} from {initial_downloaded_size} bytes. File: {file_path}")
        else:
            print(f"[LOG] Starting new download for {req.id}. File: {file_path}")
        
        # Removed: req.status = "proxying" # Set status to proxying before parsing direct link
        # The status should be set by the calling endpoint (e.g., create_download_task, resume_download)
        db.commit()
        print(f"[LOG] Before notify (proxying): req.total_size={req.total_size}, req.downloaded_size={req.downloaded_size}")
        notify_status_update(db, int(getattr(req, 'id')), lang)
        print(f"[LOG] DB status updated to proxying for {req.id}")
        print(f"[LOG] Before get_or_parse_direct_link: req.total_size={req.total_size}, req.downloaded_size={req.downloaded_size}")
        
        # 타임아웃 체크
        if time.time() - start_time > max_duration:
            raise TimeoutError("Download function timed out after 5 minutes")
            
        direct_link = get_or_parse_direct_link(req, use_proxy=use_proxy)
        print(f"[LOG] After get_or_parse_direct_link: direct_link={direct_link}, req.total_size={req.total_size}, req.downloaded_size={req.downloaded_size}")
        print(f"[LOG] Direct link for {req.id}: {direct_link}")

        if not direct_link:
            raise Exception("1fichier에서 다운로드 링크를 찾을 수 없습니다. 사이트 구조가 변경되었거나 프록시 문제일 수 있습니다.")
        
        # 다운로드 링크를 데이터베이스에 저장
        req.direct_link = direct_link
        db.commit()

        setattr(req, "status", StatusEnum.downloading) # Set status to downloading after direct link is found
        db.commit()
        notify_status_update(db, int(getattr(req, 'id')), lang)
        print(f"[LOG] DB status updated to downloading for {req.id}")

        headers = {}
        if initial_downloaded_size > 0:
            headers["Range"] = f"bytes={initial_downloaded_size}-"
            print(f"[LOG] Request headers with Range: {headers}")

        # 다운로드는 로컬로 진행 (프록시 정보가 없으므로)
        download_proxies = None
        print(f"[LOG] 다운로드는 로컬로 진행")
        
        # Use requests to download the file
        with requests.get(str(direct_link), stream=True, allow_redirects=True, headers=headers, proxies=download_proxies) as r:
            print(f"[LOG] HTTP GET request sent for {req.id}. Status code: {r.status_code}")
            print(f"[LOG] Response headers: {r.headers}")
            print(f"[LOG] Content-Length header: {r.headers.get("Content-Length")}")
            print(f"[LOG] Content-Range header: {r.headers.get("Content-Range")}")
            r.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            file_name = None
            if "Content-Disposition" in r.headers:
                # Try to extract filename from Content-Disposition header
                cd = r.headers["Content-Disposition"]
                file_name = re.findall(r"filename\*=UTF-8''(.+?)", cd)
                if not file_name:
                    file_name = re.findall(r"filename=\"(.*?)\"", cd)
                if file_name:
                    file_name = unquote(file_name[0])
            
            if not file_name:
                # Fallback to filename from URL
                file_name = os.path.basename(urlparse(str(direct_link)).path)
                if not file_name:
                    file_name = f"download_{request_id}" # Generic name if all else fails
            print(f"[LOG] Determined file name: {file_name}")

            # If resuming, and file_name was not set, set it now
            if req.file_name is None:
                setattr(req, "file_name", file_name)
                db.commit()

            # Get total size from Content-Length or Content-Range header
            total_size = 0
            if "Content-Length" in r.headers:
                total_size = int(r.headers["Content-Length"])
            elif "Content-Range" in r.headers:
                # Parse Content-Range: bytes 200-1000/1001
                content_range = r.headers["Content-Range"]
                match = re.search(r"bytes \d+-\d+/(\d+)", content_range)
                if match:
                    total_size = int(match.group(1))
            
            if initial_downloaded_size > 0 and total_size > 0:
                total_size = total_size + initial_downloaded_size

            downloaded_size = initial_downloaded_size

            setattr(req, "total_size", total_size)
            db.commit()
            notify_status_update(db, int(getattr(req, 'id')), lang) # Call notify_status_update here
            print(f"[LOG] DB file_name and total_size updated for {req.id}")

            # Open file in append mode if resuming, else write mode
            mode = "ab" if initial_downloaded_size > 0 else "wb"
            print(f"[LOG] Opening file in mode: {mode}")
            with open(str(file_path), mode) as f:
                chunk_count = 0
                last_status_check = time.time()
                status_check_interval = 2.0  # 2초마다 상태 체크
                
                for chunk in r.iter_content(chunk_size=8192):
                    chunk_count += 1
                    current_time = time.time()
                    
                    # 타임아웃 체크
                    if current_time - start_time > max_duration:
                        raise TimeoutError("Download function timed out after 5 minutes")
                    
                    # 효율적인 상태 체크: 2초마다 또는 1MB마다
                    should_check_status = (
                        current_time - last_status_check >= status_check_interval or
                        chunk_count % 128 == 0  # 1MB (8192 * 128 = 1MB)
                    )
                    
                    if should_check_status:
                        db.refresh(req) # Refresh the req object from the database
                        print(f"[LOG] Download {req.id} status refreshed: {req.status}")
                        last_status_check = current_time

                    current_status = getattr(req, 'status')
                    if current_status == StatusEnum.paused: # Check for pause status
                        print(f"[LOG] Download {req.id} paused. Exiting chunk loop.")
                        return # Exit the function, download will resume later
                    
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    setattr(req, "downloaded_size", downloaded_size)
                    db.commit()
                    # Update status every 1MB or 10% of total size, whichever is smaller
                    if total_size > 0 and (downloaded_size % (1024 * 1024) == 0 or downloaded_size * 10 // total_size != (downloaded_size - len(chunk)) * 10 // total_size):
                        notify_status_update(db, int(getattr(req, 'id')), lang)
                print(f"[LOG] Finished writing all chunks for {req.id}")

        setattr(req, "status", StatusEnum.done)
        setattr(req, "downloaded_size", total_size) # Ensure downloaded_size is total_size on completion
        db.commit()
        notify_status_update(db, int(getattr(req, 'id')), lang)
        print(f"[LOG] 다운로드 완료 처리: {req.url}")

    except requests.exceptions.RequestException as e:
        error_message = f"Network or HTTP error: {e}"
        print(f"[LOG] Download {request_id} failed due to RequestException: {error_message}")
        if req: # Ensure req is defined before accessing its attributes
            setattr(req, "status", StatusEnum.failed)
            setattr(req, "error", error_message)
            db.commit()
            notify_status_update(db, int(getattr(req, 'id')), lang)
        else:
            print(f"[LOG] Critical: req was None when RequestException occurred for download_id {request_id}")
    except TimeoutError as e:
        error_message = f"Download timed out: {str(e)}"
        print(f"[LOG] Download {request_id} failed due to TimeoutError: {error_message}")
        if req: # Ensure req is defined before accessing its attributes
            setattr(req, "status", StatusEnum.failed)
            setattr(req, "error", error_message)
            db.commit()
            notify_status_update(db, int(getattr(req, 'id')), lang)
        else:
            print(f"[LOG] Critical: req was None when TimeoutError occurred for download_id {request_id}")
    except Exception as e:
        error_message = str(e)
        print(f"[LOG] Download {request_id} failed due to general Exception: {error_message}")
        if req: # Ensure req is defined before accessing its attributes
            setattr(req, "status", StatusEnum.failed)
            setattr(req, "error", error_message)
            db.commit()
            notify_status_update(db, int(getattr(req, 'id')), lang)
        else:
            print(f"[LOG] Critical: req was None when general Exception occurred for download_id {request_id}")
    finally:
        db.close() # Ensure the session is closed
        # 다운로드 완료 후 매니저에서 제거
        # download_manager.cleanup_completed() # This line is no longer needed as multiprocessing handles cleanup


status_map = {
    "pending": "download_pending",
    "downloading": "download_downloading",
    "paused": "download_paused",
    "proxying": "download_proxying",
    "done": "download_done",
    "failed": "download_failed"
}

def get_lang(request: Request):
    return request.headers.get("accept-language", "ko")[:2]

# Request = Depends()가 붙은 모든 엔드포인트를 main.py에서 완전히 삭제
# websocket, SPA 라우팅, app 설정 등만 남김

@api_router.get("/proxies/")
def get_proxies(req: Request):
    return get_all_proxies()

@api_router.post("/proxies/")
def add_proxy(req: Request, proxy: str = Body(..., embed=True)):
    with open("proxies.txt", "a") as f:
        f.write(proxy + "\n")
    return {"message": "Proxy added successfully"}

@api_router.delete("/proxies/")
def delete_proxy(req: Request, proxy: str = Body(..., embed=True)):
    proxies = get_all_proxies()
    if proxy in proxies:
        proxies.remove(proxy)
        with open("proxies.txt", "w") as f:
            for p in proxies:
                f.write(p + "\n")
        return {"message": "Proxy deleted successfully"}
    else:
        raise HTTPException(status_code=404, detail="Proxy not found")

@api_router.get("/settings")
def get_settings_endpoint(req: Request):
    config = get_config()
    # Use the already resolved and ensured path from get_download_path()
    config['download_path'] = str(get_download_path())
    return config

@api_router.post("/select_folder")
async def select_folder(req: Request):
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    folder_selected = filedialog.askdirectory()
    root.destroy()
    return {"path": folder_selected}

@api_router.post("/settings")
def update_settings_endpoint(settings: dict, req: Request):
    try:
        print(f"[LOG] Received settings to save: {settings}")
        if 'download_path' in settings and settings['download_path'] is not None:
            # Resolve to absolute path before saving
            settings['download_path'] = str(Path(settings['download_path']).resolve())
            # Create the directory if it doesn't exist
            Path(settings['download_path']).mkdir(parents=True, exist_ok=True)
        save_config(settings)
        return {"message": "Settings updated successfully"}
    except Exception as e:
        print(f"[ERROR] Failed to save settings: {e}")
        raise HTTPException(status_code=500, detail="Failed to save settings")

@api_router.get("/locales/{lang}.json")
async def serve_locale_file(lang: str, req: Request):
    locale_file_path = os.path.join(backend_dir, "locales", f"{lang}.json")
    if os.path.exists(locale_file_path):
        return FileResponse(locale_file_path, media_type="application/json")
    raise HTTPException(status_code=404, detail="Locale file not found")

@api_router.get("/downloads/active")
def get_active_downloads(req: Request):
    """활성 다운로드 목록 반환"""
    active_downloads = list(download_manager.active_downloads.keys())
    return {"active_downloads": active_downloads, "count": len(active_downloads)}

@api_router.post("/downloads/cancel/{download_id}")
def cancel_download(download_id: int, req: Request, db: Session = Depends(get_db)):
    """다운로드 강제 취소"""
    lang = get_lang(req)
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail=get_message("download_not_found", lang))
    
    # 스레드 취소
    if download_manager.is_download_active(download_id):
        download_manager.cancel_download(download_id)
        print(f"[LOG] Download {download_id} forcefully cancelled")
    
    # 상태를 failed로 변경
    setattr(item, "status", StatusEnum.failed)
    setattr(item, "error", "Download cancelled by user")
    db.commit()
    notify_status_update(db, int(getattr(item, 'id')), lang)
    
    return {"id": item.id, "status": item.status, "message": "Download cancelled"}

@api_router.get("/proxy-status")
def get_proxy_status(req: Request, db: Session = Depends(get_db)):
    """프록시 사용 현황 조회"""
    try:
        # 최근 24시간 내 사용된 프록시들
        cutoff_time = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        
        used_proxies = db.query(ProxyStatus).filter(
            ProxyStatus.last_used_at > cutoff_time
        ).order_by(desc(ProxyStatus.last_used_at)).all()
        
        # 전체 프록시 개수
        all_proxies = get_all_proxies()
        total_proxies = len(all_proxies)
        used_count = len(used_proxies)
        available_count = total_proxies - used_count
        
        # 성공/실패 통계
        success_count = len([p for p in used_proxies if p.last_status == 'success'])
        fail_count = len([p for p in used_proxies if p.last_status == 'fail'])
        
        proxy_list = []
        for proxy in used_proxies:
            proxy_list.append({
                "address": f"{proxy.ip}:{proxy.port}",
                "last_used": proxy.last_used_at.isoformat() if proxy.last_used_at else None,
                "status": proxy.last_status,
                "last_failed": proxy.last_failed_at.isoformat() if proxy.last_failed_at else None
            })
        
        return {
            "total_proxies": total_proxies,
            "used_proxies": used_count,
            "available_proxies": available_count,
            "success_count": success_count,
            "fail_count": fail_count,
            "used_proxy_list": proxy_list
        }
        
    except Exception as e:
        print(f"[ERROR] 프록시 상태 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="프록시 상태 조회 실패")

@api_router.post("/proxy-status/reset")
def reset_proxy_status(req: Request, db: Session = Depends(get_db)):
    """프록시 사용 기록 초기화"""
    try:
        reset_proxy_usage(db)
        return {"message": "프록시 사용 기록이 초기화되었습니다"}
    except Exception as e:
        print(f"[ERROR] 프록시 기록 초기화 실패: {e}")
        raise HTTPException(status_code=500, detail="프록시 기록 초기화 실패")

@api_router.post("/debug/parse")
def debug_parse_link(data: dict = Body(...)):
    """1fichier 링크 파싱 디버깅 엔드포인트 (상세 로그 포함)"""
    from core.parser import fichier_parser
    
    url = data.get("url")
    password = data.get("password")
    use_proxy = data.get("use_proxy", True)
    
    if not url:
        raise HTTPException(status_code=400, detail="URL이 필요합니다")
    
    debug_info = {
        "url": url,
        "steps": [],
        "success": False,
        "direct_link": None,
        "error": None
    }
    
    try:
        print(f"[DEBUG] 파싱 테스트 시작: {url}")
        debug_info["steps"].append(f"파싱 테스트 시작: {url}")
        
        # 1단계: 기본 HTTP 요청 테스트
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        try:
            import requests
            simple_response = requests.get(url, headers=headers, timeout=10)
            debug_info["steps"].append(f"기본 GET 요청: {simple_response.status_code}")
            print(f"[DEBUG] 기본 GET 요청 응답: {simple_response.status_code}")
        except Exception as e:
            debug_info["steps"].append(f"기본 GET 요청 실패: {str(e)}")
            print(f"[DEBUG] 기본 GET 요청 실패: {e}")
        
        # 2단계: cloudscraper로 POST 요청
        payload = {'dl_no_ssl': 'on', 'dlinline': 'on'}
        if password:
            payload['pass'] = password
        
        scraper = cloudscraper.create_scraper()
        
        try:
            r = scraper.post(url, data=payload, headers=headers, timeout=15, verify=False)
            debug_info["steps"].append(f"cloudscraper POST 요청: {r.status_code}")
            print(f"[DEBUG] cloudscraper POST 응답: {r.status_code}")
            
            if r.status_code == 200:
                html_length = len(r.text)
                debug_info["steps"].append(f"HTML 응답 길이: {html_length} 문자")
                print(f"[DEBUG] HTML 응답 길이: {html_length}")
                
                # HTML 내용 일부 로그
                html_preview = r.text[:1000].replace('\n', ' ').replace('\r', '')
                debug_info["steps"].append(f"HTML 미리보기: {html_preview}")
                print(f"[DEBUG] HTML 미리보기: {html_preview}")
                
                # 3단계: 파서로 링크 추출 시도
                direct_link = fichier_parser.parse_download_link(r.text, str(url))
                
                if direct_link:
                    debug_info["success"] = True
                    debug_info["direct_link"] = direct_link
                    debug_info["steps"].append(f"✅ 다운로드 링크 발견: {direct_link}")
                    print(f"[DEBUG] ✅ 다운로드 링크 발견: {direct_link}")
                    
                    # 파일 정보 추출
                    file_info = fichier_parser.extract_file_info(r.text)
                    debug_info["file_info"] = file_info
                    debug_info["steps"].append(f"파일 정보: {file_info}")
                else:
                    debug_info["steps"].append("❌ 파서에서 다운로드 링크를 찾지 못함")
                    print(f"[DEBUG] ❌ 파서에서 다운로드 링크를 찾지 못함")
                    
                    # HTML에서 모든 링크 추출해서 디버깅
                    import lxml.html
                    doc = lxml.html.fromstring(r.text)
                    all_links = [a.get('href') for a in doc.xpath('//a[@href]') if a.get('href')]
                    debug_info["all_links"] = all_links[:20]  # 처음 20개만
                    debug_info["steps"].append(f"페이지의 모든 링크 (처음 20개): {all_links[:20]}")
            else:
                debug_info["steps"].append(f"❌ HTTP 오류: {r.status_code}")
                debug_info["error"] = f"HTTP {r.status_code}"
                
        except Exception as e:
            debug_info["steps"].append(f"❌ cloudscraper 요청 실패: {str(e)}")
            debug_info["error"] = str(e)
            print(f"[DEBUG] cloudscraper 요청 실패: {e}")
        
        return debug_info
        
    except Exception as e:
        print(f"[DEBUG] 전체 파싱 테스트 오류: {e}")
        debug_info["error"] = str(e)
        debug_info["steps"].append(f"❌ 전체 테스트 실패: {str(e)}")
        return debug_info

@api_router.post("/debug/simple-test")
def simple_connection_test():
    """간단한 연결 테스트"""
    test_results = {}
    
    # 1. 기본 HTTP 연결 테스트
    try:
        import requests
        response = requests.get("https://1fichier.com", timeout=10)
        test_results["basic_http"] = {
            "status": "success",
            "status_code": response.status_code,
            "response_length": len(response.text)
        }
    except Exception as e:
        test_results["basic_http"] = {
            "status": "failed",
            "error": str(e)
        }
    
    # 2. cloudscraper 테스트
    try:
        scraper = cloudscraper.create_scraper()
        response = scraper.get("https://1fichier.com", timeout=10)
        test_results["cloudscraper"] = {
            "status": "success", 
            "status_code": response.status_code,
            "response_length": len(response.text)
        }
    except Exception as e:
        test_results["cloudscraper"] = {
            "status": "failed",
            "error": str(e)
        }
    
    # 3. 프록시 개수 확인
    try:
        proxy_count = len(get_all_proxies())
        test_results["proxy_count"] = proxy_count
    except Exception as e:
        test_results["proxy_error"] = str(e)
    
    return test_results

app.include_router(api_router)

# Serve static files from the dist directory
app.mount("/", StaticFiles(directory=frontend_dist_path), name="static")

# Catch-all route for SPA routing
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    return FileResponse(os.path.join(frontend_dist_path, "index.html"))

if __name__ == "__main__":
    multiprocessing.freeze_support()
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
