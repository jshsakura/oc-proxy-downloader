# -*- coding: utf-8 -*-
import time
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse


async def log_requests(request: Request, call_next):
    """요청 로깅 미들웨어"""
    start_time = time.time()
    
    # 요청 로그
    print(f"[LOG] {request.method} {request.url}")
    
    try:
        response = await call_next(request)
        
        # 응답 시간 계산
        process_time = time.time() - start_time
        
        # 응답 로그 (긴 요청만)
        if process_time > 1.0:
            print(f"[LOG] {request.method} {request.url} - {response.status_code} ({process_time:.2f}s)")
            
        response.headers["X-Process-Time"] = str(process_time)
        return response
        
    except Exception as e:
        process_time = time.time() - start_time
        print(f"[ERROR] {request.method} {request.url} - Error: {e} ({process_time:.2f}s)")
        
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )