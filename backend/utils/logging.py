# -*- coding: utf-8 -*-
import sys
import os
import builtins


def setup_logging():
    """UTF-8 인코딩 강제 설정"""
    if sys.platform.startswith('win'):
        try:
            # Windows에서 UTF-8 강제 설정
            os.environ['PYTHONIOENCODING'] = 'utf-8'
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except:
            pass


def force_print(*args, **kwargs):
    """강제 stdout 출력"""
    message = ' '.join(str(arg) for arg in args)
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()


def smart_print(*args, **kwargs):
    """로그 레벨에 따른 메시지 필터링 - reentrant call 방지"""
    try:
        message = ' '.join(str(arg) for arg in args)

        # 런타임에 LOG_LEVEL 확인 (환경변수가 변경될 수 있으므로)
        log_level = os.getenv('LOG_LEVEL', 'DEBUG').upper()

        # LOG_LEVEL에 따른 필터링
        if log_level == 'ERROR' and not any(tag in message for tag in ['[ERROR]']):
            return
        elif log_level == 'WARNING' and not any(tag in message for tag in ['[ERROR]', '[WARNING]']):
            return
        elif log_level == 'INFO' and not any(tag in message for tag in ['[ERROR]', '[WARNING]', '[LOG]']):
            return
        # DEBUG 레벨이면 모든 메시지 출력

        # reentrant call 방지를 위해 try-except로 보호
        sys.stdout.write(f"{message}\n")
        sys.stdout.flush()
    except (RuntimeError, OSError):
        # reentrant call이나 stdout 문제 시 무시
        pass


def replace_print():
    """기존 print를 smart_print로 대체"""
    builtins.print = smart_print


def log_once(message):
    """같은 메시지를 한 번만 로그에 출력"""
    if message not in _logged_messages:
        _logged_messages.add(message)
        print(message)


def clear_log_cache():
    """로그 캐시 초기화"""
    global _logged_messages
    _logged_messages.clear()


# 로그 중복 방지를 위한 전역 변수
_logged_messages = set()
