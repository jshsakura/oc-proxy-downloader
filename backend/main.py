from core.config import get_config, save_config, get_download_path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, BackgroundTasks, HTTPException, Body, APIRouter
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, HttpUrl
from core.models import Base, DownloadRequest
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

# Get the absolute path to the frontend/dist directory
backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(backend_dir)
frontend_dist_path = os.path.join(project_root, "frontend", "dist")

# 다운로드 스레드 관리
class DownloadManager:
    def __init__(self):
        self.active_downloads = {}  # {download_id: Process}

    def start_download(self, download_id, func, *args, **kwargs):
        self.cancel_download(download_id)
        p = multiprocessing.Process(target=func, args=args, kwargs=kwargs)
        p.start()
        self.active_downloads[download_id] = p

    def cancel_download(self, download_id):
        p = self.active_downloads.get(download_id)
        if p and p.is_alive():
            p.terminate()
        self.active_downloads.pop(download_id, None)

    def is_download_active(self, download_id):
        p = self.active_downloads.get(download_id)
        return p and p.is_alive()

# 전역 다운로드 매니저 인스턴스
download_manager = DownloadManager()


Base.metadata.create_all(bind=engine)

app = FastAPI()
api_router = APIRouter(prefix="/api")

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
        for connection in self.active_connections:
            await connection.send_text(message)

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
        DownloadRequest.status.in_(["downloading", "proxying"])
    ).update({"status": "paused"})
    db.commit()
    print(f"[LOG] 서버 재시작: {affected}개의 진행 중 다운로드를 paused로 변경")


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
    password: str = None
    use_proxy: Optional[bool] = True

def parse_direct_link(url, password=None, proxies=None, req_id=None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36 Edg/116.0.1938.54',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Fetch-User': '?1',
        'Referer': str(url),
    }
    payload = {'dl_no_ssl': 'on', 'dlinline': 'on'}
    if password:
        payload['pass'] = password
    # 프록시 리스트 순차 시도
    proxy_list = get_all_proxies()
    tried = False
    scraper = cloudscraper.create_scraper()
    for proxy_addr in proxy_list:
        if req_id: # Check status only if req_id is provided
            db_check = next(get_db())
            try:
                current_req = db_check.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
                if current_req and current_req.status == "paused":
                    print(f"[LOG] Proxy parsing for {req_id} paused. Exiting proxy loop.")
                    return None # Exit if paused
            finally:
                db_check.close()

        proxies = {"http": proxy_addr, "https": proxy_addr}
        try:
            r = scraper.post(url, payload, headers=headers, proxies=proxies, timeout=10, verify=False)
            print(f"[LOG] 프록시 {proxy_addr} 응답코드: {r.status_code}")
            print(f"[LOG] 프록시 {proxy_addr} 응답 HTML 일부: {r.text[:1000]}")
            tried = True
            if r.status_code == 200:
                print(f"[LOG] Content-Length from direct link parsing: {r.headers.get("Content-Length")}")
                html = lxml.html.fromstring(r.content)
                direct_link_elem = html.xpath('/html/body/div[4]/div[2]/a')
                if direct_link_elem:
                    return direct_link_elem[0].get('href')
        except Exception as e:
            print(f"[LOG] 프록시 {proxy_addr} 예외: {e}")
            continue
    # 프록시 모두 실패 시 로컬로 시도
    try:
        r = scraper.post(url, payload, headers=headers, timeout=10, verify=False)
        print(f"[LOG] 로컬 응답코드: {r.status_code}")
        print(f"[LOG] 로컬 응답 HTML 일부: {r.text[:1000]}")
        if r.status_code == 200:
            html = lxml.html.fromstring(r.content)
            direct_link_elem = html.xpath('/html/body/div[4]/div[2]/a')
            if direct_link_elem:
                return direct_link_elem[0].get('href')
    except Exception as e:
        print(f"[LOG] 로컬 direct_link 파싱 예외: {e}")
    return None

