"""
로그 중복 방지 모듈
"""
import os

# 로그 중복 방지를 위한 전역 변수
_logged_messages = set()

def log_once(message):
    """같은 메시지를 한 번만 로그에 출력"""
    if message not in _logged_messages:
        _logged_messages.add(message)
        print(message)

def clear_log_cache():
    """로그 캐시 초기화"""
    global _logged_messages
    _logged_messages.clear()