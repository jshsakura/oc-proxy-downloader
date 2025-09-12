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
    """프록시 목록 조회 (사용자가 추가한 프록시 설정만 반환)"""
    try:
        from core.models import UserProxy
        user_proxies = db.query(UserProxy).all()
        
        proxies = []
        for proxy in user_proxies:
            proxies.append({
                "id": proxy.id,
                "address": proxy.address,
                "proxy_type": proxy.proxy_type,
                "is_active": proxy.is_active,
                "added_at": proxy.added_at.isoformat() if proxy.added_at else None,
                "last_used": proxy.last_used.isoformat() if proxy.last_used else None,
                "description": proxy.description
            })
        
        return {"proxies": proxies}
    except Exception as e:
        print(f"[ERROR] Get proxies failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/proxies")
async def add_proxy(request: Request, db: Session = Depends(get_db), data: dict = Body(...)):
    """프록시 추가"""
    try:
        from core.models import UserProxy
        from core.proxy_manager import detect_proxy_type
        import datetime
        
        address = data.get("address", "").strip()
        description = data.get("description", "").strip()
        
        if not address:
            raise HTTPException(status_code=400, detail="프록시 주소가 필요합니다.")
        
        # 이미 존재하는 프록시인지 확인
        existing = db.query(UserProxy).filter(UserProxy.address == address).first()
        if existing:
            raise HTTPException(status_code=400, detail="이미 등록된 프록시입니다.")
        
        # 프록시 타입 자동 감지
        proxy_type = detect_proxy_type(address)
        
        # 새 프록시 생성
        new_proxy = UserProxy(
            address=address,
            proxy_type=proxy_type,
            is_active=True,
            added_at=datetime.datetime.utcnow(),
            description=description
        )
        
        db.add(new_proxy)
        db.commit()
        db.refresh(new_proxy)
        
        return {"success": True, "message": f"프록시가 추가되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Add proxy failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/proxies/{proxy_id}")
async def delete_proxy(proxy_id: int, request: Request, db: Session = Depends(get_db)):
    """프록시 삭제"""
    try:
        from core.models import UserProxy
        
        proxy = db.query(UserProxy).filter(UserProxy.id == proxy_id).first()
        if not proxy:
            raise HTTPException(status_code=404, detail="프록시를 찾을 수 없습니다.")
        
        db.delete(proxy)
        db.commit()
        
        return {"success": True, "message": "프록시가 삭제되었습니다."}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Delete proxy failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/proxies/{proxy_id}/toggle")
async def toggle_proxy(proxy_id: int, request: Request, db: Session = Depends(get_db)):
    """프록시 활성/비활성 토글"""
    try:
        from core.models import UserProxy
        
        proxy = db.query(UserProxy).filter(UserProxy.id == proxy_id).first()
        if not proxy:
            raise HTTPException(status_code=404, detail="프록시를 찾을 수 없습니다.")
        
        proxy.is_active = not proxy.is_active
        db.commit()
        
        return {"success": True, "is_active": proxy.is_active}
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Toggle proxy failed: {e}")
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
        
        # 대기 중인 프록시 다운로드 개수
        pending_proxy_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.use_proxy == True,
            DownloadRequest.status == StatusEnum.pending
        ).count()
        
        # 프록시 파싱 중인 다운로드 개수
        parsing_proxy_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.use_proxy == True,
            DownloadRequest.status == StatusEnum.parsing
        ).count()
        
        # 프록시 상태 메시지 결정
        if active_proxy_downloads > 0:
            if parsing_proxy_downloads > 0:
                proxy_status = f"파싱 중 ({parsing_proxy_downloads}개)"
            else:
                proxy_status = f"다운로드 중 ({active_proxy_downloads}개)"
        elif pending_proxy_downloads > 0:
            proxy_status = f"대기 중 ({pending_proxy_downloads}개)"
        else:
            proxy_status = "대기 중..."

        return {
            "total_proxies": total_proxies,
            "available_proxies": available_proxies,
            "used_proxies": used_proxies,
            "success_count": success_count,
            "fail_count": fail_count,
            "active_downloads": active_proxy_downloads,
            "pending_downloads": pending_proxy_downloads,
            "parsing_downloads": parsing_proxy_downloads,
            "status_message": proxy_status
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
