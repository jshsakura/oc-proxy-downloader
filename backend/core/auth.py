# -*- coding: utf-8 -*-
"""
JWT 기반 인증 시스템
환경변수를 통한 로그인 인증 관리
로그인 시도 횟수 제한 (5회 실패 시 5분 차단)
"""
import os
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext

# 환경변수에서 인증 설정 가져오기
AUTH_USERNAME = os.getenv('AUTH_USERNAME')
AUTH_PASSWORD = os.getenv('AUTH_PASSWORD') 
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'default-secret-key-change-in-production')
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))

# 인증이 활성화되었는지 확인
AUTHENTICATION_ENABLED = bool(AUTH_USERNAME and AUTH_PASSWORD)

# 비밀번호 해싱을 위한 컨텍스트 (단순한 경우 평문 비교도 지원)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer 토큰을 위한 스키마
security = HTTPBearer(auto_error=False)

# 로그인 시도 제한을 위한 메모리 저장소 (운영환경에서는 Redis 사용 권장)
login_attempts = {}  # IP 주소별 실패 횟수와 차단 시간 저장
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 5

class AuthManager:
    @staticmethod
    def check_ip_blocked(client_ip: str) -> bool:
        """IP 주소가 차단되었는지 확인"""
        if client_ip not in login_attempts:
            return False
        
        attempt_data = login_attempts[client_ip]
        if attempt_data['attempts'] >= MAX_LOGIN_ATTEMPTS:
            # 차단 시간이 지났는지 확인
            if datetime.now() < attempt_data['blocked_until']:
                return True
            else:
                # 차단 시간이 지났으면 초기화
                del login_attempts[client_ip]
        
        return False
    
    @staticmethod
    def record_failed_login(client_ip: str):
        """로그인 실패 기록"""
        now = datetime.now()
        
        if client_ip not in login_attempts:
            login_attempts[client_ip] = {
                'attempts': 1,
                'first_attempt': now,
                'blocked_until': None
            }
        else:
            login_attempts[client_ip]['attempts'] += 1
        
        # 최대 시도 횟수에 도달하면 차단
        if login_attempts[client_ip]['attempts'] >= MAX_LOGIN_ATTEMPTS:
            login_attempts[client_ip]['blocked_until'] = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
    
    @staticmethod
    def clear_login_attempts(client_ip: str):
        """성공적인 로그인 후 시도 기록 초기화"""
        if client_ip in login_attempts:
            del login_attempts[client_ip]
    
    @staticmethod
    def get_remaining_lockout_time(client_ip: str) -> Optional[int]:
        """남은 차단 시간(초) 반환"""
        if client_ip not in login_attempts:
            return None
        
        attempt_data = login_attempts[client_ip]
        if attempt_data['blocked_until'] and datetime.now() < attempt_data['blocked_until']:
            remaining = (attempt_data['blocked_until'] - datetime.now()).total_seconds()
            return int(remaining)
        
        return None
    
    @staticmethod
    def verify_credentials(username: str, password: str) -> bool:
        """사용자 인증 확인"""
        if not AUTHENTICATION_ENABLED:
            return True  # 인증이 비활성화된 경우 항상 성공
        
        return username == AUTH_USERNAME and password == AUTH_PASSWORD
    
    @staticmethod
    def create_access_token(data: Dict[str, Any]) -> str:
        """JWT 액세스 토큰 생성"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
        to_encode.update({"exp": expire})
        
        encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def verify_token(token: str) -> Optional[Dict[str, Any]]:
        """JWT 토큰 검증"""
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    @staticmethod
    def is_authentication_enabled() -> bool:
        """인증이 활성화되었는지 확인"""
        return AUTHENTICATION_ENABLED

# FastAPI 의존성 함수들
def get_current_user_optional(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[Dict[str, Any]]:
    """현재 사용자 정보 가져오기 (선택적)"""
    if not AUTHENTICATION_ENABLED:
        return {"username": "anonymous", "authenticated": False}
    
    if not credentials:
        return None
    
    token = credentials.credentials
    payload = AuthManager.verify_token(token)
    
    if payload is None:
        return None
    
    return payload

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    """현재 사용자 정보 가져오기 (필수)"""
    if not AUTHENTICATION_ENABLED:
        return {"username": "anonymous", "authenticated": False}
    
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    payload = AuthManager.verify_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return payload

def require_auth(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """인증 필수 데코레이터"""
    return user

# 편의 함수들
auth_manager = AuthManager()