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

# Get the absolute path to the frontend/dist directory
backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(backend_dir)
frontend_dist_path = os.path.join(project_root, "frontend", "dist")


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
        item_dict["status"] = get_message(status_map.get(item.status, item.status), lang)
        status_queue.put(json.dumps({"type": "status_update", "data": item_dict}))

async def notify_proxy_try(download_id: int, proxy: str):
    import json
    await manager.broadcast(json.dumps({"id": download_id, "proxy": proxy, "type": "proxy_try"}))

class DownloadRequestCreate(BaseModel):
    url: HttpUrl
    password: str = None

def parse_direct_link(url, password=None, proxies=None):
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
        proxies = {"http": proxy_addr, "https": proxy_addr}
        try:
            r = scraper.post(url, payload, headers=headers, proxies=proxies, timeout=10, verify=False)
            print(f"[LOG] 프록시 {proxy_addr} 응답코드: {r.status_code}")
            print(f"[LOG] 프록시 {proxy_addr} 응답 HTML 일부: {r.text[:1000]}")
            tried = True
            if r.status_code == 200:
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

def get_or_parse_direct_link(req, proxies=None):
    if req.direct_link:
        return req.direct_link
    direct_link = parse_direct_link(req.url, req.password, proxies)
    req.direct_link = direct_link
    return direct_link

def download_1fichier_file(request_id: int, db: Session, lang: str = "ko"):
    req = db.query(DownloadRequest).filter(DownloadRequest.id == request_id).first()
    if not req:
        print(f"[LOG] DownloadRequest not found: {request_id}")
        return

    download_path = get_download_path()

    try:
        req.status = "downloading"
        db.commit()
        notify_status_update(db, req.id, lang)
        print(f"[LOG] 다운로드 시작: {req.url}")

        direct_link = get_or_parse_direct_link(req)

        if not direct_link:
            raise Exception("Direct link not found")

        # Use requests to download the file
        with requests.get(direct_link, stream=True, allow_redirects=True) as r:
            r.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            file_name = None
            if "Content-Disposition" in r.headers:
                # Try to extract filename from Content-Disposition header
                cd = r.headers["Content-Disposition"]
                file_name = re.findall(r"filename\*=UTF-8\'\'(.*?)", cd)
                if not file_name:
                    file_name = re.findall(r"filename=\"(.*?)\"", cd)
                if file_name:
                    file_name = unquote(file_name[0])
            
            if not file_name:
                # Fallback to filename from URL
                file_name = os.path.basename(urlparse(direct_link).path)
                if not file_name:
                    file_name = f"download_{request_id}" # Generic name if all else fails

            file_path = download_path / file_name
            total_size = int(r.headers.get("Content-Length", 0))
            downloaded_size = 0

            req.file_name = file_name
            req.file_size = total_size
            db.commit()
            notify_status_update(db, req.id, lang)

            with open(file_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if req.status == "paused": # Check for pause status
                        print(f"[LOG] Download {req.id} paused.")
                        return # Exit the function, download will resume later
                    
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    req.downloaded_size = downloaded_size
                    db.commit()
                    # Update status every 1MB or 10% of total size, whichever is smaller
                    if total_size > 0 and (downloaded_size % (1024 * 1024) == 0 or downloaded_size * 10 // total_size != (downloaded_size - len(chunk)) * 10 // total_size):
                        notify_status_update(db, req.id, lang)

        req.status = "done"
        req.downloaded_size = total_size # Ensure downloaded_size is total_size on completion
        db.commit()
        notify_status_update(db, req.id, lang)
        print(f"[LOG] 다운로드 완료 처리: {req.url}")

    except requests.exceptions.RequestException as e:
        req.status = "failed"
        req.error = f"Network or HTTP error: {e}"
        db.commit()
        notify_status_update(db, req.id, lang)
        print(f"[LOG] 다운로드 예외 발생 (requests): {e}")
    except Exception as e:
        req.status = "failed"
        req.error = str(e)
        db.commit()
        notify_status_update(db, req.id, lang)
        print(f"[LOG] 다운로드 예외 발생: {e}")


status_map = {
    "pending": "download_pending",
    "downloading": "download_downloading",
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
        status="pending",
        password=request.password
    )
    db.add(db_req)
    db.commit()
    db.refresh(db_req)
    background_tasks.add_task(download_1fichier_file, db_req.id, db, lang)
    return {"id": db_req.id, "status": get_message(status_map[db_req.status], lang)}

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
        item_dict["status"] = get_message(status_map.get(item.status, item.status), lang)
        result.append(item_dict)
        
    return {"items": result, "page": page, "total_pages": total_pages}

@api_router.get("/history/{download_id}")
def get_download_detail(download_id: int, db: Session = Depends(get_db), req: Request = None):
    lang = get_lang(req)
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=get_message("download_not_found", lang))
    item_dict = item.as_dict()
    item_dict["status"] = get_message(status_map.get(item.status, item.status), lang)
    return item_dict

@api_router.post("/resume/{download_id}")
def resume_download(download_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), req: Request = None):
    lang = get_lang(req)
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=get_message("download_not_found", lang))
    item.status = "pending"
    db.commit()
    notify_status_update(db, item.id, lang)
    background_tasks.add_task(download_1fichier_file, item.id, db, lang)
    return {"id": item.id, "status": get_message(status_map[item.status], lang), "message": get_message("resume_success", lang)}

@api_router.post("/pause/{download_id}")
def pause_download(download_id: int, db: Session = Depends(get_db), req: Request = None):
    lang = get_lang(req)
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Download not found")
    item.status = "pending"
    db.commit()
    notify_status_update(db, item.id, lang)
    return {"id": item.id, "status": get_message(status_map[item.status], lang)}

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
    item.status = "pending"
    item.error = None
    db.commit()
    notify_status_update(db, item.id, lang)
    background_tasks.add_task(download_1fichier_file, item.id, db, lang)
    return {"id": item.id, "status": get_message(status_map[item.status], lang), "message": get_message("retry_success", lang)}

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

@api_router.post("/settings/")
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

app.include_router(api_router)

# Serve static files from the dist directory
app.mount("/", StaticFiles(directory=frontend_dist_path), name="static")

# Catch-all route for SPA routing
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    return FileResponse(os.path.join(frontend_dist_path, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
