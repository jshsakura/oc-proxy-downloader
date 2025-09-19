"""
알림 서비스 모듈
- SSE 메시지 전송
- 텔레그램 알림
"""

import asyncio
import threading
import requests
import datetime
from services.sse_manager import sse_manager
from core.config import get_config
from core.i18n import get_translations


def send_sse_message(message_type: str, data: dict):
    """통합된 SSE 메시지 전송 함수"""
    try:
        # 간단하게 새 스레드에서 비동기 실행
        def run_broadcast():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(sse_manager.broadcast_message(message_type, data))
                loop.close()
            except Exception as e:
                print(f"[LOG] SSE 전송 실패: {e}")

        threading.Thread(target=run_broadcast, daemon=True).start()

    except Exception as e:
        print(f"[LOG] SSE 메시지 전송 실패: {e}")


def send_telegram_wait_notification(file_name: str, wait_minutes: int, language: str = "ko", file_size_str: str = None):
    """텔레그램 대기 시간 알림 전송"""
    print(f"[DEBUG] 텔레그램 대기 알림 호출됨: file_name={file_name}, wait_minutes={wait_minutes}")
    try:
        config = get_config()

        bot_token = config.get("telegram_bot_token", "").strip()
        chat_id = config.get("telegram_chat_id", "").strip()
        notify_wait = config.get("telegram_notify_wait", True)

        print(f"[DEBUG] 텔레그램 설정: bot_token={'있음' if bot_token else '없음'}, chat_id={'있음' if chat_id else '없음'}, notify_wait={notify_wait}")

        if not bot_token or not chat_id or not notify_wait:
            print(f"[DEBUG] 텔레그램 알림 조건 불만족 - 전송 중단")
            return

        translations = get_translations(language)

        # HTML 형식으로 메시지 작성
        if language == "ko":
            current_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            current_time = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        wait_text = translations.get("telegram_wait_detected", "Wait Time Detected")
        filename_text = translations.get("telegram_filename", "Filename")
        wait_time_text = translations.get("telegram_wait_time", "Wait Time")
        filesize_text = translations.get("telegram_filesize", "File Size")

        message = f"""⏱️ <b>OC-Proxy: {wait_text}</b> ⏳

📁 <b>{filename_text}</b>
<code>{file_name}</code>

📊 <b>{filesize_text}</b>
<code>{file_size_str or ('알 수 없음' if language == 'ko' else 'Unknown')}</code>

⏰ <b>{wait_time_text}</b>
<code>{wait_minutes}분</code>"""

        print(f"[DEBUG] 텔레그램 메시지 생성 완료, API 호출 시작")

        # 텔레그램 API 호출
        def send_notification():
            try:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                }

                print(f"[DEBUG] 텔레그램 API 호출: URL={url[:50]}..., chat_id={chat_id}")
                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    print(f"[TELEGRAM] 대기 알림 전송 성공: {file_name} ({wait_minutes}분)")
                else:
                    print(f"[WARNING] 텔레그램 전송 실패 - HTTP {response.status_code}: {response.text}")
            except Exception as e:
                print(f"[WARNING] 텔레그램 전송 실패: {e}")

        # 별도 스레드에서 전송
        print(f"[DEBUG] 텔레그램 알림 스레드 시작")
        threading.Thread(target=send_notification, daemon=True).start()

    except Exception as e:
        print(f"[LOG] 텔레그램 알림 실패: {e}")


def send_telegram_start_notification(file_name: str, download_mode: str, language: str = "ko", file_size_str: str = None):
    """텔레그램 다운로드 시작 알림"""
    print(f"[DEBUG] 텔레그램 시작 알림 호출됨: file_name={file_name}, download_mode={download_mode}")
    try:
        config = get_config()

        bot_token = config.get("telegram_bot_token", "").strip()
        chat_id = config.get("telegram_chat_id", "").strip()
        notify_start = config.get("telegram_notify_start", False)

        print(f"[DEBUG] 텔레그램 시작 설정: bot_token={'있음' if bot_token else '없음'}, chat_id={'있음' if chat_id else '없음'}, notify_start={notify_start}")

        if not bot_token or not chat_id or not notify_start:
            print(f"[DEBUG] 텔레그램 시작 알림 조건 불만족 - 전송 중단")
            return

        translations = get_translations(language)

        if language == "ko":
            current_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            current_time = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        start_text = translations.get("telegram_download_started", "Download Started")
        filename_text = translations.get("telegram_filename", "Filename")
        started_time_text = translations.get("telegram_started_time", "Started At")
        filesize_text = translations.get("telegram_filesize", "File Size")
        mode_text = translations.get("telegram_download_mode", "Download Mode")

        mode_display = "프록시" if download_mode == "proxy" else "로컬" if language == "ko" else download_mode.title()

        message = f"""🚀 <b>OC-Proxy: {start_text}</b> 📥

📁 <b>{filename_text}</b>
<code>{file_name}</code>

📊 <b>{filesize_text}</b>
<code>{file_size_str or ('알 수 없음' if language == 'ko' else 'Unknown')}</code>

🔧 <b>{mode_text}</b>
<code>{mode_display}</code>

🕐 <b>{started_time_text}</b>
<code>{current_time}</code>"""

        def send_notification():
            try:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                }

                response = requests.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    print(f"[TELEGRAM] 시작 알림 전송 성공: {file_name}")
                else:
                    print(f"[WARNING] 텔레그램 전송 실패 - HTTP {response.status_code}")
            except Exception as e:
                print(f"[WARNING] 텔레그램 전송 실패: {e}")

        threading.Thread(target=send_notification, daemon=True).start()

    except Exception as e:
        print(f"[LOG] 텔레그램 시작 알림 실패: {e}")


