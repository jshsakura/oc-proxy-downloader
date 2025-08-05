# -*- coding: utf-8 -*-
# print("[DEBUG] main.py 모듈 로딩 시작")
import sys
import os
import locale
import logging
import signal
import atexit

# UTF-8 인코딩 강제 설정
if sys.platform.startswith('win'):
    try:
        # Windows에서 UTF-8 강제 설정
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

# 강제 stdout 출력 설정
def force_print(*args, **kwargs):
    message = ' '.join(str(arg) for arg in args)
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()

# 기존 print를 force_print로 대체
import builtins
original_print = builtins.print
builtins.print = force_print

# Python 경로 설정 (Docker 환경 대응)
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from core.config import get_config, save_config, get_download_path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Depends, BackgroundTasks, HTTPException, Body, APIRouter
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
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
try:
    import tkinter as tk
    from tkinter import filedialog
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False
import threading
from concurrent.futures import ThreadPoolExecutor, Future
import weakref
import multiprocessing
from typing import Optional
from core.downloader import router as downloader_router
from core.proxy_stats import router as proxy_stats_router

# Get the absolute path to the frontend/dist directory
backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(backend_dir)

# Docker 환경에서는 static 디렉토리 사용, 개발 환경에서는 frontend/dist 사용
if os.path.exists(os.path.join(backend_dir, "static")):
    frontend_dist_path = os.path.join(backend_dir, "static")
else:
    frontend_dist_path = os.path.join(project_root, "frontend", "dist")

# 다운로드 스레드 관리
# 공유 객체들을 별도 모듈에서 import
from core.shared import download_manager, status_queue
from logger import log_once

# 공유 객체 import 완료


Base.metadata.create_all(bind=engine)

app = FastAPI()
# print(f"[DEBUG] FastAPI 앱 생성됨 - ID: {id(app)} PID: {os.getpid()}")

# 모든 요청 로깅 미들웨어
@app.middleware("http")
async def log_requests(request, call_next):
    print(f"[API] === INCOMING REQUEST ===")
    print(f"[API] Method: {request.method}")
    print(f"[API] Path: {request.url.path}")
    print(f"[API] Query: {request.url.query}")
    if request.method == "POST":
        print(f"[API] Headers: {dict(request.headers)}")
    print(f"[API] ========================")
    
    response = await call_next(request)
    
    print(f"[API] === RESPONSE ===")
    print(f"[API] Status: {response.status_code}")
    print(f"[API] =================")
    
    return response

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
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            # 이미 제거된 경우 무시
            pass

    async def broadcast(self, message: str):
        if not self.active_connections:
            return
        
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except ConnectionClosedError:
                # 연결이 정상적으로 종료됨
                disconnected.append(connection)
            except ConnectionClosedOK:
                # 연결이 정상적으로 종료됨
                disconnected.append(connection)
            except Exception as e:
                # 기타 예외
                print(f"[LOG] WebSocket broadcast error: {e}")
                disconnected.append(connection)
        
        # 끊어진 연결 제거
        for connection in disconnected:
            try:
                self.active_connections.remove(connection)
            except ValueError:
                # 이미 제거된 경우 무시
                pass

manager = ConnectionManager()

# status_queue는 shared.py에서 import됨

async def status_broadcaster():
    while True:
        try:
            # non-blocking으로 큐에서 메시지 확인
            try:
                msg = status_queue.get_nowait()
                await manager.broadcast(msg)
            except queue.Empty:
                # 큐가 비어있으면 잠시 대기
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            # 서버 종료 시 정상적으로 종료
            print("[LOG] status_broadcaster 종료됨")
            break
        except Exception as e:
            # 기타 예외 처리
            print(f"[ERROR] status_broadcaster 오류: {e}")
            await asyncio.sleep(1)  # 오류 시 잠시 대기

# 전역 변수로 중복 실행 방지
_startup_executed = False

@app.on_event("startup")
async def startup_event():
    global _startup_executed
    
    # 이미 실행되었으면 무조건 종료
    if _startup_executed:
        return
    
    _startup_executed = True
    
    # WebSocket broadcaster 시작
    asyncio.create_task(status_broadcaster())
    
    # 서버 재시작 시 진행 중이던 다운로드를 모두 paused로 변경
    db = next(get_db())
    
    # 진행 중이던 다운로드들을 가져와서 개별적으로 처리
    downloading_requests = db.query(DownloadRequest).filter(
        DownloadRequest.status.in_([StatusEnum.downloading, StatusEnum.proxying])
    ).all()
    
    for req in downloading_requests:
        req.status = StatusEnum.stopped
        db.commit()
        
        # 각 다운로드의 상태 변경을 WebSocket으로 알림
        try:
            import json
            status_data = {
                "type": "status_update",
                "data": {
                    "id": req.id,
                    "status": "paused",
                    "url": req.url,
                    "file_name": req.file_name,
                    "total_size": req.total_size,
                    "downloaded_size": req.downloaded_size,
                    "requested_at": req.requested_at.isoformat() if req.requested_at else None,
                    "direct_link": req.direct_link,
                    "use_proxy": req.use_proxy,
                    "error": "서버 재시작으로 인한 정지"
                }
            }
            status_queue.put(json.dumps(status_data))
        except Exception as e:
            print(f"[LOG] 서버 시작 시 WebSocket 알림 실패: {e}")
    
    if len(downloading_requests) > 0:
        print(f"[LOG] 서버 재시작: {len(downloading_requests)}개의 진행 중 다운로드를 stopped로 변경")
    else:
        print(f"[LOG] 서버 시작 완료")

# cleanup 중복 실행 방지
_cleanup_executed = False

def cleanup_and_exit():
    """서버 종료 시 정리 작업"""
    global _cleanup_executed
    
    if _cleanup_executed:
        return
    
    _cleanup_executed = True
    print("[LOG] 서버 종료 중...")
    print("[LOG] FastAPI 서버 종료: 모든 백그라운드 다운로드 스레드 관리 목록 비움")
    download_manager.terminate_all_downloads()
    
    # 진행 중인 다운로드들을 정지 상태로 변경
    db = next(get_db())
    try:
        affected = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([StatusEnum.downloading, StatusEnum.proxying])
        ).update({"status": "stopped"})
        db.commit()
        print(f"[LOG] 서버 종료 시 {affected}개의 진행 중 다운로드를 stopped로 변경")
    except Exception as e:
        print(f"[LOG] 서버 종료 시 다운로드 상태 변경 실패: {e}")
    finally:
        db.close()
    
    # 강제로 모든 백그라운드 태스크 종료
    try:
        import threading
        for thread in threading.enumerate():
            if thread != threading.current_thread():
                print(f"[LOG] 활성 스레드 발견: {thread.name}")
        print(f"[LOG] 총 {threading.active_count()}개의 스레드 활성화")
    except Exception as e:
        print(f"[LOG] 스레드 정보 확인 실패: {e}")
    
    print("[LOG] 서버 종료 완료")