def get_or_parse_direct_link(req, proxies=None, use_proxy=True):
    if req.direct_link:
        return req.direct_link
    # 프록시 없이 시도
    if not use_proxy:
        return parse_direct_link(req.url, req.password, proxies=None, req_id=req.id)
    # 프록시 순회 코드 (기존)
    proxy_list = get_all_proxies()
    tried = False
    scraper = cloudscraper.create_scraper()
    for proxy_addr in proxy_list:
        if req.id: # Check status only if req_id is provided
            db_check = next(get_db())
            try:
                current_req = db_check.query(DownloadRequest).filter(DownloadRequest.id == req.id).first()
                if current_req and current_req.status == "paused":
                    print(f"[LOG] Proxy parsing for {req.id} paused. Exiting proxy loop.")
                    return None # Exit if paused
            finally:
                db_check.close()

        proxies = {"http": proxy_addr, "https": proxy_addr}
        try:
            r = scraper.post(req.url, payload={'dl_no_ssl': 'on', 'dlinline': 'on'}, headers=headers, proxies=proxies, timeout=10, verify=False)
            print(f"[LOG] 프록시 {proxy_addr} 응답코드: {r.status_code}")
            print(f"[LOG] 프록시 {proxy_addr} 응답 HTML 일부: {r.text[:1000]}")
            tried = True
            if r.status_code == 200:
                print(f"[LOG] Content-Length from direct link parsing: {r.headers.get("Content-Length")}")
                html = lxml.html.fromstring(r.content)
                direct_link_elem = html.xpath('/html/body/div[4]/div[2]/a')
                if direct_link_elem:
                    return direct_link_elem[0].get('href')
        except Exception as e:
            print(f"[LOG] 프록시 {proxy_addr} 예외: {e}")
            continue
    # 프록시 모두 실패 시 로컬로 시도
    try:
        r = scraper.post(req.url, payload={'dl_no_ssl': 'on', 'dlinline': 'on'}, headers=headers, timeout=10, verify=False)
        print(f"[LOG] 로컬 응답코드: {r.status_code}")
        print(f"[LOG] 로컬 응답 HTML 일부: {r.text[:1000]}")
        if r.status_code == 200:
            html = lxml.html.fromstring(r.content)
            direct_link_elem = html.xpath('/html/body/div[4]/div[2]/a')
            if direct_link_elem:
                return direct_link_elem[0].get('href')
    except Exception as e:
        print(f"[LOG] 로컬 direct_link 파싱 예외: {e}")
    return None

