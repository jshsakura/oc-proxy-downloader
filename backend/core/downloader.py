# -*- coding: utf-8 -*-
import sys
import os

# UTF-8 인코딩 강제 설정
if sys.platform.startswith('win'):
    try:
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, HttpUrl
from core.models import DownloadRequest, Base, StatusEnum
from core.db import engine, get_db
from core.i18n import get_message
import json
import os
import re
import time

# 테이블 생성은 main.py에서 처리

# 기존 'paused' 상태를 'stopped'로 마이그레이션
try:
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text("UPDATE download_requests SET status = 'stopped' WHERE status = 'paused'"))
        conn.commit()
        if result.rowcount > 0:
            print(f"[LOG] {result.rowcount}개의 'paused' 레코드를 'stopped'로 변경")
except Exception as e:
    print(f"[LOG] 상태 마이그레이션 실패: {e}")

router = APIRouter()

class DownloadRequestCreate(BaseModel):
    url: HttpUrl
    password: str = ""
    use_proxy: bool = True
    file_name: str = None  # 재다운로드시 기존 파일명 전달용

@router.post("/download/")
def create_download_task(request: DownloadRequestCreate, db: Session = Depends(get_db)):
    # 로그 파일에도 기록 (도커 환경을 위해 /tmp 경로 사용)
    try:
        import os
        log_path = "/tmp/debug.log" if os.path.exists("/tmp") else "debug.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] API CALLED: {request.url}\n")
            f.flush()
    except PermissionError:
        # 권한 없으면 그냥 콘솔에만 출력
        print(f"[{time.strftime('%H:%M:%S')}] API CALLED: {request.url}")
    
    print("="*80)
    print("[LOG] *** CREATE DOWNLOAD TASK API CALLED ***")
    print(f"[LOG] URL: {request.url}")
    print(f"[LOG] Use Proxy: {request.use_proxy}")
    print("="*80)
    import sys
    sys.stdout.flush()  # 즉시 출력 강제
    
    # URL 형식 기본 검증
    url_str = str(request.url)
    if not url_str.startswith('https://1fichier.com/'):
        print(f"[LOG] 경고: 표준 1fichier URL 형식이 아님: {url_str}")
        # 에러는 발생시키지 않고 계속 진행 (다른 도메인일 수도 있음)
    
    db_req = DownloadRequest(
        url=str(request.url),
        status=StatusEnum.pending,
        password=request.password,
        use_proxy=request.use_proxy
    )
    db.add(db_req)
    db.commit()
    db.refresh(db_req)
    
    # 새로운 다운로드 시스템 사용
    print(f"[LOG] 데이터베이스에 저장된 요청 ID: {db_req.id}")
    print(f"[LOG] 다운로드 스레드 시작 준비")
    
    from .download_core import download_1fichier_file_new
    from .shared import download_manager
    import threading
    
    # 다운로드 제한 체크 (전체 5개 + 1fichier 2개)
    if not request.use_proxy:
        if not download_manager.can_start_download(str(request.url)):
            # 대기 상태로 설정
            db_req.status = StatusEnum.pending
            db.commit()
            
            # 어떤 제한인지 확인
            if len(download_manager.all_downloads) >= download_manager.MAX_TOTAL_DOWNLOADS:
                print(f"[LOG] 전체 다운로드 제한 도달 ({download_manager.MAX_TOTAL_DOWNLOADS}개). 대기 상태로 설정: {db_req.id}")
                return {"id": db_req.id, "status": "waiting", "message": f"전체 다운로드 제한 도달 ({download_manager.MAX_TOTAL_DOWNLOADS}개). 대기 중..."}
            else:
                print(f"[LOG] 1fichier 로컬 다운로드 제한 도달 ({download_manager.MAX_LOCAL_DOWNLOADS}개). 대기 상태로 설정: {db_req.id}")
                return {"id": db_req.id, "status": "waiting", "message": f"1fichier 로컬 다운로드 제한 도달 ({download_manager.MAX_LOCAL_DOWNLOADS}개). 대기 중..."}
    
    thread = threading.Thread(
        target=download_1fichier_file_new,
        args=(db_req.id, "ko", request.use_proxy),
        daemon=True
    )
    print(f"[LOG] 스레드 시작 중...")
    thread.start()
    print(f"[LOG] 스레드 시작 완료: {thread.is_alive()}")
    
    return {"id": db_req.id, "status": db_req.status}