def signal_handler(signum, frame):
    """신호 처리기"""
    print(f"\n[LOG] 신호 {signum} 받음. 서버를 종료합니다...")
    cleanup_and_exit()
    sys.exit(0)

# 신호 처리기 등록 (중복 방지)
if not hasattr(cleanup_and_exit, '_handlers_registered'):
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # 종료 신호
    atexit.register(cleanup_and_exit)  # 프로그램 종료 시
    cleanup_and_exit._handlers_registered = True

@app.on_event("shutdown")
def shutdown_event():
    cleanup_and_exit()


@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(10)  # keep alive
    except WebSocketDisconnect:
        print("[LOG] WebSocket 정상 연결 해제")
        manager.disconnect(websocket)
    except ConnectionClosedError:
        print("[LOG] WebSocket 연결이 비정상적으로 종료됨")
        manager.disconnect(websocket)
    except ConnectionClosedOK:
        print("[LOG] WebSocket 연결이 정상적으로 종료됨")
        manager.disconnect(websocket)
    except asyncio.CancelledError:
        print("[LOG] WebSocket 태스크가 취소됨")
        manager.disconnect(websocket)
    except Exception as e:
        print(f"[ERROR] WebSocket 예외: {e}")
        manager.disconnect(websocket)

def notify_status_update(db: Session, download_id: int, lang: str = "ko"):
    import json
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item:
        item_dict = item.as_dict()
        item_dict["status"] = item.status # Send raw status to frontend
        # Safely handle encoding for log messages
        try:
            print(f"[LOG] Notifying status update for {download_id}: {item_dict}")
        except UnicodeEncodeError:
            print(f"[LOG] Notifying status update for {download_id}: (encoding error)")
        status_queue.put(json.dumps({"type": "status_update", "data": item_dict}, ensure_ascii=False))

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
        
        # 프록시 상태 변경을 WebSocket으로 알림
        try:
            import json
            status_queue.put(json.dumps({
                "type": "proxy_update", 
                "data": {"proxy_addr": proxy_addr, "success": success}
            }, ensure_ascii=False))
        except Exception as ws_e:
            print(f"[LOG] 프록시 상태 WebSocket 알림 실패: {ws_e}")
        
    except Exception as e:
        print(f"[LOG] 프록시 사용 기록 저장 실패: {e}")
        db.rollback()

def reset_proxy_usage(db: Session):
    """모든 프록시 사용 기록 초기화 (모든 프록시를 다 써버렸을 때)"""
    try:
        db.query(ProxyStatus).delete()
        db.commit()
        print(f"[LOG] 모든 프록시 사용 기록 초기화 완료")
        
        # 프록시 리셋을 WebSocket으로 알림
        try:
            import json
            status_queue.put(json.dumps({
                "type": "proxy_reset", 
                "data": {"message": "All proxies reset"}
            }, ensure_ascii=False))
        except Exception as ws_e:
            print(f"[LOG] 프록시 리셋 WebSocket 알림 실패: {ws_e}")
    except Exception as e:
        print(f"[LOG] 프록시 사용 기록 초기화 실패: {e}")
        db.rollback()

def test_proxy(proxy_addr, timeout=1):
    """프록시가 작동하는지 빠르게 테스트"""
    try:
        proxy_config = {"http": f"http://{proxy_addr}", "https": f"http://{proxy_addr}"}
        # 1fichier 접근 테스트로 변경 (더 정확한 검증)
        response = requests.get("https://1fichier.com", proxies=proxy_config, timeout=timeout, verify=False)
        print(f"[LOG] 프록시 {proxy_addr} 테스트 결과: {response.status_code}")
        return response.status_code in [200, 403]  # 403도 허용 (차단되었지만 연결은 됨)
    except Exception as e:
        print(f"[LOG] 프록시 {proxy_addr} 테스트 실패: {e}")
        return False

