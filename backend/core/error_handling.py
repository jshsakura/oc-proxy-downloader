"""
Common error-handling module
- Standardized exception handling
- Error logging
- User-friendly error messages
"""

import logging
from typing import Optional, Dict, Any
from enum import Enum


class ErrorCode(Enum):
    """Error code definitions"""
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    PARSE_FAILED = "PARSE_FAILED"
    PROXY_FAILED = "PROXY_FAILED"
    FILE_ACCESS_ERROR = "FILE_ACCESS_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class AppError(Exception):
    """Common application exception class"""
    def __init__(self, code: ErrorCode, message: str, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def handle_error(error: Exception, context: str = "") -> Dict[str, Any]:
    """
    Common error-handling function

    Args:
        error: The exception that occurred
        context: The context in which the error occurred

    Returns:
        An error-info dictionary
    """
    error_info = {
        "success": False,
        "error_code": ErrorCode.UNKNOWN_ERROR.value,
        "message": "알 수 없는 오류가 발생했습니다.",
        "context": context,
        "details": {}
    }

    if isinstance(error, AppError):
        error_info.update({
            "error_code": error.code.value,
            "message": error.message,
            "details": error.details
        })
    elif isinstance(error, (ConnectionError, TimeoutError)):
        error_info.update({
            "error_code": ErrorCode.NETWORK_ERROR.value,
            "message": "네트워크 연결 오류가 발생했습니다."
        })
    elif isinstance(error, FileNotFoundError):
        error_info.update({
            "error_code": ErrorCode.FILE_ACCESS_ERROR.value,
            "message": "파일을 찾을 수 없습니다."
        })
    elif isinstance(error, PermissionError):
        error_info.update({
            "error_code": ErrorCode.FILE_ACCESS_ERROR.value,
            "message": "파일 접근 권한이 없습니다."
        })
    else:
        error_info["message"] = str(error) if str(error) else "알 수 없는 오류가 발생했습니다."

    # Logging
    log_error(error, context, error_info)

    return error_info


def log_error(error: Exception, context: str, error_info: Dict[str, Any]):
    """Error logging"""
    logger = logging.getLogger(__name__)

    log_message = f"[{context}] {error_info['error_code']}: {error_info['message']}"
    if error_info.get('details'):
        log_message += f" | Details: {error_info['details']}"

    logger.error(log_message, exc_info=True)
    print(f"[LOG] ❌ {log_message}")


def safe_execute(func, *args, context: str = "", **kwargs) -> Dict[str, Any]:
    """
    Safe function-execution wrapper

    Args:
        func: The function to execute
        *args: Function arguments
        context: Execution context
        **kwargs: Function keyword arguments

    Returns:
        The execution result or error info
    """
    try:
        result = func(*args, **kwargs)
        return {
            "success": True,
            "result": result
        }
    except Exception as e:
        return handle_error(e, context or func.__name__)