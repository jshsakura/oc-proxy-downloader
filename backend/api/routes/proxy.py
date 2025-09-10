# -*- coding: utf-8 -*-
from fastapi import APIRouter, Request, HTTPException, Depends, Body
from sqlalchemy.orm import Session

from core.db import get_db
from core.models import DownloadRequest, StatusEnum, ProxyStatus
from core.proxy_manager import (
    get_unused_proxies,
    get_user_proxy_list,
    reset_proxy_usage,
    test_proxy
)
from sqlalchemy import desc

router = APIRouter(prefix="/api", tags=["proxy"])


@router.get("/proxies/")
async def get_proxies(request: Request, db: Session = Depends(get_db)):
    """프록시 목록 조회"""
    try:
        proxies = get_user_proxy_list(db)
        return {"proxies": proxies}
    except Exception as e:
        print(f"[ERROR] Get proxies failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/proxies/")
async def add_proxy(request: Request, proxy: str = Body(..., embed=True)):
    """프록시 추가"""
    try:
        # 프록시 추가 로직 (기존 main.py에서 이동)
        # TODO: 실제 프록시 추가 구현

        return {"success": True, "message": f"프록시 {proxy}가 추가되었습니다."}
    except Exception as e:
        print(f"[ERROR] Add proxy failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/proxies/")
async def delete_proxy(request: Request, proxy: str = Body(..., embed=True)):
    """프록시 삭제"""
    try:
        # 프록시 삭제 로직 (기존 main.py에서 이동)
        # TODO: 실제 프록시 삭제 구현

        return {"success": True, "message": f"프록시 {proxy}가 삭제되었습니다."}
    except Exception as e:
        print(f"[ERROR] Delete proxy failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/proxy-status")
async def get_proxy_status(request: Request, db: Session = Depends(get_db)):
    """프록시 상태 조회"""
    try:
        proxies = get_user_proxy_list(db)

        # 최근 프록시 통계 조회
        recent_stats = db.query(ProxyStatus).order_by(
            desc(ProxyStatus.last_used_at)).limit(100).all()

        total_proxies = len(proxies)
        available_proxies = len(get_unused_proxies(db))
        used_proxies = total_proxies - available_proxies

        success_count = len([s for s in recent_stats if s.success])
        fail_count = len([s for s in recent_stats if not s.success])

        # 현재 프록시 다운로드 개수
        active_proxy_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.use_proxy == True,
            DownloadRequest.status.in_(
                [StatusEnum.downloading, StatusEnum.proxying])
        ).count()

        return {
            "total_proxies": total_proxies,
            "available_proxies": available_proxies,
            "used_proxies": used_proxies,
            "success_count": success_count,
            "fail_count": fail_count,
            "active_downloads": active_proxy_downloads
        }

    except Exception as e:
        print(f"[ERROR] Get proxy status failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/proxies/available")
async def check_proxy_availability(request: Request, db: Session = Depends(get_db)):
    """프록시 사용 가능 여부 확인"""
    try:
        proxies = get_user_proxy_list(db)
        available = len(proxies) > 0

        return {"available": available, "count": len(proxies)}

    except Exception as e:
        print(f"[ERROR] Check proxy availability failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/proxy-status/reset")
async def reset_proxy_status(request: Request, db: Session = Depends(get_db)):
    """프록시 상태 리셋"""
    try:
        # 프록시 사용량 리셋
        reset_proxy_usage(db)

        # DB의 프록시 통계 삭제
        db.query(ProxyStatus).delete()
        db.commit()

        return {"success": True, "message": "프록시 상태가 리셋되었습니다."}

    except Exception as e:
        print(f"[ERROR] Reset proxy status failed: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
