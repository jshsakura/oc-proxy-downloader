"""
SSE 메시지 전송 유틸리티
"""

import asyncio
import threading
from services.sse_manager import sse_manager


def send_sse_message(message_type: str, data: dict):
    """통합된 SSE 메시지 전송 함수"""
    try:
        # 현재 루프가 있는지 확인
        try:
            loop = asyncio.get_running_loop()
            # 현재 루프에서 태스크 생성
            loop.create_task(sse_manager.broadcast_message(message_type, data))
        except RuntimeError:
            # 루프가 없으면 스레드에서 새 루프 생성
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