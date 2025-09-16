"""
공통 에러 처리 모듈
- 표준화된 예외 처리
- 에러 로깅
- 사용자 친화적 에러 메시지
"""

import logging
from typing import Optional, Dict, Any
from enum import Enum


class ErrorCode(Enum):
    """에러 코드 정의"""
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    PARSE_FAILED = "PARSE_FAILED"
    PROXY_FAILED = "PROXY_FAILED"
    FILE_ACCESS_ERROR = "FILE_ACCESS_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class AppError(Exception):
    """애플리케이션 공통 예외 클래스"""
    def __init__(self, code: ErrorCode, message: str, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def handle_error(error: Exception, context: str = "") -> Dict[str, Any]:
    """
    공통 에러 처리 함수

    Args:
        error: 발생한 예외
        context: 에러 발생 컨텍스트

    Returns:
        에러 정보 딕셔너리
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

    # 로깅
    log_error(error, context, error_info)

    return error_info


def log_error(error: Exception, context: str, error_info: Dict[str, Any]):
    """에러 로깅"""
    logger = logging.getLogger(__name__)

    log_message = f"[{context}] {error_info['error_code']}: {error_info['message']}"
    if error_info.get('details'):
        log_message += f" | Details: {error_info['details']}"

    logger.error(log_message, exc_info=True)
    print(f"[LOG] ❌ {log_message}")


def safe_execute(func, *args, context: str = "", **kwargs) -> Dict[str, Any]:
    """
    안전한 함수 실행 래퍼

    Args:
        func: 실행할 함수
        *args: 함수 인자
        context: 실행 컨텍스트
        **kwargs: 함수 키워드 인자

    Returns:
        실행 결과 또는 에러 정보
    """
    try:
        result = func(*args, **kwargs)
        return {
            "success": True,
            "result": result
        }
    except Exception as e:
        return handle_error(e, context or func.__name__)