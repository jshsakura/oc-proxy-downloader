# -*- coding: utf-8 -*-
import time
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse


async def log_requests(request: Request, call_next):
    """Request logging middleware"""
    start_time = time.time()

    # Request log
    print(f"[LOG] {request.method} {request.url}")

    try:
        response = await call_next(request)

        # Calculate response time
        process_time = time.time() - start_time

        # Response log (slow requests only)
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