def parse_direct_link(url, password=None, proxies=None, req_id=None, use_proxy=True):
    """1fichier에서 직접 다운로드 링크를 파싱하는 함수 (강화된 버전)"""
    from core.parser import fichier_parser
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
    }
    
    # 강화된 파싱 시도
    def try_advanced_parsing(scraper_or_session, method_name):
        """고급 파싱 시도"""
        try:
            # 1단계: GET 요청으로 초기 페이지 로드
            print(f"[LOG] {method_name} - 초기 페이지 로드...")
            r1 = scraper_or_session.get(url, headers=headers, timeout=3)
            print(f"[LOG] {method_name} GET 응답: {r1.status_code}")
            
            # HTTP 상태 코드가 500이어도 HTML 응답이 있으면 계속 진행
            if r1.status_code not in [200, 500]:
                print(f"[LOG] {method_name} GET 실패: {r1.status_code}")
                return None
            elif r1.status_code == 500:
                print(f"[LOG] {method_name} GET 500 오류지만 HTML 응답 있음, 계속 진행...")
            
            # 대기 시간 확인 (JavaScript 타이머)
            import re
            timer_matches = re.findall(r'setTimeout\s*\([^,]+,\s*(\d+)', r1.text)
            wait_time = 0
            for match in timer_matches:
                time_ms = int(match)
                if 1000 <= time_ms <= 60000:  # 1초~60초
                    wait_time = max(wait_time, time_ms / 1000)
            
            if wait_time > 0:
                print(f"[LOG] {method_name} - 대기 시간 감지: {wait_time}초")
                time.sleep(min(wait_time, 30))  # 최대 30초
            else:
                print(f"[LOG] {method_name} - 기본 대기: 3초")
                time.sleep(3)
            
            # 2단계: POST 데이터 구성
            payload = {'dl_no_ssl': 'on', 'dlinline': 'on'}
            if password:
                payload['pass'] = password
            
            # 숨겨진 필드 추출
            hidden_fields = re.findall(r'<input[^>]*type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']', r1.text, re.IGNORECASE)
            for field_name, field_value in hidden_fields:
                payload[field_name] = field_value
                print(f"[LOG] {method_name} - 숨겨진 필드: {field_name}")
            
            # CSRF 토큰 추출
            csrf_patterns = [
                r'name=["\']_token["\'][^>]*value=["\']([^"\']+)["\']',
                r'value=["\']([^"\']+)["\'][^>]*name=["\']_token["\']'
            ]
            for pattern in csrf_patterns:
                match = re.search(pattern, r1.text, re.IGNORECASE)
                if match:
                    payload['_token'] = match.group(1)
                    print(f"[LOG] {method_name} - CSRF 토큰 추가")
                    break
            
            # 3단계: POST 요청
            headers_post = headers.copy()
            headers_post['Referer'] = str(url)
            
            print(f"[LOG] {method_name} - POST 요청...")
            r2 = scraper_or_session.post(url, data=payload, headers=headers_post, timeout=3)
            print(f"[LOG] {method_name} POST 응답: {r2.status_code}")
            
            # HTTP 상태 코드가 500이어도 HTML 응답이 있으면 파싱 시도
            if r2.status_code in [200, 500]:
                if r2.status_code == 500:
                    print(f"[LOG] {method_name} POST 500 오류지만 HTML 응답 있음, 파싱 시도...")
                
                # 파서로 링크 추출
                direct_link = fichier_parser.parse_download_link(r2.text, str(url))
                if direct_link and direct_link != str(url):
                    print(f"[LOG] {method_name}로 다운로드 링크 발견: {direct_link}")
                    
                    # 파일 정보 추출
                    file_info = fichier_parser.extract_file_info(r2.text)
                    if file_info.get('name'):
                        print(f"[LOG] 파일명: {file_info['name']}")
                    if file_info.get('size'):
                        print(f"[LOG] 파일 크기: {file_info['size']}")
                    
                    return direct_link
                else:
                    print(f"[LOG] {method_name}에서 유효한 다운로드 링크를 찾을 수 없음")
            else:
                print(f"[LOG] {method_name} POST 실패: {r2.status_code}")
            
        except Exception as e:
            print(f"[LOG] {method_name} 예외: {e}")
        
        return None
    
    # 프록시 사용하지 않을 때만 로컬 연결 시도
    if not use_proxy:
        print(f"[LOG] 프록시 비활성화. 로컬 연결로 1fichier 파싱 시도...")
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True
                }
            )
            
            result = try_advanced_parsing(scraper, "로컬 cloudscraper")
            if result:
                return result
        except Exception as e:
            print(f"[LOG] cloudscraper 오류: {e}")
            
            # cloudscraper 실패 시 기본 requests 시도
            try:
                import requests
                session = requests.Session()
                session.verify = False
                result = try_advanced_parsing(session, "로컬 requests")
                if result:
                    return result
            except Exception as e2:
                print(f"[LOG] requests 오류: {e2}")
        
        print(f"[LOG] 로컬 연결로 파싱 실패")
        return None
    
    # 프록시가 제공된 경우 해당 프록시만 사용
    if proxies:
        print(f"[LOG] 지정된 프록시로 파싱 시도: {proxies}")
        try:
            r = scraper.post(url, data=payload, headers=headers, proxies=proxies, timeout=3, verify=False)
            print(f"[LOG] 지정된 프록시 응답코드: {r.status_code}")
            
            if r.status_code == 200:
                print(f"[LOG] HTML 응답 길이: {len(r.text)} 문자")
                
                # 새로운 파서 사용
                direct_link = fichier_parser.parse_download_link(r.text, str(url))
                if direct_link:
                    print(f"[LOG] 지정된 프록시로 다운로드 링크 발견: {direct_link}")
                    
                    # 파일 정보도 추출
                    file_info = fichier_parser.extract_file_info(r.text)
                    if file_info.get('name'):
                        print(f"[LOG] 파일명: {file_info['name']}")
                    if file_info.get('size'):
                        print(f"[LOG] 파일 크기: {file_info['size']}")
                    
                    return direct_link
                else:
                    print(f"[LOG] 지정된 프록시에서 다운로드 링크를 찾을 수 없음")
            else:
                print(f"[LOG] 지정된 프록시 HTTP 오류: {r.status_code}")
                
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, requests.exceptions.Timeout) as e:
            print(f"[LOG] 지정된 프록시 타임아웃: {e}")
            raise e  # 프록시 순환 로직에서 처리하도록 raise
        except requests.exceptions.ProxyError as e:
            print(f"[LOG] 지정된 프록시 연결 오류: {e}")
            raise e  # 프록시 순환 로직에서 처리하도록 raise
        except Exception as e:
            print(f"[LOG] 지정된 프록시 예외 발생: {e}")
            raise e
    
    print(f"[LOG] 프록시 파싱 실패")
    return None

def is_direct_link_expired(direct_link, use_proxy=False, proxy_addr=None):
    """direct_link가 만료되었는지 간단히 체크"""
    if not direct_link:
        return True
    
    # 프록시 설정
    proxies = None
    if use_proxy and proxy_addr:
        proxies = {
            'http': f'http://{proxy_addr}',
            'https': f'http://{proxy_addr}'
        }
    
    # 1fichier 다운로드에 적합한 헤더
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
    }
    
    try:
        # HEAD 요청으로 링크 유효성 확인
        response = requests.head(direct_link, headers=headers, timeout=(1, 3), allow_redirects=True, proxies=proxies)
        print(f"[LOG] direct_link 유효성 검사: {response.status_code}")
        
        if response.status_code in [200, 206]:  # 200 OK 또는 206 Partial Content
            return False
        elif response.status_code in [403, 404, 410, 429]:  # 만료되거나 접근 불가, 요청 제한
            print(f"[LOG] direct_link 만료 감지: {response.status_code}")
            return True
        else:
            print(f"[LOG] direct_link 상태 확인 중 예상치 못한 응답: {response.status_code}")
            return True
    except Exception as e:
        print(f"[LOG] direct_link 유효성 검사 실패: {e}")
        return True

def get_or_parse_direct_link(req, proxies=None, use_proxy=True, force_reparse=False, proxy_addr=None):
    """다운로드 요청에서 직접 링크를 가져오거나 파싱하는 함수 (개선된 버전)"""
    
    # proxy_addr이 있으면 proxies 생성
    if proxy_addr and use_proxy:
        proxies = {
            'http': f'http://{proxy_addr}',
            'https': f'http://{proxy_addr}'
        }
        # print(f"[LOG] 프록시 설정: {proxy_addr}")
    
    # 강제 재파싱이 요청되었거나 기존 링크가 없는 경우
    if force_reparse or not req.direct_link:
        print(f"[LOG] direct_link 새로 파싱 (force_reparse: {force_reparse}, proxy: {proxy_addr})")
        return parse_direct_link(req.url, req.password, proxies=proxies, req_id=req.id, use_proxy=use_proxy)
    
    # 기존 링크가 있는 경우 만료 여부 확인
    if is_direct_link_expired(req.direct_link, use_proxy=use_proxy, proxy_addr=proxy_addr):
        print(f"[LOG] 기존 direct_link가 만료됨. 재파싱 시작: {req.direct_link} (proxy: {proxy_addr})")
        return parse_direct_link(req.url, req.password, proxies=proxies, req_id=req.id, use_proxy=use_proxy)
    
    print(f"[LOG] 기존 direct_link 재사용: {req.direct_link}")
    return req.direct_link

def exit_if_parent_dead():
    """부모 프로세스가 종료되면 자식 프로세스도 종료하는 함수"""
    parent_pid = os.getppid()
    while True:
        if os.getppid() != parent_pid:
            print("[LOG] 부모 프로세스가 종료됨. 자식 프로세스도 종료.")
            # 임시 파일 정리는 스킵 (부모가 종료되면서 이미 처리됨)
            os._exit(0)
        time.sleep(1)

