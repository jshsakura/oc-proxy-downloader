# -*- coding: utf-8 -*-
"""
JWT-based authentication system
Manages login authentication via environment variables
Login attempt rate limiting (5 minute block after 5 failures)
"""
import os
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext

# Get authentication settings from environment variables
AUTH_USERNAME = os.getenv('AUTH_USERNAME')
AUTH_PASSWORD = os.getenv('AUTH_PASSWORD') 
JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'default-secret-key-change-in-production')
JWT_ALGORITHM = os.getenv('JWT_ALGORITHM', 'HS256')
JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', '24'))

# Check whether authentication is enabled
AUTHENTICATION_ENABLED = bool(AUTH_USERNAME and AUTH_PASSWORD)

# Temporary enablement for development/testing (lets you test the login screen even without env vars)
if not AUTHENTICATION_ENABLED:
    # Set up a temporary test account
    AUTH_USERNAME = AUTH_USERNAME or 'admin'
    AUTH_PASSWORD = AUTH_PASSWORD or 'admin'
    AUTHENTICATION_ENABLED = True
    print(f"[개발모드] 임시 로그인 활성화 - 사용자명: {AUTH_USERNAME}, 비밀번호: {AUTH_PASSWORD}")

# Context for password hashing (also supports plaintext comparison in simple cases)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Scheme for HTTP Bearer tokens
security = HTTPBearer(auto_error=False)

# In-memory store for login attempt limiting (Redis recommended in production)
login_attempts = {}  # store failure count and block time per IP address
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 5

class AuthManager:
    @staticmethod
    def check_ip_blocked(client_ip: str) -> bool:
        """Check whether the IP address is blocked"""
        if client_ip not in login_attempts:
            return False

        attempt_data = login_attempts[client_ip]
        if attempt_data['attempts'] >= MAX_LOGIN_ATTEMPTS:
            # Check whether the block time has passed
            if datetime.now() < attempt_data['blocked_until']:
                return True
            else:
                # Reset once the block time has passed
                del login_attempts[client_ip]
        
        return False
    
    @staticmethod
    def record_failed_login(client_ip: str):
        """Record a failed login"""
        now = datetime.now()

        if client_ip not in login_attempts:
            login_attempts[client_ip] = {
                'attempts': 1,
                'first_attempt': now,
                'blocked_until': None
            }
        else:
            login_attempts[client_ip]['attempts'] += 1

        # Block once the maximum number of attempts is reached
        if login_attempts[client_ip]['attempts'] >= MAX_LOGIN_ATTEMPTS:
            login_attempts[client_ip]['blocked_until'] = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
    
    @staticmethod
    def clear_login_attempts(client_ip: str):
        """Reset the attempt record after a successful login"""
        if client_ip in login_attempts:
            del login_attempts[client_ip]
    
    @staticmethod
    def get_remaining_lockout_time(client_ip: str) -> Optional[int]:
        """Return the remaining block time (seconds)"""
        if client_ip not in login_attempts:
            return None
        
        attempt_data = login_attempts[client_ip]
        if attempt_data['blocked_until'] and datetime.now() < attempt_data['blocked_until']:
            remaining = (attempt_data['blocked_until'] - datetime.now()).total_seconds()
            return int(remaining)
        
        return None
    
    @staticmethod
    def verify_credentials(username: str, password: str) -> bool:
        """Verify user credentials"""
        if not AUTHENTICATION_ENABLED:
            return True  # always succeed when authentication is disabled
        
        return username == AUTH_USERNAME and password == AUTH_PASSWORD
    
    @staticmethod
    def create_access_token(data: Dict[str, Any]) -> str:
        """Create a JWT access token"""
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
        to_encode.update({"exp": expire})
        
        encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        return encoded_jwt
    
    @staticmethod
    def verify_token(token: str) -> Optional[Dict[str, Any]]:
        """Verify a JWT token"""
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
    
    @staticmethod
    def is_authentication_enabled() -> bool:
        """Check whether authentication is enabled"""
        return AUTHENTICATION_ENABLED

# FastAPI dependency functions
def get_current_user_optional(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[Dict[str, Any]]:
    """Get the current user info (optional)"""
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
    """Get the current user info (required)"""
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
    """Authentication-required decorator"""
    return user

# Convenience functions
auth_manager = AuthManager()