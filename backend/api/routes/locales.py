# -*- coding: utf-8 -*-
import os
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from core.config import get_config, save_config, get_download_path
from core.db import get_db
from core.i18n import get_translations, reload_translations

router = APIRouter(prefix="/api", tags=["locales"])


@router.get("/locales/{lang}.json")
async def get_locale(lang: str, request: Request):
    """언어 파일 조회"""
    try:
        translations = get_translations(lang)
        if not translations:
            raise HTTPException(status_code=404, detail="Language not found")


        return JSONResponse(
            content=translations,
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

    except Exception as e:
        print(f"[ERROR] Get locale failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/locales/reload")
async def reload_locale(request: Request):
    """번역 캐시 다시 로드"""
    try:
        success = reload_translations()
        return {"success": success, "message": "Translations reloaded"}
    except Exception as e:
        print(f"[ERROR] Reload translations failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
