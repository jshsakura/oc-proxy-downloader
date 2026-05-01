# -*- coding: utf-8 -*-
import os
import threading
import queue
import httpx
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from core.config import get_config, save_config, get_download_path, get_default_download_path, IS_STANDALONE
from core.db import get_db
from core.version import CURRENT_VERSION
from services.notification_service import send_telegram_notification


def parse_version(version_str):
    """버전 문자열을 파싱하여 비교 가능한 튜플로 변환"""
    # v 접두사 제거
    version = version_str.lstrip('v')
    # . 으로 분할하여 정수 튜플로 변환
    try:
        parts = [int(x) for x in version.split('.')]
        # 3자리 버전으로 맞춤 (예: 2.0 -> 2.0.0)
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])  # 처음 3자리만 사용
    except ValueError:
        return (0, 0, 0)


def is_newer_version(latest_version, current_version):
    """latest_version이 current_version보다 최신인지 확인"""
    latest_tuple = parse_version(latest_version)
    current_tuple = parse_version(current_version)
    return latest_tuple > current_tuple

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


@router.get("/debug/parse-response")
async def get_debug_parse_response(stage: str = "post"):
    """마지막 1fichier 파싱 응답 본문 다운로드.

    파라미터 ``stage`` = ``get`` 또는 ``post`` (기본 post). 본문을 그대로
    내려주므로 사용자가 브라우저에서 ``/api/debug/parse-response?stage=post``
    로 접근하면 즉시 HTML 다운로드 가능. docker logs 접근이 어려운 환경에서도
    실패 진단에 사용.
    """
    from fastapi.responses import Response
    from core.config import CONFIG_DIR

    if stage not in ("get", "post"):
        raise HTTPException(status_code=400, detail="stage 는 get 또는 post 여야 합니다")

    path = CONFIG_DIR / f"parse_debug_{stage}.html"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"디버그 파일 없음: {path.name} (한 번 다운로드를 시도해야 생성됨)",
        )

    try:
        body = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"파일 읽기 실패: {exc}")

    return Response(
        content=body,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="parse_debug_{stage}.html"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/fichier/test-login")
async def test_fichier_login(request: Request):
    """저장된 1fichier 자격증명으로 로그인 테스트.

    body 가 비어있으면 ``config`` 의 ``fichier_email`` / ``fichier_password`` 사용,
    body 에 ``email`` / ``password`` 가 있으면 그 값으로 즉석 테스트 (저장 X).
    """
    from core import fichier_auth

    try:
        body = await request.json()
    except Exception:
        body = {}

    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    if not email or not password:
        config = get_config()
        email = (config.get("fichier_email") or "").strip()
        password = config.get("fichier_password") or ""

    if not email or not password:
        return {
            "success": False,
            "message": "1fichier 이메일/비밀번호가 입력되지 않았습니다.",
        }

    try:
        # force_refresh=True 로 캐시 무시하고 새 로그인 시도
        fichier_auth.get_authenticated_scraper(email, password, force_refresh=True)
        return {"success": True, "message": "로그인 성공 — 다운로드 시 자동 사용됩니다."}
    except fichier_auth.FichierLoginError as exc:
        return {"success": False, "message": f"로그인 실패: {exc}"}
    except Exception as exc:
        return {"success": False, "message": f"테스트 중 오류: {exc}"}


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


@router.get("/version")
async def get_version_info(request: Request):
    """현재 버전과 최신 버전 정보 조회"""
    try:
        config = get_config()
        user_language = config.get("language", "ko")

        version_info = {
            "current_version": CURRENT_VERSION,
            "latest_version": None,
            "update_available": False,
            "error": None
        }

        try:
            # GitHub API에서 최신 릴리즈 정보 가져오기
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.github.com/repos/jshsakura/oc-proxy-downloader/releases/latest"
                )

                if response.status_code == 200:
                    release_data = response.json()
                    latest_version = release_data.get("tag_name", "")

                    version_info["latest_version"] = latest_version

                    # 버전 비교 (의미론적 버전 비교)
                    if latest_version and is_newer_version(latest_version, CURRENT_VERSION):
                        version_info["update_available"] = True
                else:
                    version_info["error"] = "Failed to check latest version"

        except asyncio.TimeoutError:
            version_info["error"] = "Timeout checking latest version"
        except Exception as e:
            version_info["error"] = f"Error checking latest version: {str(e)}"

        return version_info

    except Exception as e:
        print(f"[ERROR] Get version info failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

