import requests
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, HttpUrl
from core.models import DownloadRequest, Base
from core.db import engine, get_db
from core.i18n import get_message
import json
import os
import re
from core.recaptcha import RecaptchaV3

# 앱 시작 시 테이블 생성
Base.metadata.create_all(bind=engine)

app = FastAPI()

class DownloadRequestCreate(BaseModel):
    url: HttpUrl
    password: str = None

@app.post("/download/")
def create_download_task(request: DownloadRequestCreate, db: Session = Depends(get_db)):
    db_req = DownloadRequest(
        url=request.url,
        status="pending",
        password=request.password
    )
    db.add(db_req)
    db.commit()
    db.refresh(db_req)
    return {"id": db_req.id, "status": db_req.status}

@app.get("/history/")
def get_download_history(db: Session = Depends(get_db)):
    history = db.query(DownloadRequest).order_by(DownloadRequest.requested_at.desc()).all()
    return [item.as_dict() for item in history]

@app.get("/history/{download_id}")
def get_download_detail(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Download not found")
    return item.as_dict()

@app.post("/resume/{download_id}")
def resume_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Download not found")
    item.status = "pending"
    db.commit()
    return {"id": item.id, "status": item.status}

def get_message(key, lang="ko"):
    try:
        with open(os.path.join("locales", f"{lang}.json"), encoding="utf-8") as f:
            messages = json.load(f)
        return messages.get(key, key)
    except Exception:
        return key