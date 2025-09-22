# -*- coding: utf-8 -*-
import os
import threading
import queue
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from core.config import get_config, save_config, get_download_path, get_default_download_path, IS_STANDALONE
from core.db import get_db
from services.notification_service import send_telegram_notification

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
async def get_default_download_path_endpoint(request: Request):
    """환경별 기본 다운로드 경로 조회"""
    try:
        default_path = get_default_download_path()
        return {
            "default_download_path": default_path,
            "is_standalone": IS_STANDALONE,
            "is_docker": bool(os.environ.get("CONFIG_PATH"))
        }
    except Exception as e:
        print(f"[ERROR] Get default download path failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/select_folder")
async def select_folder(request: Request):
    """폴더 선택 다이얼로그 (스탠드얼론 환경에서만 지원)"""
    # 도커 환경에서는 폴더 선택 다이얼로그 비활성화
    if os.environ.get("CONFIG_PATH"):
        raise HTTPException(status_code=501, detail="폴더 선택은 도커 환경에서 지원되지 않습니다")

    if not GUI_AVAILABLE:
        raise HTTPException(status_code=501, detail="GUI not available")

    try:
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


@router.post("/telegram/test")
async def test_telegram_notification(request: Request):
    """텔레그램 알림 테스트"""
    try:
        print(f"[LOG] 텔레그램 테스트 알림 시작")

        # 설정 확인
        config = get_config()
        bot_token = config.get("telegram_bot_token", "").strip()
        chat_id = config.get("telegram_chat_id", "").strip()
        notify_success = config.get("telegram_notify_success", False)

        # 번역된 텍스트 가져오기
        from core.i18n import get_translations
        user_language = config.get("language", "ko")
        translations = get_translations(user_language)

        if not bot_token:
            error_msg = "텔레그램 봇 토큰이 설정되지 않았습니다." if user_language == "ko" else "Telegram bot token is not configured."
            return {"success": False, "message": error_msg}

        if not chat_id:
            error_msg = "텔레그램 채팅 ID가 설정되지 않았습니다." if user_language == "ko" else "Telegram chat ID is not configured."
            return {"success": False, "message": error_msg}

        if not notify_success:
            error_msg = "텔레그램 성공 알림이 비활성화되어 있습니다. 설정에서 활성화해주세요." if user_language == "ko" else "Telegram success notifications are disabled. Please enable them in settings."
            return {"success": False, "message": error_msg}

        # 번역된 테스트 메시지 사용

        test_file_name = f"🧪 {translations.get('telegram_test', 'Telegram Test')}"
        test_size = translations.get('telegram_test_message', 'Test message from OC Proxy Downloader')
        test_path = translations.get('telegram_test', 'Test Path') if user_language == 'ko' else 'Test Path'

        # 간단한 테스트 메시지 전송
        send_telegram_notification(
            file_name=test_file_name,
            status="success",
            language=user_language,
            file_size_str=test_size,
            save_path=test_path,
            requested_time="00:00:01"
        )

        success_message = translations.get('telegram_test_success', 'Telegram test message sent successfully')
        return {"success": True, "message": success_message}

    except Exception as e:
        print(f"[ERROR] 텔레그램 테스트 실패: {e}")
        error_msg = f"텔레그램 테스트 실패: {str(e)}" if config.get("language", "ko") == "ko" else f"Telegram test failed: {str(e)}"
        return {"success": False, "message": error_msg}


