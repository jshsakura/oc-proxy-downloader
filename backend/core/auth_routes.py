# -*- coding: utf-8 -*-
"""
인증 관련 API 라우트
로그인 시도 제한 포함
"""
from fastapi import APIRouter, HTTPException, status, Request
from pydantic import BaseModel
from typing import Optional
from .auth import auth_manager, AUTHENTICATION_ENABLED

router = APIRouter()

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    username: str

class AuthStatusResponse(BaseModel):
    authentication_enabled: bool
    authenticated: bool
    username: Optional[str] = None

class LoginErrorResponse(BaseModel):
    detail: str
    remaining_lockout_time: Optional[int] = None

@router.post("/auth/login", response_model=LoginResponse)
def login(request: LoginRequest, req: Request):
    """로그인 API (5회 실패 시 5분 차단)"""
    # 클라이언트 IP 주소 획득
    client_ip = req.client.host if req.client else "unknown"
    print(f"[LOG] 로그인 시도: {request.username} from {client_ip}")
    
    if not AUTHENTICATION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication is not enabled"
        )
    
    # IP 차단 상태 확인
    if auth_manager.check_ip_blocked(client_ip):
        remaining_time = auth_manager.get_remaining_lockout_time(client_ip)
        print(f"[LOG] IP 차단됨: {client_ip}, 남은 시간: {remaining_time}초")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Please try again after {remaining_time} seconds.",
            headers={"X-RateLimit-Remaining-Time": str(remaining_time)}
        )
    
    # 사용자 인증 확인
    if not auth_manager.verify_credentials(request.username, request.password):
        print(f"[LOG] 로그인 실패: 잘못된 인증 정보 - {request.username} from {client_ip}")
        
        # 실패 기록
        auth_manager.record_failed_login(client_ip)
        
        # 차단 여부 재확인
        if auth_manager.check_ip_blocked(client_ip):
            remaining_time = auth_manager.get_remaining_lockout_time(client_ip)
            print(f"[LOG] IP 차단됨 (한계 도달): {client_ip}, 남은 시간: {remaining_time}초")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts. Account locked for {remaining_time} seconds.",
                headers={"X-RateLimit-Remaining-Time": str(remaining_time)}
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
    
    # 로그인 성공 - 시도 기록 초기화
    auth_manager.clear_login_attempts(client_ip)
    
    # JWT 토큰 생성
    token_data = {
        "sub": request.username,
        "username": request.username,
        "authenticated": True
    }
    
    access_token = auth_manager.create_access_token(token_data)
    
    print(f"[LOG] 로그인 성공: {request.username} from {client_ip}")
    
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=24 * 60 * 60,  # 24시간 (초 단위)
        username=request.username
    )

@router.get("/auth/status", response_model=AuthStatusResponse)
def get_auth_status():
    """인증 상태 확인 API"""
    return AuthStatusResponse(
        authentication_enabled=AUTHENTICATION_ENABLED,
        authenticated=False  # 프론트엔드에서 토큰으로 확인
    )

@router.post("/auth/verify")
def verify_token():
    """토큰 검증 API (인증이 필요한 엔드포인트)"""
    from .auth import require_auth
    from fastapi import Depends
    
    @router.post("/auth/verify")
    def verify_token_endpoint(user: dict = Depends(require_auth)):
        return {
            "valid": True,
            "user": user
        }
    
    return {"valid": True}