def cleanup_incomplete_file(file_path, is_complete=False):
    """다운로드가 완료되지 않은 파일 정리"""
    try:
        if file_path and os.path.exists(file_path):
            if not is_complete:
                # 불완전한 다운로드 파일은 .part 확장자 추가하여 구분
                part_path = str(file_path) + ".part"
                if not os.path.exists(part_path):
                    os.rename(file_path, part_path)
                    print(f"[LOG] 불완전한 다운로드 파일을 .part로 이름 변경: {part_path}")
            else:
                # 완료된 다운로드는 .part 확장자 제거
                if str(file_path).endswith('.part'):
                    final_path = str(file_path)[:-5]  # .part 제거
                    os.rename(file_path, final_path)
                    print(f"[LOG] 완료된 다운로드 파일에서 .part 제거: {final_path}")
    except Exception as e:
        print(f"[LOG] 파일 정리 실패: {e}")

def download_1fichier_file_NEW_VERSION(request_id: int, lang: str = "ko", use_proxy: bool = True):
    # 부모 감시 스레드 시작 (자식 프로세스에서만 동작)
    if os.getppid() != os.getpid():
        threading.Thread(target=exit_if_parent_dead, daemon=True).start()
    
    print("=" * 80)
    print(f"[LOG] *** 최신 프록시 순환 로직 버전 2024 *** DOWNLOAD START")
    print(f"[LOG] Request ID: {request_id}, Lang: {lang}, Use Proxy: {use_proxy}")
    print(f"[LOG] Function called at: {time.strftime('%H:%M:%S')}")
    print("=" * 80)
    
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
        base_filename = req.file_name if req is not None and req.file_name is not None else f"download_{request_id}"
        file_path = download_path / base_filename
        part_file_path = download_path / (base_filename + ".part")
        
        initial_downloaded_size = 0
        # .part 파일이 있으면 그것을 우선 사용
        if part_file_path.exists():
            file_path = part_file_path
            initial_downloaded_size = part_file_path.stat().st_size
            print(f"[LOG] Resuming download from .part file for {req.id} from {initial_downloaded_size} bytes. File: {file_path}")
        elif file_path.exists():
            initial_downloaded_size = file_path.stat().st_size
            print(f"[LOG] Resuming download for {req.id} from {initial_downloaded_size} bytes. File: {file_path}")
        else:
            # 새 다운로드는 .part 파일로 시작
            file_path = part_file_path
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
        
        # 타임아웃 체크만 유지
        
        # 다운로드 시작 전 상태 체크 (혹시 이미 정지 요청이 있었는지)
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 시작 전 이미 정지 상태 감지. 중단합니다.")
            return
        
        # 간단한 프록시 순환 로직
        print(f"[LOG] 프록시 사용 여부: {use_proxy}")
        
        available_proxies = []
        if use_proxy:
            available_proxies = get_unused_proxies(db)
            print(f"[LOG] 사용 가능한 프록시: {len(available_proxies)}개")
        
        # 이어받기인 경우 direct_link 재파싱
        force_reparse = initial_downloaded_size > 0
        if force_reparse:
            print(f"[LOG] 이어받기 감지. direct_link 재파싱 수행")
        
        # Direct Link 파싱 with 프록시 순환
        direct_link = None
        used_proxy_addr = None
        download_proxies = None
        
        if use_proxy and available_proxies:
            # 프록시 순환하여 direct_link 파싱
            print(f"[LOG] *** 프록시 순환 시작! 총 {len(available_proxies)}개 프록시 ***")
            for i, proxy_addr in enumerate(available_proxies):
                # 상태 체크 - stopped면 중단
                db.refresh(req)
                if req.status == StatusEnum.stopped:
                    print(f"[LOG] 프록시 파싱 중 정지 요청 감지. 중단합니다.")
                    return
                
                try:
                    print(f"[LOG] Direct Link 파싱 - 프록시 {i+1}/{len(available_proxies)} 시도: {proxy_addr}")
                    
                    # 프록시 시도 중 상태 WebSocket 전송
                    try:
                        import json
                        status_queue.put(json.dumps({
                            "type": "proxy_trying", 
                            "data": {
                                "proxy": proxy_addr,
                                "step": "parsing",
                                "current": i+1,
                                "total": len(available_proxies)
                            }
                        }, ensure_ascii=False))
                    except:
                        pass
                    
                    # 프록시 시도 전 상태 재체크
                    db.refresh(req)
                    if req.status == StatusEnum.stopped:
                        print(f"[LOG] 프록시 파싱 시도 전 정지 요청 감지. 중단합니다.")
                        return
                    
                    direct_link = get_or_parse_direct_link(req, use_proxy=True, force_reparse=force_reparse, proxy_addr=proxy_addr)
                    
                    # 파싱 성공 후 다음 프록시로
                    
                    if direct_link:
                        used_proxy_addr = proxy_addr
                        download_proxies = {
                            'http': f'http://{proxy_addr}',
                            'https': f'http://{proxy_addr}'
                        }
                        # mark_proxy_used(db, proxy_addr, success=True)  # 중복 기록 방지: 다운로드 완료 시에만 기록
                        print(f"[LOG] Direct Link 파싱 성공 - 프록시: {proxy_addr}")
                        
                        # 프록시 성공 상태 WebSocket 전송
                        try:
                            status_queue.put(json.dumps({
                                "type": "proxy_success", 
                                "data": {
                                    "proxy": proxy_addr,
                                    "step": "parsing"
                                }
                            }, ensure_ascii=False))
                        except:
                            pass
                        break
                except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, 
                        requests.exceptions.Timeout, requests.exceptions.ProxyError) as e:
                    print(f"[LOG] Direct Link 파싱 실패 - 프록시 {proxy_addr}: {e}")
                    # mark_proxy_used(db, proxy_addr, success=False)  # 중복 기록 방지
                    
                    # 예외 발생 시 다음 프록시로
                    
                    # 프록시 실패 상태 WebSocket 전송
                    try:
                        status_queue.put(json.dumps({
                            "type": "proxy_failed", 
                            "data": {
                                "proxy": proxy_addr,
                                "step": "parsing",
                                "error": str(e)
                            }
                        }, ensure_ascii=False))
                    except:
                        pass
                    continue
                except Exception as e:
                    print(f"[LOG] Direct Link 파싱 오류 - 프록시 {proxy_addr}: {e}")
                    # mark_proxy_used(db, proxy_addr, success=False)  # 중복 기록 방지
                    
                    # 프록시 실패 상태 WebSocket 전송
                    try:
                        status_queue.put(json.dumps({
                            "type": "proxy_failed", 
                            "data": {
                                "proxy": proxy_addr,
                                "step": "parsing",
                                "error": str(e)
                            }
                        }, ensure_ascii=False))
                    except:
                        pass
                    continue
        else:
            # 프록시 없이 시도
            direct_link = get_or_parse_direct_link(req, use_proxy=False, force_reparse=force_reparse, proxy_addr=None)
        print(f"[LOG] After get_or_parse_direct_link: direct_link={direct_link}, req.total_size={req.total_size}, req.downloaded_size={req.downloaded_size}")
        print(f"[LOG] Direct link for {req.id}: {direct_link}")

        if not direct_link:
            raise Exception("Cannot find download link from 1fichier. Site structure may have changed or proxy issue.")
        
        # 다운로드 링크를 데이터베이스에 저장
        req.direct_link = direct_link
        db.commit()

        setattr(req, "status", StatusEnum.downloading) # Set status to downloading after direct link is found
        db.commit()
        notify_status_update(db, int(getattr(req, 'id')), lang)
        print(f"[LOG] DB status updated to downloading for {req.id}")

        # 단순한 다운로드 함수 (재시도만 포함)
        def simple_download(url, headers, proxies, max_retries=2):
            """단순 다운로드 함수 - ProxyError 시 즉시 실패"""
            range_removed = False
            
            for attempt in range(max_retries):
                # 재시도는 빠르게 진행
                try:
                    print(f"[LOG] 다운로드 시도 {attempt + 1}/{max_retries} (프록시: {proxies})")
                    current_headers = headers.copy()
                    
                    # HTTP 요청은 빠르게 진행
                    
                    response = requests.get(url, stream=True, allow_redirects=True, headers=current_headers, proxies=proxies, timeout=(1, 5))
                    print(f"[LOG] 응답 상태 코드: {response.status_code}")
                    
                    # 409 에러 처리 (Range 헤더 제거)
                    if response.status_code == 409 and "Range" in current_headers:
                        print(f"[LOG] 409 에러 - Range 헤더 제거 후 재시도")
                        current_headers.pop("Range", None)
                        range_removed = True
                        response = requests.get(url, stream=True, allow_redirects=True, headers=current_headers, proxies=proxies, timeout=(1, 5))
                    
                    response.raise_for_status()
                    return response, range_removed
                    
                except requests.exceptions.HTTPError as e:
                    if e.response and e.response.status_code in [403, 404, 410]:
                        # 링크 만료 - 재파싱 필요하지만 여기서는 바로 실패
                        print(f"[LOG] HTTP {e.response.status_code} - 링크 만료")
                        raise e
                    if attempt < max_retries - 1:
                        print(f"[LOG] HTTP 에러 재시도...")
                        time.sleep(1)
                        continue
                    raise e
                    
                except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, 
                        requests.exceptions.Timeout, requests.exceptions.ProxyError) as e:
                    # 프록시/연결 에러는 즉시 실패 (다음 프록시로)
                    print(f"[LOG] 연결/프록시 에러: {e}")
                    raise e
                    
                except Exception as e:
                    if attempt < max_retries - 1:
                        print(f"[LOG] 일반 에러 재시도: {e}")
                        time.sleep(1)
                        continue
                    raise e
            
            raise Exception("모든 재시도 실패")

        # 이어받기를 위한 HEAD 요청으로 서버 Range 지원 확인
        resume_supported = False
        server_file_size = None
        
        if initial_downloaded_size > 0:
            try:
                print(f"[LOG] HEAD 요청으로 서버 파일 정보 확인...")
                head_response = requests.head(str(direct_link), allow_redirects=True, proxies=download_proxies, timeout=(2, 5))
                print(f"[LOG] HEAD 응답: {head_response.status_code}")
                print(f"[LOG] HEAD 헤더: {head_response.headers}")
                
                # Accept-Ranges 헤더 확인
                accept_ranges = head_response.headers.get('Accept-Ranges', '').lower()
                server_file_size = head_response.headers.get('Content-Length')
                
                if accept_ranges == 'bytes' and server_file_size:
                    server_file_size = int(server_file_size)
                    print(f"[LOG] 서버 파일 크기: {server_file_size}, 현재 다운로드된 크기: {initial_downloaded_size}")
                    
                    if initial_downloaded_size < server_file_size:
                        resume_supported = True
                        print(f"[LOG] 이어받기 지원됨")
                    elif initial_downloaded_size >= server_file_size:
                        print(f"[LOG] 파일이 이미 완전히 다운로드됨")
                        # 완료 처리
                        setattr(req, "status", StatusEnum.done)
                        setattr(req, "downloaded_size", server_file_size)
                        setattr(req, "total_size", server_file_size)
                        db.commit()
                        cleanup_incomplete_file(file_path, is_complete=True)
                        notify_status_update(db, int(getattr(req, 'id')), lang)
                        return
                    else:
                        print(f"[LOG] 로컬 파일이 서버 파일보다 큼. 처음부터 다시 다운로드")
                        initial_downloaded_size = 0
                        file_path = part_file_path  # .part 파일로 다시 시작
                else:
                    print(f"[LOG] 서버가 Range 요청을 지원하지 않음 (Accept-Ranges: {accept_ranges})")
                    
            except Exception as e:
                print(f"[LOG] HEAD 요청 실패: {e}. 이어받기 비활성화")

        # Range 헤더 설정
        headers = {}
        if resume_supported and initial_downloaded_size > 0:
            headers["Range"] = f"bytes={initial_downloaded_size}-"
            print(f"[LOG] 이어받기 요청 헤더: {headers}")
        else:
            if initial_downloaded_size > 0:
                print(f"[LOG] 이어받기 실패. 처음부터 다시 다운로드")
                initial_downloaded_size = 0
                file_path = part_file_path  # .part 파일로 다시 시작
        
        # 개선된 다운로드 헤더
        download_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site',
        }
        
        # Range 헤더 추가 (이어받기용)
        if resume_supported and initial_downloaded_size > 0:
            download_headers["Range"] = f"bytes={initial_downloaded_size}-"
            print(f"[LOG] 이어받기 요청 헤더: Range={download_headers['Range']}")

        # 실제 다운로드 요청 with 프록시 순환
        r = None
        range_was_removed = False
        
        if use_proxy and available_proxies:
            # 남은 사용 가능한 프록시들로 다운로드 시도
            remaining_proxies = get_unused_proxies(db)
            print(f"[LOG] 다운로드용 남은 프록시: {len(remaining_proxies)}개")
            
            for i, proxy_addr in enumerate(remaining_proxies):
                # 다운로드 프록시 순환 시 상태 체크 (주요 중단점)
                db.refresh(req)
                if req.status == StatusEnum.stopped:
                    print(f"[LOG] 프록시 다운로드 중 정지 요청 감지. 중단합니다.")
                    cleanup_incomplete_file(file_path, is_complete=False)
                    return
                
                try:
                    print(f"[LOG] 다운로드 - 프록시 {i+1}/{len(remaining_proxies)} 시도: {proxy_addr}")
                    
                    # 프록시 시도 중 상태 WebSocket 전송
                    try:
                        import json
                        status_queue.put(json.dumps({
                            "type": "proxy_trying", 
                            "data": {
                                "proxy": proxy_addr,
                                "step": "downloading",
                                "current": i+1,
                                "total": len(remaining_proxies)
                            }
                        }, ensure_ascii=False))
                    except:
                        pass
                    
                    current_proxies = {
                        'http': f'http://{proxy_addr}',
                        'https': f'http://{proxy_addr}'
                    }
                    
                    # 다운로드 시도
                    
                    r, range_was_removed = simple_download(str(direct_link), download_headers, current_proxies)
                    
                    # 다운로드 성공 시 완료
                    
                    # 성공하면 프록시 기록하고 중단
                    # mark_proxy_used(db, proxy_addr, success=True)  # 중복 기록 방지: 다운로드 완료 시에만 기록
                    download_proxies = current_proxies
                    used_proxy_addr = proxy_addr
                    print(f"[LOG] 다운로드 성공 - 프록시: {proxy_addr}")
                    
                    # 프록시 성공 상태 WebSocket 전송
                    try:
                        status_queue.put(json.dumps({
                            "type": "proxy_success", 
                            "data": {
                                "proxy": proxy_addr,
                                "step": "downloading"
                            }
                        }, ensure_ascii=False))
                    except:
                        pass
                    break
                    
                except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout, 
                        requests.exceptions.Timeout, requests.exceptions.ProxyError) as e:
                    print(f"[LOG] 다운로드 실패 - 프록시 {proxy_addr}: {e}")
                    # mark_proxy_used(db, proxy_addr, success=False)  # 중복 기록 방지
                    
                    # 예외 발생 시 다음 프록시로
                    
                    # 프록시 실패 상태 WebSocket 전송
                    try:
                        status_queue.put(json.dumps({
                            "type": "proxy_failed", 
                            "data": {
                                "proxy": proxy_addr,
                                "step": "downloading",
                                "error": str(e)
                            }
                        }, ensure_ascii=False))
                    except:
                        pass
                    continue
                    
                except Exception as e:
                    print(f"[LOG] 다운로드 오류 - 프록시 {proxy_addr}: {e}")
                    # mark_proxy_used(db, proxy_addr, success=False)  # 중복 기록 방지
                    
                    # 프록시 실패 상태 WebSocket 전송
                    try:
                        status_queue.put(json.dumps({
                            "type": "proxy_failed", 
                            "data": {
                                "proxy": proxy_addr,
                                "step": "downloading",
                                "error": str(e)
                            }
                        }, ensure_ascii=False))
                    except:
                        pass
                    continue
            
            # 모든 프록시 실패한 경우
            if r is None:
                print(f"[LOG] 모든 프록시 실패. 로컬로 다운로드 시도")
                r, range_was_removed = simple_download(str(direct_link), download_headers, None)
        else:
            # 프록시 없이 다운로드
            print(f"[LOG] 로컬 다운로드 시도")
            r, range_was_removed = simple_download(str(direct_link), download_headers, download_proxies)
        
        # 409 에러로 인해 Range 헤더가 제거되었는지 확인
        if range_was_removed:
            print(f"[LOG] 409 에러로 인해 Range 헤더가 제거됨. 전체 다운로드로 변경")
            initial_downloaded_size = 0
            file_path = part_file_path  # .part 파일로 변경
            resume_supported = False
            # 기존 .part 파일이 있으면 삭제 (처음부터 다시 시작)
            if file_path.exists():
                print(f"[LOG] 기존 .part 파일 삭제: {file_path}")
                file_path.unlink()
        
        with r:
            print(f"[LOG] HTTP GET request sent for {req.id}. Status code: {r.status_code}")
            print(f"[LOG] Response headers: {r.headers}")
            print(f"[LOG] Content-Length header: {r.headers.get('Content-Length')}")
            print(f"[LOG] Content-Range header: {r.headers.get('Content-Range')}")
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
            if "Content-Range" in r.headers:
                # Parse Content-Range: bytes 200-1000/1001
                content_range = r.headers["Content-Range"]
                match = re.search(r"bytes \d+-\d+/(\d+)", content_range)
                if match:
                    total_size = int(match.group(1))
                    print(f"[LOG] Range 응답에서 전체 파일 크기: {total_size}")
            elif "Content-Length" in r.headers:
                content_length = int(r.headers["Content-Length"])
                if initial_downloaded_size > 0:
                    # 이어받기인 경우 전체 크기는 기존 + 추가로 받을 크기
                    total_size = initial_downloaded_size + content_length
                    print(f"[LOG] 이어받기: 기존 {initial_downloaded_size} + 추가 {content_length} = 전체 {total_size}")
                else:
                    # 새 다운로드인 경우
                    total_size = content_length
                    print(f"[LOG] 새 다운로드 전체 크기: {total_size}")
            
            # 서버에서 받은 파일 크기가 있으면 우선 사용
            if server_file_size and server_file_size > total_size:
                total_size = server_file_size
                print(f"[LOG] HEAD 요청에서 받은 파일 크기 사용: {total_size}")

            downloaded_size = initial_downloaded_size

            setattr(req, "total_size", total_size)
            db.commit()
            notify_status_update(db, int(getattr(req, 'id')), lang) # Call notify_status_update here
            print(f"[LOG] DB file_name and total_size updated for {req.id}")

            # Open file in append mode if resuming, else write mode
            mode = "ab" if initial_downloaded_size > 0 and resume_supported else "wb"
            print(f"[LOG] Opening file in mode: {mode} (resume_supported: {resume_supported})")
            
            # 처음부터 다시 다운로드하는 경우 기존 파일 삭제
            if mode == "wb" and file_path.exists():
                print(f"[LOG] 기존 파일 삭제 후 새로 시작: {file_path}")
                file_path.unlink()
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
                    
                    # DB 체크는 프록시 순환할 때만 (성능 향상)
                    
                    # 상세 로깅은 가끔만 (성능을 위해)
                    should_log_status = (
                        current_time - last_status_check >= status_check_interval or
                        chunk_count % 128 == 0  # 1MB마다
                    )
                    
                    if should_log_status:
                        print(f"[LOG] Download {req.id} status: {req.status}, chunk: {chunk_count}")
                        last_status_check = current_time
                    
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
        
        # 다운로드 완료 시 .part 확장자 제거
        cleanup_incomplete_file(file_path, is_complete=True)
        
        # 프록시 사용 성공 기록
        if used_proxy_addr:
            mark_proxy_used(db, used_proxy_addr, True)
            print(f"[LOG] 프록시 {used_proxy_addr} 다운로드 성공 기록됨")
        
        try:
            print(f"[LOG] Download completed: {req.url}")
        except UnicodeEncodeError:
            print(f"[LOG] Download completed: (encoding error)")

    except requests.exceptions.RequestException as e:
        error_message = f"Network or HTTP error: {e}"
        # Clean error message to prevent encoding issues
        error_message = error_message.encode('ascii', 'ignore').decode('ascii')
        try:
            print(f"[LOG] Download {request_id} failed due to RequestException: {error_message}")
        except UnicodeEncodeError:
            print(f"[LOG] Download {request_id} failed due to RequestException: (encoding error)")
        # 프록시 사용 실패 기록 (최종 실패만 기록)
        if used_proxy_addr:
            mark_proxy_used(db, used_proxy_addr, False)
            print(f"[LOG] 프록시 {used_proxy_addr} 다운로드 최종 실패 기록됨")
        
        if req: # Ensure req is defined before accessing its attributes
            setattr(req, "status", StatusEnum.failed)
            setattr(req, "error", error_message)
            db.commit()
            notify_status_update(db, int(getattr(req, 'id')), lang)
            
            # 실패한 다운로드 파일 정리
            if 'file_path' in locals():
                cleanup_incomplete_file(file_path, is_complete=False)
        else:
            print(f"[LOG] Critical: req was None when RequestException occurred for download_id {request_id}")
    except TimeoutError as e:
        error_message = f"Download timed out: {str(e)}"
        # Clean error message to prevent encoding issues
        error_message = error_message.encode('ascii', 'ignore').decode('ascii')
        try:
            print(f"[LOG] Download {request_id} failed due to TimeoutError: {error_message}")
        except UnicodeEncodeError:
            print(f"[LOG] Download {request_id} failed due to TimeoutError: (encoding error)")
        # 프록시 사용 실패 기록 (최종 실패만 기록)
        if used_proxy_addr:
            mark_proxy_used(db, used_proxy_addr, False)
            print(f"[LOG] 프록시 {used_proxy_addr} 타임아웃 최종 실패 기록됨")
        
        if req: # Ensure req is defined before accessing its attributes
            setattr(req, "status", StatusEnum.failed)
            setattr(req, "error", error_message)
            db.commit()
            notify_status_update(db, int(getattr(req, 'id')), lang)
            
            # 타임아웃된 다운로드 파일 정리
            if 'file_path' in locals():
                cleanup_incomplete_file(file_path, is_complete=False)
        else:
            print(f"[LOG] Critical: req was None when TimeoutError occurred for download_id {request_id}")
    except Exception as e:
        error_message = str(e)
        # Clean error message to prevent encoding issues
        error_message = error_message.encode('ascii', 'ignore').decode('ascii')
        try:
            print(f"[LOG] Download {request_id} failed due to general Exception: {error_message}")
        except UnicodeEncodeError:
            print(f"[LOG] Download {request_id} failed due to general Exception: (encoding error)")
        
        # 프록시 사용 실패 기록 (최종 실패만 기록)
        if used_proxy_addr:
            mark_proxy_used(db, used_proxy_addr, False)
            print(f"[LOG] 프록시 {used_proxy_addr} 일반 에러 최종 실패 기록됨")
        
        if req: # Ensure req is defined before accessing its attributes
            setattr(req, "status", StatusEnum.failed)
            setattr(req, "error", error_message)
            db.commit()
            notify_status_update(db, int(getattr(req, 'id')), lang)
            
            # 일반 예외로 실패한 다운로드 파일 정리
            if 'file_path' in locals():
                cleanup_incomplete_file(file_path, is_complete=False)
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
    """폴더 선택 대화상자를 열고 선택된 경로를 반환"""
    import os
    import platform
    import threading
    import asyncio
    
    # 기본 다운로드 폴더
    if platform.system() == "Windows":
        downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
    else:
        downloads_path = os.path.join(os.path.expanduser("~"), "Downloads")
    
    def open_folder_dialog():
        """별도 스레드에서 폴더 선택 대화상자 실행"""
        if not GUI_AVAILABLE:
            print("[INFO] GUI not available in this environment, using default downloads path")
            return downloads_path
            
        try:
            root = tk.Tk()
            root.withdraw()
            root.wm_attributes('-topmost', 1)
            folder_path = filedialog.askdirectory(
                title="다운로드 폴더 선택",
                initialdir=downloads_path
            )
            root.destroy()
            return folder_path if folder_path else downloads_path
        except Exception as e:
            print(f"[ERROR] tkinter folder dialog failed: {e}")
            return downloads_path
    
    try:
        # 별도 스레드에서 실행하여 서버 블로킹 방지
        loop = asyncio.get_event_loop()
        selected_path = await loop.run_in_executor(None, open_folder_dialog)
        return {"path": selected_path}
    except Exception as e:
        print(f"[ERROR] Folder selection error: {e}")
        return {"path": downloads_path}

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
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            simple_response = requests.get(url, headers=headers, timeout=3, verify=False)
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
            import ssl
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            r = scraper.post(url, data=payload, headers=headers, timeout=3, verify=False)
            debug_info["steps"].append(f"cloudscraper POST 요청: {r.status_code}")
            print(f"[DEBUG] cloudscraper POST 응답: {r.status_code}")
            
            if r.status_code in [200, 500]:  # HTTP 500도 HTML 응답이 있으면 처리
                if r.status_code == 500:
                    debug_info["steps"].append(f"HTTP 500 오류지만 HTML 응답 있음, 파싱 시도")
                
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
                    debug_info["steps"].append(f"다운로드 링크 발견: {direct_link}")
                    print(f"[DEBUG] 다운로드 링크 발견: {direct_link}")
                    
                    # 파일 정보 추출
                    file_info = fichier_parser.extract_file_info(r.text)
                    debug_info["file_info"] = file_info
                    debug_info["steps"].append(f"파일 정보: {file_info}")
                else:
                    debug_info["steps"].append("파서에서 다운로드 링크를 찾지 못함")
                    print(f"[DEBUG] 파서에서 다운로드 링크를 찾지 못함")
                    
                    # HTML에서 모든 링크 추출해서 디버깅
                    import lxml.html
                    doc = lxml.html.fromstring(r.text)
                    all_links = [a.get('href') for a in doc.xpath('//a[@href]') if a.get('href')]
                    debug_info["all_links"] = all_links[:20]  # 처음 20개만
                    debug_info["steps"].append(f"페이지의 모든 링크 (처음 20개): {all_links[:20]}")
            else:
                debug_info["steps"].append(f"HTTP 오류: {r.status_code}")
                debug_info["error"] = f"HTTP {r.status_code}"
                
        except Exception as e:
            debug_info["steps"].append(f"cloudscraper 요청 실패: {str(e)}")
            debug_info["error"] = str(e)
            print(f"[DEBUG] cloudscraper 요청 실패: {e}")
        
        return debug_info
        
    except Exception as e:
        print(f"[DEBUG] 전체 파싱 테스트 오류: {e}")
        debug_info["error"] = str(e)
        debug_info["steps"].append(f"전체 테스트 실패: {str(e)}")
        return debug_info

