# -*- coding: utf-8 -*-
import os
import jwt
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/auth", tags=["authentication"])

# JWT 설정
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'fallback-secret-key')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRATION_HOURS = 24

# 인증 설정
AUTH_USERNAME = os.getenv('AUTH_USERNAME')
AUTH_PASSWORD = os.getenv('AUTH_PASSWORD')
AUTHENTICATION_ENABLED = bool(AUTH_USERNAME and AUTH_PASSWORD)

security = HTTPBearer(auto_error=False)

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str

def create_access_token(data: dict):
    """JWT 토큰 생성"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt

def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """JWT 토큰 검증"""
    if not AUTHENTICATION_ENABLED:
        return {"username": "guest", "authenticated": False}
    
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )
        return {"username": username, "authenticated": True}
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

@router.post("/login", response_model=LoginResponse)
async def login(login_request: LoginRequest):
    """로그인 처리"""
    if not AUTHENTICATION_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authentication not configured"
        )
    
    if (login_request.username != AUTH_USERNAME or 
        login_request.password != AUTH_PASSWORD):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    
    access_token = create_access_token(data={"sub": login_request.username})
    
    return LoginResponse(
        access_token=access_token,
        expires_in=JWT_EXPIRATION_HOURS * 3600,
        username=login_request.username
    )

@router.get("/status")
async def auth_status():
    """인증 상태 확인"""
    return {
        "authentication_enabled": AUTHENTICATION_ENABLED,
        "username_configured": bool(AUTH_USERNAME),
        "password_configured": bool(AUTH_PASSWORD)
    }

@router.get("/verify")
async def verify_auth(current_user: dict = Depends(verify_token)):
    """토큰 검증"""
    return {
        "valid": True,
        "user": current_user
    }