def download_1fichier_file(request_id: int, lang: str = "ko", use_proxy: bool = True):
    print(f"[LOG] Entering download_1fichier_file for request_id: {request_id}")
    db = next(get_db()) # Get a new session for this background task
    req = None # Initialize req to None
    try:
        req = db.query(DownloadRequest).filter(DownloadRequest.id == request_id).first()
        if not req:
            print(f"[LOG] DownloadRequest not found: {request_id}")
            return

        download_path = get_download_path()
        print(f"[LOG] Download path: {download_path}")

        # Check if file already exists to resume download
        file_path = download_path / (req.file_name if req.file_name else f"download_{request_id}")
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
        notify_status_update(db, req.id, lang)
        print(f"[LOG] DB status updated to proxying for {req.id}")
        print(f"[LOG] Before get_or_parse_direct_link: req.total_size={req.total_size}, req.downloaded_size={req.downloaded_size}")
        direct_link = get_or_parse_direct_link(req, use_proxy=use_proxy)
        print(f"[LOG] After get_or_parse_direct_link: direct_link={direct_link}, req.total_size={req.total_size}, req.downloaded_size={req.downloaded_size}")
        print(f"[LOG] Direct link for {req.id}: {direct_link}")

        if not direct_link:
            raise Exception("Direct link not found")

        req.status = "downloading" # Set status to downloading after direct link is found
        db.commit()
        notify_status_update(db, req.id, lang)
        print(f"[LOG] DB status updated to downloading for {req.id}")

        headers = {}
        if initial_downloaded_size > 0:
            headers["Range"] = f"bytes={initial_downloaded_size}-"
            print(f"[LOG] Request headers with Range: {headers}")

        # Use requests to download the file
        with requests.get(direct_link, stream=True, allow_redirects=True, headers=headers) as r:
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
                file_name = os.path.basename(urlparse(direct_link).path)
                if not file_name:
                    file_name = f"download_{request_id}" # Generic name if all else fails
            print(f"[LOG] Determined file name: {file_name}")

            # If resuming, and file_name was not set, set it now
            if not req.file_name:
                req.file_name = file_name
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

            req.total_size = total_size
            db.commit()
            notify_status_update(db, req.id, lang) # Call notify_status_update here
            print(f"[LOG] DB file_name and total_size updated for {req.id}")

            # Open file in append mode if resuming, else write mode
            mode = "ab" if initial_downloaded_size > 0 else "wb"
            print(f"[LOG] Opening file in mode: {mode}")
            with open(file_path, mode) as f:
                chunk_count = 0
                last_status_check = time.time()
                status_check_interval = 2.0  # 2초마다 상태 체크
                
                for chunk in r.iter_content(chunk_size=8192):
                    chunk_count += 1
                    current_time = time.time()
                    
                    # 효율적인 상태 체크: 2초마다 또는 1MB마다
                    should_check_status = (
                        current_time - last_status_check >= status_check_interval or
                        chunk_count % 128 == 0  # 1MB (8192 * 128 = 1MB)
                    )
                    
                    if should_check_status:
                        db.refresh(req) # Refresh the req object from the database
                        print(f"[LOG] Download {req.id} status refreshed: {req.status}")
                        last_status_check = current_time

                    if req.status == "paused": # Check for pause status
                        print(f"[LOG] Download {req.id} paused. Exiting chunk loop.")
                        return # Exit the function, download will resume later
                    
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    req.downloaded_size = downloaded_size
                    db.commit()
                    # Update status every 1MB or 10% of total size, whichever is smaller
                    if total_size > 0 and (downloaded_size % (1024 * 1024) == 0 or downloaded_size * 10 // total_size != (downloaded_size - len(chunk)) * 10 // total_size):
                        notify_status_update(db, req.id, lang)
                print(f"[LOG] Finished writing all chunks for {req.id}")

        req.status = "done"
        req.downloaded_size = total_size # Ensure downloaded_size is total_size on completion
        db.commit()
        notify_status_update(db, req.id, lang)
        print(f"[LOG] 다운로드 완료 처리: {req.url}")

    except requests.exceptions.RequestException as e:
        error_message = f"Network or HTTP error: {e}"
        print(f"[LOG] Download {request_id} failed due to RequestException: {error_message}")
        if req: # Ensure req is defined before accessing its attributes
            req.status = "failed"
            req.error = error_message
            db.commit()
            notify_status_update(db, req.id, lang)
        else:
            print(f"[LOG] Critical: req was None when RequestException occurred for download_id {request_id}")
    except Exception as e:
        error_message = str(e)
        print(f"[LOG] Download {request_id} failed due to general Exception: {error_message}")
        if req: # Ensure req is defined before accessing its attributes
            req.status = "failed"
            req.error = error_message
            db.commit()
            notify_status_update(db, req.id, lang)
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

def get_lang(request: Request = None):
    return request.headers.get("accept-language", "ko")[:2] if request else "ko"

@api_router.post("/download/")
def create_download_task(request: DownloadRequestCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db), req: Request = None):
    lang = get_lang(req)
    db_req = DownloadRequest(
        url=str(request.url),
        status="proxying", # Set initial status to proxying
        password=request.password
    )
    db.add(db_req)
    db.commit()
    db.refresh(db_req)
    notify_status_update(db, db_req.id, lang) # Add this line
    print(f"[LOG] New DownloadRequest created: id={db_req.id}, total_size={db_req.total_size}") # Add this log
    
    # DownloadManager를 사용하여 다운로드 시작
    download_manager.start_download(db_req.id, download_1fichier_file, db_req.id, lang, request.use_proxy)
    return {"id": db_req.id, "status": db_req.status}

@api_router.get("/history/")
def get_download_history(db: Session = Depends(get_db), req: Request = None):
    lang = get_lang(req)
    page = int(req.query_params.get("page", 1))
    size = int(req.query_params.get("size", 10))
    sort = req.query_params.get("sort", "requested_at")
    order = req.query_params.get("order", "desc")
    search = req.query_params.get("search", "")
    
    query = db.query(DownloadRequest)
    if search:
        query = query.filter(
            or_(
                DownloadRequest.url.contains(search),
                DownloadRequest.file_name.contains(search),
                DownloadRequest.status.contains(search)
            )
        )
    
    sort_col = getattr(DownloadRequest, sort, DownloadRequest.requested_at)
    if order == "desc":
        query = query.order_by(desc(sort_col))
    else:
        query = query.order_by(asc(sort_col))
        
    total = query.count()
    total_pages = (total + size - 1) // size
    items = query.offset((page - 1) * size).limit(size).all()
    
    result = []
    for item in items:
        item_dict = item.as_dict()
        item_dict["status"] = item.status # Send raw status to frontend for CSS class consistency
        result.append(item_dict)
        
    return {"items": result, "page": page, "total_pages": total_pages}