@api_router.post("/debug/parse-fixed")
def debug_parse_fixed(data: dict = Body(...)):
    """1fichier 링크 파싱 (SSL 문제 해결된 버전)"""
    
    url = data.get("url")
    password = data.get("password")
    
    if not url:
        raise HTTPException(status_code=400, detail="URL이 필요합니다")
    
    result = {
        "url": url,
        "steps": [],
        "success": False,
        "direct_link": None,
        "error": None
    }
    
    try:
        result["steps"].append(f"파싱 시작: {url}")
        
        # SSL 경고 비활성화
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        # 기본 requests로 시도
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        }
        
        response = requests.get(url, headers=headers, timeout=3, verify=False)
        result["steps"].append(f"GET 요청: {response.status_code}")
        
        if response.status_code in [200, 500]:  # HTTP 500도 허용
            if response.status_code == 500:
                result["steps"].append("HTTP 500이지만 HTML 응답 있음, 계속 진행")
            
            # HTML 파싱 시도
            from core.parser import fichier_parser
            
            # 60초 대기 시뮬레이션 (실제로는 5초만)
            import time
            result["steps"].append("5초 대기 중...")
            time.sleep(5)
            
            # POST 요청
            post_data = {'dl_no_ssl': 'on', 'dlinline': 'on'}
            if password:
                post_data['pass'] = password
            
            headers['Referer'] = url
            post_response = requests.post(url, data=post_data, headers=headers, timeout=3, verify=False)
            result["steps"].append(f"POST 요청: {post_response.status_code}")
            
            if post_response.status_code in [200, 500]:
                if post_response.status_code == 500:
                    result["steps"].append("POST HTTP 500이지만 HTML 응답 있음, 파싱 시도")
                
                # 파서로 링크 추출
                direct_link = fichier_parser.parse_download_link(post_response.text, str(url))
                
                if direct_link and direct_link != str(url):
                    result["success"] = True
                    result["direct_link"] = direct_link
                    result["steps"].append(f"다운로드 링크 발견: {direct_link}")
                    
                    # 파일 정보 추출
                    file_info = fichier_parser.extract_file_info(post_response.text)
                    result["file_info"] = file_info
                    
                else:
                    result["steps"].append("파서에서 다운로드 링크를 찾지 못함")
                    
                    # 디버깅을 위해 모든 링크 표시
                    import re
                    all_links = re.findall(r'href=["\']([^"\']+)["\']', post_response.text)
                    external_links = [link for link in all_links if link.startswith('http')][:10]
                    result["all_links"] = external_links
                    result["steps"].append(f"발견된 외부 링크: {len(external_links)}개")
            else:
                result["error"] = f"POST 실패: {post_response.status_code}"
        else:
            result["error"] = f"GET 실패: {response.status_code}"
            
    except Exception as e:
        result["error"] = str(e)
        result["steps"].append(f"오류 발생: {str(e)}")
    
    return result

