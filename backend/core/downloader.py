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
from core.auth import get_current_user_optional, AUTHENTICATION_ENABLED
from typing import Dict, Any
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

@router.post("/parse-info/")
def parse_file_info_only(request: DownloadRequestCreate, db: Session = Depends(get_db)):
    """파일 정보만 파싱하고 대기 상태로 설정"""
    try:
        # 로그 파일에도 기록
        try:
            import os
            log_path = "/tmp/debug.log" if os.path.exists("/tmp") else "debug.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] PARSE INFO API CALLED: {request.url}\n")
                f.flush()
        except PermissionError:
            print(f"[{time.strftime('%H:%M:%S')}] PARSE INFO API CALLED: {request.url}")
        
        print("="*80)
        print("[LOG] *** PARSE FILE INFO API CALLED ***")
        print(f"[LOG] URL: {request.url}")
        print(f"[LOG] Use Proxy: {request.use_proxy}")
        print("="*80)
        
        # DB에 요청 저장 (waiting 상태로)
        db_req = DownloadRequest(
            url=str(request.url),
            status=StatusEnum.pending,  # 대기 상태로 설정
            password=request.password,
            use_proxy=request.use_proxy
        )
        db.add(db_req)
        db.commit()
        db.refresh(db_req)
        
        print(f"[LOG] 파일 정보 파싱 요청 생성: ID {db_req.id}")
        
        # 파일 정보 파싱
        from .parser_service import parse_direct_link_with_file_info
        
        try:
            print(f"[LOG] 파일 정보 파싱 시작...")
            direct_link, file_info = parse_direct_link_with_file_info(
                str(request.url),
                request.password,
                use_proxy=request.use_proxy
            )
            
            # 파일 정보 업데이트
            if file_info and file_info.get('name'):
                db_req.file_name = file_info['name']
                print(f"[LOG] 파일명 추출: {file_info['name']}")
            
            if file_info and file_info.get('size'):
                # 크기를 바이트로 변환해서 저장
                size_str = file_info['size']
                try:
                    import re
                    match = re.search(r'(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)', size_str, re.IGNORECASE)
                    if match:
                        value = float(match.group(1))
                        unit = match.group(2).upper()
                        
                        multipliers = {'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
                        if unit in multipliers:
                            total_bytes = int(value * multipliers[unit])
                            db_req.total_size = total_bytes
                            print(f"[LOG] 파일 크기 추출: {size_str} ({total_bytes} bytes)")
                except Exception as e:
                    print(f"[LOG] 파일 크기 파싱 실패: {e}")
            
            # direct_link도 저장 (나중에 다운로드할 때 사용)
            if direct_link:
                db_req.direct_link = direct_link
                print(f"[LOG] Direct link 저장됨")
            
            db.commit()
            
            return {
                "id": db_req.id, 
                "status": "parsed",
                "file_name": db_req.file_name or "Unknown",
                "file_size": file_info.get('size') if file_info else None,
                "message": "File info parsed successfully, ready to download"
            }
            
        except Exception as parse_error:
            print(f"[ERROR] 파일 정보 파싱 실패: {parse_error}")
            db_req.error = f"파싱 실패: {str(parse_error)}"
            db_req.status = StatusEnum.failed
            db.commit()
            
            return {
                "id": db_req.id,
                "status": "failed",
                "error": str(parse_error)
            }
            
    except Exception as e:
        print(f"[ERROR] Parse info API 실패: {e}")
        return {
            "error": str(e),
            "status": "failed"
        }

@router.post("/download/")
def create_download_task(
    request: DownloadRequestCreate, 
    db: Session = Depends(get_db),
    user: Dict[str, Any] = Depends(get_current_user_optional)
):
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
                return {"id": db_req.id, "status": "waiting", "message_key": "total_download_limit_reached", "message_args": {"limit": download_manager.MAX_TOTAL_DOWNLOADS}}
            elif len(download_manager.local_downloads) >= download_manager.MAX_LOCAL_DOWNLOADS:
                print(f"[LOG] 1fichier 로컬 다운로드 제한 도달 ({download_manager.MAX_LOCAL_DOWNLOADS}개). 대기 상태로 설정: {db_req.id}")
                return {"id": db_req.id, "status": "waiting", "message_key": "local_download_limit_reached", "message_args": {"limit": download_manager.MAX_LOCAL_DOWNLOADS}}
            else:
                # 쿨다운 제한인 경우
                cooldown_remaining = download_manager.get_1fichier_cooldown_remaining()
                print(f"[LOG] 1fichier 쿨다운 중 ({cooldown_remaining:.1f}초 남음). 대기 상태로 설정: {db_req.id}")
                return {"id": db_req.id, "status": "waiting", "message_key": "fichier_cooldown_active", "message_args": {"seconds": int(cooldown_remaining)}}
    
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

@router.post("/start-download/{download_id}")
def start_actual_download(download_id: int, db: Session = Depends(get_db)):
    """파싱된 파일의 실제 다운로드 시작"""
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    # pending 상태에서만 다운로드 시작 가능
    if getattr(item, 'status', None) != StatusEnum.pending:
        raise HTTPException(status_code=400, detail=f"Download is not in pending state. Current status: {item.status}")
    
    print(f"[LOG] 실제 다운로드 시작: ID {download_id}, 파일명: {item.file_name}")
    
    # 다운로드 제한 체크
    from .shared import download_manager
    original_use_proxy = getattr(item, 'use_proxy', False)
    
    # 다운로드 제한 체크 (프록시 사용 여부와 관계없이 모든 다운로드에서 체크)
    if not download_manager.can_start_download(item.url):
        # 대기 상태 유지 (다운로드 제한이나 쿨다운 때문에 시작할 수 없음)
        setattr(item, "status", StatusEnum.pending)
        db.commit()
        return {"id": item.id, "status": "waiting", "message": "Download limit reached, staying in queue"}
    
    # 다운로드 시작
    setattr(item, "status", StatusEnum.downloading)
    db.commit()
    
    # 새로운 다운로드 시스템으로 시작
    from .download_core import download_1fichier_file_new
    import threading
    
    thread = threading.Thread(
        target=download_1fichier_file_new,
        args=(download_id, "ko", original_use_proxy),
        daemon=True
    )
    thread.start()
    
    return {"id": item.id, "status": item.status, "message": "Download started"}

@router.post("/resume/{download_id}")
def resume_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    # stopped 또는 pending 상태인 경우 재개/시작
    if getattr(item, 'status', None) in [StatusEnum.stopped, StatusEnum.pending]:
        print(f"[LOG] 다운로드 재개 요청: ID {download_id}, 현재 상태: {item.status}")
        
        # 원래 프록시 설정 사용 (기본값 없이)
        original_use_proxy = getattr(item, 'use_proxy', None)
        if original_use_proxy is None:
            # DB에 use_proxy가 없는 경우 (구버전 호환) - 기본값 False (로컬)
            original_use_proxy = False
            print(f"[LOG] use_proxy 설정이 없어 기본값 False(로컬) 사용: ID {download_id}")
        else:
            print(f"[LOG] 원래 프록시 설정 사용: use_proxy={original_use_proxy}, ID {download_id}")
        
        # 로컬 다운로드인 경우 다운로드 제한 체크
        if not original_use_proxy:
            from .shared import download_manager
            if not download_manager.can_start_download(item.url):
                # 대기 상태로 설정
                setattr(item, "status", StatusEnum.pending)
                db.commit()
                
                # WebSocket으로 상태 업데이트 알림 (대기 상태)
                from main import notify_status_update
                notify_status_update(db, download_id)
                
                # 어떤 제한인지 확인
                if len(download_manager.all_downloads) >= download_manager.MAX_TOTAL_DOWNLOADS:
                    print(f"[LOG] 재개 - 전체 다운로드 제한 도달 ({download_manager.MAX_TOTAL_DOWNLOADS}개). 대기 상태로 설정: {download_id}")
                    return {"id": item.id, "status": "waiting", "message_key": "total_download_limit_reached", "message_args": {"limit": download_manager.MAX_TOTAL_DOWNLOADS}}
                elif len(download_manager.local_downloads) >= download_manager.MAX_LOCAL_DOWNLOADS:
                    print(f"[LOG] 재개 - 1fichier 로컬 다운로드 제한 도달 ({download_manager.MAX_LOCAL_DOWNLOADS}개). 대기 상태로 설정: {download_id}")
                    return {"id": item.id, "status": "waiting", "message_key": "local_download_limit_reached", "message_args": {"limit": download_manager.MAX_LOCAL_DOWNLOADS}}
                else:
                    # 쿨다운 제한인 경우
                    cooldown_remaining = download_manager.get_1fichier_cooldown_remaining()
                    print(f"[LOG] 재개 - 1fichier 쿨다운 중 ({cooldown_remaining:.1f}초 남음). 대기 상태로 설정: {download_id}")
                    return {"id": item.id, "status": "waiting", "message_key": "fichier_cooldown_active", "message_args": {"seconds": int(cooldown_remaining)}}
        
        # 제한에 걸리지 않은 경우 즉시 시작
        setattr(item, "status", StatusEnum.downloading)
        db.commit()
        
        # WebSocket으로 상태 업데이트 알림 (다운로드 시작)
        from main import notify_status_update
        notify_status_update(db, download_id)
        print(f"[LOG] ★ 재개 WebSocket 알림 전송 완료: ID={download_id}")
        
        # 새로운 다운로드 시스템으로 재시작
        from .download_core import download_1fichier_file_new
        import threading
        
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
    
    print(f"[LOG] 다운로드 정지 요청: ID {download_id}, 현재 상태: {item.status}")
    
    # pending, downloading, proxying 상태만 정지 가능
    if item.status not in [StatusEnum.pending, StatusEnum.downloading, StatusEnum.proxying]:
        raise HTTPException(status_code=400, detail=f"현재 상태({item.status})에서는 정지할 수 없습니다")
    
    # 상태를 stopped로 변경
    setattr(item, "status", StatusEnum.stopped)
    db.commit()
    
    print(f"[LOG] 다운로드 상태를 stopped로 변경 완료: ID {download_id}")
    
    # WebSocket으로 상태 업데이트 알림
    from main import notify_status_update
    notify_status_update(db, download_id)
    print(f"[LOG] ★ 정지 WebSocket 알림 전송 완료: ID={download_id}")
    
    return {"id": item.id, "status": item.status}

@router.post("/retry/{download_id}")
def retry_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    print(f"[LOG] 다운로드 재시도 요청: ID {download_id}, 현재 상태: {item.status}")
    
    # 원래 프록시 설정 사용 (기본값 없이)
    original_use_proxy = getattr(item, 'use_proxy', None)
    if original_use_proxy is None:
        # DB에 use_proxy가 없는 경우 (구버전 호환) - 기본값 False (로컬)
        original_use_proxy = False
        print(f"[LOG] retry에서 use_proxy 설정이 없어 기본값 False(로컬) 사용: ID {download_id}")
    else:
        print(f"[LOG] retry에서 원래 프록시 설정 사용: use_proxy={original_use_proxy}, ID {download_id}")
    
    # 재시도 시에는 항상 대기 상태로 추가 (큐에서 순서 대기)
    setattr(item, "status", StatusEnum.pending)
    setattr(item, "error", None)
    setattr(item, "direct_link", None)  # 재시도 시 새로운 링크 파싱 강제
    db.commit()
    
    print(f"[LOG] 재시도 요청이 대기 큐에 추가됨: ID {download_id}")
    
    # 프록시 다운로드인 경우 즉시 시작 가능
    if original_use_proxy:
        from .download_core import download_1fichier_file_new
        import threading
        
        setattr(item, "status", StatusEnum.downloading)
        db.commit()
        
        thread = threading.Thread(
            target=download_1fichier_file_new,
            args=(download_id, "ko", original_use_proxy),
            daemon=True
        )
        thread.start()
        
        return {"id": item.id, "status": item.status, "message": "Download retry started (proxy mode)"}
    else:
        # 로컬 다운로드는 대기 상태로 유지 (자동 큐 시스템이 처리)
        return {"id": item.id, "status": "waiting", "message": "Download added to queue for retry"}

