"""
알림 서비스 모듈
- SSE 메시지 전송
- 텔레그램 알림
"""

import asyncio
import threading
from services.sse_manager import sse_manager


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


def send_telegram_wait_notification(file_name, wait_minutes, language="ko", file_size_str=None):
    """텔레그램 대기 시간 알림 전송"""
    try:
        # TODO: 실제 텔레그램 전송 로직 구현
        print(f"[TELEGRAM] 대기 알림: {file_name}, {wait_minutes}분 대기")
        if file_size_str:
            print(f"[TELEGRAM] 파일 크기: {file_size_str}")
    except Exception as e:
        print(f"[LOG] 텔레그램 알림 실패: {e}")