@api_router.post("/debug/simple-test")
def simple_connection_test():
    """간단한 연결 테스트"""
    test_results = {}
    
    # 1. 기본 HTTP 연결 테스트
    try:
        import requests
        response = requests.get("https://1fichier.com", timeout=3)
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
        response = scraper.get("https://1fichier.com", timeout=3)
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

# Resume download endpoint
@api_router.post("/resume/{download_id}")
async def resume_download(download_id: int, use_proxy: bool = True, db: Session = Depends(get_db)):
    """다운로드 재시작"""
    try:
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드를 찾을 수 없습니다")
        
        if req.status not in [StatusEnum.stopped, StatusEnum.failed]:
            raise HTTPException(status_code=400, detail="정지 또는 실패 상태의 다운로드만 재시작할 수 있습니다")
        
        # 프록시 설정 업데이트
        req.use_proxy = use_proxy
        req.status = StatusEnum.downloading
        req.error = None
        db.commit()
        
        print(f"[LOG] 다운로드 재시작 요청: ID={download_id}, use_proxy={use_proxy}")
        
        # 다운로드 스레드 시작
        download_manager.start_download(
            download_id,
            download_with_proxy_rotation,
            download_id,
            db,
            force_reparse=False
        )
        
        # 상태 업데이트 알림
        notify_status_update(db, download_id)
        
        return {"message": "다운로드가 재시작되었습니다", "download_id": download_id}
        
    except Exception as e:
        print(f"[ERROR] 다운로드 재시작 실패: {e}")
        raise HTTPException(status_code=500, detail=f"다운로드 재시작 실패: {str(e)}")

