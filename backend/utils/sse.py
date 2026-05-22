"""
SSE message-sending utilities
"""

import asyncio
import threading
from services.sse_manager import sse_manager


def send_sse_message(message_type: str, data: dict):
    """Unified SSE message-sending function"""
    try:
        # Check whether there is a current loop
        try:
            loop = asyncio.get_running_loop()
            # Create a task on the current loop
            loop.create_task(sse_manager.broadcast_message(message_type, data))
        except RuntimeError:
            # No loop, so create a new loop in a thread
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