def send_telegram_notification(file_name: str, status: str, error: str = None, language: str = "ko",
                              file_size_str: str = None, download_time: str = None,
                              save_path: str = None, requested_time: str = None):
    """텔레그램 완료/실패 알림"""
    try:
        print(f"[DEBUG] send_telegram_notification 호출됨: file_name={file_name}, status={status}")
        config = get_config()

        bot_token = config.get("telegram_bot_token", "").strip()
        chat_id = config.get("telegram_chat_id", "").strip()
        notify_success = config.get("telegram_notify_success", False)
        notify_failure = config.get("telegram_notify_failure", True)

        print(f"[DEBUG] 텔레그램 설정: bot_token={'있음' if bot_token else '없음'}, chat_id={'있음' if chat_id else '없음'}")

        if not bot_token or not chat_id:
            print(f"[DEBUG] 텔레그램 설정 부족으로 알림 건너뜀")
            return

        # 상태에 따른 알림 설정 확인
        print(f"[DEBUG] 텔레그램 알림 설정 체크: status={status}, notify_success={notify_success}, notify_failure={notify_failure}")
        if status == "success" and not notify_success:
            print(f"[DEBUG] 성공 알림이 비활성화되어 있어 알림 건너뜀")
            return
        if status == "failed" and not notify_failure:
            print(f"[DEBUG] 실패 알림이 비활성화되어 있어 알림 건너뜀")
            return

        translations = get_translations(language)

        if language == "ko":
            current_time = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            current_time = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        if status == "success":
            success_text = translations.get("telegram_download_success", "Download Complete")
            filename_text = translations.get("telegram_filename", "Filename")
            filesize_text = translations.get("telegram_filesize", "파일크기")
            requested_time_text = translations.get("telegram_requested_time", "요청시간")
            completed_time_text = translations.get("telegram_completed_time", "완료시간")
            save_path_text = translations.get("telegram_save_path", "저장경로")

            message = f"""✅ <b>OC-Proxy: {success_text}</b> 🎉

📁 <b>{filename_text}</b>
<code>{file_name}</code>

📊 <b>{filesize_text}</b>
<code>{file_size_str or ('알 수 없음' if language == 'ko' else 'Unknown')}</code>

📅 <b>{requested_time_text}</b>
<code>{requested_time or 'N/A'}</code>

🕐 <b>{completed_time_text}</b>
<code>{download_time or current_time}</code>

💾 <b>{save_path_text}</b>
<code>{save_path or 'N/A'}</code>"""

        else:  # failed
            failed_text = translations.get("telegram_download_failed", "Download Failed")
            filename_text = translations.get("telegram_filename", "Filename")
            error_text = translations.get("telegram_error", "Error")
            failed_time_text = translations.get("telegram_failed_time", "실패시간")

            message = f"""❌ <b>OC-Proxy: {failed_text}</b> 💥

📁 <b>{filename_text}</b>
<code>{file_name}</code>

❌ <b>{error_text}</b>
<code>{error or ('알 수 없는 오류' if language == 'ko' else 'Unknown error')}</code>

🕐 <b>{failed_time_text}</b>
<code>{current_time}</code>"""

        def send_notification():
            try:
                print(f"[DEBUG] 텔레그램 메시지 전송 시작: {status}")
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                }

                print(f"[DEBUG] 텔레그램 요청 URL: {url}")
                print(f"[DEBUG] 텔레그램 메시지 내용: {message[:100]}...")

                response = requests.post(url, json=payload, timeout=10)
                print(f"[DEBUG] 텔레그램 응답 코드: {response.status_code}")
                print(f"[DEBUG] 텔레그램 응답 내용: {response.text}")

                if response.status_code == 200:
                    print(f"[TELEGRAM] {status} 알림 전송 성공: {file_name}")
                else:
                    print(f"[WARNING] 텔레그램 전송 실패 - HTTP {response.status_code}: {response.text}")
            except Exception as e:
                print(f"[WARNING] 텔레그램 전송 실패: {e}")

        threading.Thread(target=send_notification, daemon=True).start()

    except Exception as e:
        print(f"[LOG] 텔레그램 알림 실패: {e}")