@router.get("/history/")
def get_download_history(db: Session = Depends(get_db)):
    try:
        history = db.query(DownloadRequest).order_by(DownloadRequest.requested_at.desc()).all()
        print(f"[LOG] History API: Found {len(history)} records")
        result = [item.as_dict() for item in history]
        print(f"[LOG] History API: Returning {len(result)} items")
        if result:
            print(f"[LOG] First item: {result[0]}")
        return result
    except Exception as e:
        print(f"[ERROR] History API failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {str(e)}")

@router.get("/history/{download_id}")
def get_download_detail(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    return item.as_dict()

@router.post("/resume/{download_id}")
def resume_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    # stopped 또는 pending 상태인 경우 재개/시작
    if getattr(item, 'status', None) in [StatusEnum.stopped, StatusEnum.pending]:
        setattr(item, "status", StatusEnum.downloading)
        db.commit()
        
        # 새로운 다운로드 시스템으로 재시작
        from .download_core import download_1fichier_file_new
        import threading
        
        # 원래 프록시 설정 사용 (기본값 없이)
        original_use_proxy = getattr(item, 'use_proxy', None)
        if original_use_proxy is None:
            # DB에 use_proxy가 없는 경우 (구버전 호환) - 기본값 False (로컬)
            original_use_proxy = False
            print(f"[LOG] use_proxy 설정이 없어 기본값 False(로컬) 사용: ID {download_id}")
        else:
            print(f"[LOG] 원래 프록시 설정 사용: use_proxy={original_use_proxy}, ID {download_id}")
        
        thread = threading.Thread(
            target=download_1fichier_file_new,
            args=(download_id, "ko", original_use_proxy),
            daemon=True
        )
        thread.start()
        
        return {"id": item.id, "status": item.status, "message": "Download resumed"}
    else:
        raise HTTPException(status_code=400, detail="Download is not in a stopped or pending state")

@router.delete("/delete/{download_id}")
def delete_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    print(f"[LOG] 다운로드 삭제 요청: ID {download_id}, 현재 상태: {item.status}")
    
    # 다운로드 중인 경우 먼저 정지
    if item.status in [StatusEnum.downloading, StatusEnum.proxying]:
        print(f"[LOG] 다운로드 중이므로 먼저 정지: ID {download_id}")
        setattr(item, "status", StatusEnum.stopped)
        db.commit()
        
        # 잠시 대기 (다운로드 함수가 정지를 감지할 시간)
        import time
        time.sleep(1)
    
    # DB에서 삭제
    db.delete(item)
    db.commit()
    
    print(f"[LOG] 다운로드 삭제 완료: ID {download_id}")
    
    return {"message": "Download deleted successfully"}

@router.post("/pause/{download_id}")
def pause_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    print(f"[LOG] 다운로드 정지 요청: ID {download_id}")
    
    # 상태를 stopped로 변경
    setattr(item, "status", StatusEnum.stopped)
    db.commit()
    
    print(f"[LOG] 다운로드 상태를 stopped로 변경 완료: ID {download_id}")
    
    return {"id": item.id, "status": item.status}

@router.post("/retry/{download_id}")
def retry_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    # 상태를 downloading으로 변경하고 에러 초기화, direct_link도 초기화
    setattr(item, "status", StatusEnum.downloading)
    setattr(item, "error", None)
    setattr(item, "direct_link", None)  # 재시도 시 새로운 링크 파싱 강제
    db.commit()
    
    # 새로운 다운로드 시스템으로 재시도
    from .download_core import download_1fichier_file_new
    import threading
    
    # 원래 프록시 설정 사용 (기본값 없이)
    original_use_proxy = getattr(item, 'use_proxy', None)
    if original_use_proxy is None:
        # DB에 use_proxy가 없는 경우 (구버전 호환) - 기본값 False (로컬)
        original_use_proxy = False
        print(f"[LOG] retry에서 use_proxy 설정이 없어 기본값 False(로컬) 사용: ID {download_id}")
    else:
        print(f"[LOG] retry에서 원래 프록시 설정 사용: use_proxy={original_use_proxy}, ID {download_id}")
    
    thread = threading.Thread(
        target=download_1fichier_file_new,
        args=(download_id, "ko", original_use_proxy),
        daemon=True
    )
    thread.start()
    
    return {"id": item.id, "status": item.status, "message": "Download retry started"}

