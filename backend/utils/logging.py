# -*- coding: utf-8 -*-
import sys
import os
import builtins


def setup_logging():
    """Force UTF-8 encoding"""
    if sys.platform.startswith('win'):
        try:
            # Force UTF-8 on Windows
            os.environ['PYTHONIOENCODING'] = 'utf-8'
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except:
            pass


def force_print(*args, **kwargs):
    """Force output to stdout"""
    message = ' '.join(str(arg) for arg in args)
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()


def smart_print(*args, **kwargs):
    """Filter messages by log level - prevents reentrant calls"""
    try:
        message = ' '.join(str(arg) for arg in args)

        # Check LOG_LEVEL at runtime (since the env var may change)
        log_level = os.getenv('LOG_LEVEL', 'DEBUG').upper()

        # Filter by LOG_LEVEL
        if log_level == 'ERROR' and not any(tag in message for tag in ['[ERROR]']):
            return
        elif log_level == 'WARNING' and not any(tag in message for tag in ['[ERROR]', '[WARNING]']):
            return
        elif log_level == 'INFO' and not any(tag in message for tag in ['[ERROR]', '[WARNING]', '[LOG]']):
            return
        # At DEBUG level, print all messages

        # Guard with try-except to prevent reentrant calls
        sys.stdout.write(f"{message}\n")
        sys.stdout.flush()
    except (RuntimeError, OSError):
        # Ignore on reentrant calls or stdout problems
        pass


def replace_print():
    """Replace the built-in print with smart_print"""
    builtins.print = smart_print


def log_once(message):
    """Log the same message only once"""
    if message not in _logged_messages:
        _logged_messages.add(message)
        print(message)


def clear_log_cache():
    """Clear the log cache"""
    global _logged_messages
    _logged_messages.clear()


# Global variable to prevent duplicate logging
_logged_messages = set()