@api_router.get("/history/{download_id}")
def get_download_detail(download_id: int, db: Session = Depends(get_db), req: Request = None):
    lang = get_lang(req)
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=get_message("download_not_found", lang))
    item_dict = item.as_dict()
    item_dict["status"] = item.status # Send raw status to frontend
    return item_dict

@api_router.post("/resume/{download_id}")
def resume_download(download_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), req: Request = None):
    lang = get_lang(req)
    use_proxy = req.query_params.get("use_proxy", "true").lower() == "true"
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=get_message("download_not_found", lang))
    item.status = "downloading" # Change to downloading directly
    item.use_proxy = use_proxy  # use_proxy 값 저장
    db.commit()
    notify_status_update(db, item.id, lang)
    # DownloadManager를 사용하여 다운로드 시작
    download_manager.start_download(download_id, download_1fichier_file, download_id, lang, use_proxy)
    return {"id": item.id, "status": item.status, "message": get_message("resume_success", lang)}

@api_router.post("/pause/{download_id}")
def pause_download(download_id: int, db: Session = Depends(get_db), req: Request = None):
    lang = get_lang(req)
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Download not found")
    item.status = "paused" # Change status to 'paused'
    db.commit()
    notify_status_update(db, item.id, lang)
    
    # 활성 다운로드가 있으면 취소
    if download_manager.is_download_active(download_id):
        download_manager.cancel_download(download_id)
        print(f"[LOG] Download {download_id} cancelled due to pause request")
    
    return {"id": item.id, "status": item.status}

@api_router.post("/delete/{download_id}")
def delete_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Download not found")
    db.delete(item)
    db.commit()
    return {"id": download_id, "deleted": True}

@api_router.post("/delete/")
def delete_multiple_downloads(data: dict = Body(...), db: Session = Depends(get_db)):
    ids = data.get("ids", [])
    for download_id in ids:
        item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if item:
            db.delete(item)
    db.commit()
    return {"deleted_ids": ids}

@api_router.post("/retry/{download_id}")
def retry_download(download_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), req: Request = None):
    lang = get_lang(req)
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=get_message("download_not_found", lang))
    item.status = "downloading" # Change to downloading directly
    item.error = None
    db.commit()
    notify_status_update(db, item.id, lang)
    
    # DownloadManager를 사용하여 다운로드 시작
    download_manager.start_download(download_id, download_1fichier_file, download_id, lang)
    return {"id": item.id, "status": item.status, "message": get_message("retry_success", lang)}

@api_router.get("/proxies/")
def get_proxies():
    return get_all_proxies()

@api_router.post("/proxies/")
def add_proxy(proxy: str = Body(..., embed=True)):
    with open("proxies.txt", "a") as f:
        f.write(proxy + "\n")
    return {"message": "Proxy added successfully"}

@api_router.delete("/proxies/")
def delete_proxy(proxy: str = Body(..., embed=True)):
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
def get_settings_endpoint():
    config = get_config()
    # Use the already resolved and ensured path from get_download_path()
    config['download_path'] = str(get_download_path())
    return config

@api_router.post("/select_folder")
async def select_folder():
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    folder_selected = filedialog.askdirectory()
    root.destroy()
    return {"path": folder_selected}

@api_router.post("/settings")
def update_settings_endpoint(settings: dict):
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
async def serve_locale_file(lang: str):
    locale_file_path = os.path.join(backend_dir, "locales", f"{lang}.json")
    if os.path.exists(locale_file_path):
        return FileResponse(locale_file_path, media_type="application/json")
    raise HTTPException(status_code=404, detail="Locale file not found")

@api_router.get("/downloads/active")
def get_active_downloads():
    """활성 다운로드 목록 반환"""
    active_downloads = list(download_manager.active_downloads.keys())
    return {"active_downloads": active_downloads, "count": len(active_downloads)}

@api_router.post("/downloads/cancel/{download_id}")
def cancel_download(download_id: int, db: Session = Depends(get_db), req: Request = None):
    """다운로드 강제 취소"""
    lang = get_lang(req)
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=get_message("download_not_found", lang))
    
    # 스레드 취소
    if download_manager.is_download_active(download_id):
        download_manager.cancel_download(download_id)
        print(f"[LOG] Download {download_id} forcefully cancelled")
    
    # 상태를 failed로 변경
    item.status = "failed"
    item.error = "Download cancelled by user"
    db.commit()
    notify_status_update(db, item.id, lang)
    
    return {"id": item.id, "status": item.status, "message": "Download cancelled"}

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