# Retry download endpoint
@api_router.post("/retry/{download_id}")
async def retry_download(download_id: int, db: Session = Depends(get_db)):
    """다운로드 재시도 (링크 재파싱)"""
    try:
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드를 찾을 수 없습니다")
        
        # 상태를 downloading으로 변경
        req.status = StatusEnum.downloading
        req.error = None
        req.direct_link = None  # 링크 재파싱을 위해 초기화
        db.commit()
        
        print(f"[LOG] 다운로드 재시도 요청: ID={download_id} (링크 재파싱)")
        
        # 다운로드 스레드 시작 (강제 재파싱)
        download_manager.start_download(
            download_id,
            download_with_proxy_rotation,
            download_id,
            db,
            force_reparse=True
        )
        
        # 상태 업데이트 알림
        notify_status_update(db, download_id)
        
        return {"message": "다운로드 재시도가 시작되었습니다", "download_id": download_id}
        
    except Exception as e:
        print(f"[ERROR] 다운로드 재시도 실패: {e}")
        raise HTTPException(status_code=500, detail=f"다운로드 재시도 실패: {str(e)}")

# Pause download endpoint
@api_router.post("/pause/{download_id}")
async def pause_download(download_id: int, db: Session = Depends(get_db)):
    """다운로드 정지"""
    try:
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드를 찾을 수 없습니다")
        
        if req.status not in [StatusEnum.downloading, StatusEnum.proxying]:
            raise HTTPException(status_code=400, detail="진행 중인 다운로드만 정지할 수 있습니다")
        
        # 상태를 stopped로 변경
        req.status = StatusEnum.stopped
        db.commit()
        
        print(f"[LOG] 다운로드 정지 요청: ID={download_id}")
        
        # 다운로드 매니저에서 해당 다운로드 강제 제거
        if download_manager.is_download_active(download_id):
            download_manager.cancel_download(download_id)
            print(f"[LOG] 다운로드 {download_id} 스레드를 매니저에서 제거")
        
        # 상태 업데이트 알림  
        notify_status_update(db, download_id)
        
        return {"message": "다운로드가 정지되었습니다", "download_id": download_id}
        
    except Exception as e:
        print(f"[ERROR] 다운로드 정지 실패: {e}")
        raise HTTPException(status_code=500, detail=f"다운로드 정지 실패: {str(e)}")

app.include_router(api_router)
app.include_router(proxy_stats_router, prefix="/api")

# Catch-all route for SPA routing (정적 파일보다 먼저 정의)
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # 정적 파일인지 확인
    file_path = os.path.join(frontend_dist_path, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    # SPA 라우팅을 위해 index.html 반환
    return FileResponse(os.path.join(frontend_dist_path, "index.html"))

# Serve static files from the dist directory
app.mount("/static", StaticFiles(directory=frontend_dist_path), name="static")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
