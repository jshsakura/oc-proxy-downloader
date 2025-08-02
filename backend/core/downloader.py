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

# 앱 시작 시 테이블 생성
Base.metadata.create_all(bind=engine)

router = APIRouter()

class DownloadRequestCreate(BaseModel):
    url: HttpUrl
    password: str = ""
    use_proxy: bool = True

@router.post("/download/")
def create_download_task(request: DownloadRequestCreate, db: Session = Depends(get_db)):
    db_req = DownloadRequest(
        url=str(request.url),
        status=StatusEnum.pending,
        password=request.password,
        use_proxy=request.use_proxy
    )
    db.add(db_req)
    db.commit()
    db.refresh(db_req)
    
    # 다운로드 시작 - 데몬 스레드로 실행하여 메인 프로세스 종료 시 함께 종료
    from main import download_1fichier_file
    import threading
    thread = threading.Thread(
        target=download_1fichier_file,
        args=(db_req.id, "ko", request.use_proxy),
        daemon=True  # 데몬 스레드로 설정
    )
    thread.start()
    
    return {"id": db_req.id, "status": db_req.status}

@router.get("/history/")
def get_download_history(db: Session = Depends(get_db)):
    history = db.query(DownloadRequest).order_by(DownloadRequest.requested_at.desc()).all()
    return [item.as_dict() for item in history]

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
    
    # paused 상태인 경우에만 재개
    if getattr(item, 'status', None) == StatusEnum.paused:
        setattr(item, "status", StatusEnum.downloading)
        db.commit()
        
        # 다운로드 재시작
        from main import download_1fichier_file
        import threading
        thread = threading.Thread(
            target=download_1fichier_file,
            args=(download_id, "ko", getattr(item, 'use_proxy', True)),
            daemon=True
        )
        thread.start()
        
        return {"id": item.id, "status": item.status, "message": "Download resumed"}
    else:
        raise HTTPException(status_code=400, detail="Download is not in a paused state")

@router.delete("/delete/{download_id}")
def delete_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    # 다운로드 중인 경우 취소
    from main import download_manager
    if download_manager.is_download_active(download_id):
        download_manager.cancel_download(download_id)
    
    # DB에서 삭제
    db.delete(item)
    db.commit()
    
    return {"message": "Download deleted successfully"}

@router.post("/pause/{download_id}")
def pause_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    # 상태를 paused로 변경
    setattr(item, "status", StatusEnum.paused)
    db.commit()
    
    # 다운로드 중인 경우 취소
    from main import download_manager
    if download_manager.is_download_active(download_id):
        download_manager.cancel_download(download_id)
        print(f"[LOG] Download {download_id} cancelled due to pause request")
    
    return {"id": item.id, "status": item.status}

@router.post("/retry/{download_id}")
def retry_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    # 상태를 downloading으로 변경하고 에러 초기화
    setattr(item, "status", StatusEnum.downloading)
    setattr(item, "error", None)
    db.commit()
    
    # 다운로드 재시작
    from main import download_1fichier_file
    import threading
    thread = threading.Thread(
        target=download_1fichier_file,
        args=(download_id, "ko", getattr(item, 'use_proxy', True)),
        daemon=True
    )
    thread.start()
    
    return {"id": item.id, "status": item.status, "message": "Download retry started"}

