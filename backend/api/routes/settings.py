# -*- coding: utf-8 -*-
import os
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from core.config import get_config, save_config, get_download_path
from core.db import get_db

router = APIRouter(prefix="/api", tags=["settings"])

try:
    import tkinter as tk
    from tkinter import filedialog
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False


@router.get("/settings")
async def get_settings_endpoint(request: Request):
    """설정 조회"""
    try:
        config = get_config()
        return config
    except Exception as e:
        print(f"[ERROR] Get settings failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/settings")
async def update_settings_endpoint(settings: dict, request: Request):
    """설정 업데이트"""
    try:
        print(f"[LOG] Updating settings: {settings}")

        # 설정 저장
        save_config(settings)

        return {"success": True, "message": "설정이 저장되었습니다."}

    except Exception as e:
        print(f"[ERROR] Update settings failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/default_download_path")
async def get_default_download_path(request: Request):
    """기본 다운로드 경로 조회"""
    try:
        default_path = str(Path.home() / "Downloads")
        return {"default_download_path": default_path}
    except Exception as e:
        print(f"[ERROR] Get default download path failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/select_folder")
async def select_folder(request: Request):
    """폴더 선택 다이얼로그"""
    if not GUI_AVAILABLE:
        raise HTTPException(status_code=501, detail="GUI not available")

    try:
        import threading
        import queue

        result_queue = queue.Queue()

        def open_dialog():
            try:
                root = tk.Tk()
                root.withdraw()  # Hide the main window
                root.attributes('-topmost', True)  # Keep on top

                folder_path = filedialog.askdirectory(
                    title="다운로드 폴더를 선택하세요",
                    mustexist=True
                )

                result_queue.put({"success": True, "path": folder_path})
                root.destroy()

            except Exception as e:
                result_queue.put({"success": False, "error": str(e)})

        # GUI 스레드에서 실행
        thread = threading.Thread(target=open_dialog)
        thread.daemon = True
        thread.start()
        thread.join(timeout=30)  # 30초 타임아웃

        if result_queue.empty():
            raise HTTPException(status_code=408, detail="Dialog timeout")

        result = result_queue.get()

        if not result["success"]:
            raise HTTPException(status_code=500, detail=result["error"])

        if not result["path"]:  # 사용자가 취소한 경우
            return {"path": None}

        return {"path": result["path"]}

    except Exception as e:
        print(f"[ERROR] Select folder failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


