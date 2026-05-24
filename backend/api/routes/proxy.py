# -*- coding: utf-8 -*-
import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, Body
from sqlalchemy.orm import Session

from core.db import get_db
from core.i18n import get_message
from core.config import get_config
from core.models import DownloadRequest, StatusEnum, ProxyStatus, UserProxy
from core.proxy_manager import proxy_manager, detect_proxy_type

# Compatibility functions
async def get_unused_proxies(db):
    """Return the list of unused proxies"""
    try:
        # Get the list of active user proxies (same approach as proxy_manager)
        cached_proxy_list = await proxy_manager.get_user_proxy_list(db)
        active_proxies = db.query(UserProxy).filter(UserProxy.is_active == True).all()

        # Proxy addresses actually used (checked from ProxyStatus)
        used_proxy_statuses = db.query(ProxyStatus).filter(
            ProxyStatus.ip.isnot(None),
            ProxyStatus.port.isnot(None)
        ).all()
        used_proxy_addresses = {f"{status.ip}:{status.port}" for status in used_proxy_statuses}

        # Filter unused proxies — use cached_proxy_list for consistency
        unused_proxies = []
        for individual_proxy in cached_proxy_list:
            if individual_proxy not in used_proxy_addresses:
                unused_proxies.append(individual_proxy)

        print(f"[DEBUG] get_unused_proxies: cached_total={len(cached_proxy_list)}, used={len(used_proxy_addresses)}, unused={len(unused_proxies)}")
        return unused_proxies
    except Exception as e:
        print(f"[ERROR] get_unused_proxies failed: {e}")
        return []

def get_user_proxy_list(db):
    """Parse the list of active user proxies into individual proxy addresses and return them"""
    proxies = db.query(UserProxy).filter(UserProxy.is_active == True).all()
    individual_proxies = []

    for proxy in proxies:
        # Parse comma-separated proxy addresses individually
        proxy_addresses = [addr.strip() for addr in proxy.address.split(',') if addr.strip()]
        individual_proxies.extend(proxy_addresses)

    return individual_proxies

def reset_proxy_usage(db):
    db.query(ProxyStatus).delete()
    db.commit()

async def test_proxy(address, timeout=15):
    """Test a proxy"""
    try:
        result = await proxy_manager.test_proxy_async(address, timeout)
        return result
    except Exception as e:
        print(f"[ERROR] test_proxy failed: {e}")
        return False
from sqlalchemy import desc

router = APIRouter(prefix="/api", tags=["proxy"])


@router.get("/proxies/")
async def get_proxies(request: Request, db: Session = Depends(get_db)):
    """Get the proxy list (returns only user-added proxy settings)"""
    try:
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
    """Add a proxy"""
    try:
        address = data.get("address", "").strip()
        description = data.get("description", "").strip()

        if not address:
            raise HTTPException(status_code=400, detail="프록시 주소가 필요합니다.")

        # Check whether the proxy already exists
        existing = db.query(UserProxy).filter(UserProxy.address == address).first()
        if existing:
            raise HTTPException(status_code=400, detail="이미 등록된 프록시입니다.")

        # Auto-detect the proxy type
        proxy_type = detect_proxy_type(address)

        # Create the new proxy
        new_proxy = UserProxy(
            address=address,
            proxy_type=proxy_type,
            is_active=True,
            added_at=datetime.datetime.now(),
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
    """Delete a proxy"""
    try:
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
    """Toggle a proxy active/inactive"""
    try:
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
    """Get proxy status"""
    try:
        # Use proxy_manager's cached proxy list
        cached_proxy_list = await proxy_manager.get_user_proxy_list(db)

        # Get overall proxy stats (no limit)
        total_proxies = len(cached_proxy_list)
        unused_proxies_list = await get_unused_proxies(db)
        available_proxies = len(unused_proxies_list)

        print(f"[DEBUG] proxy_status: total={total_proxies}, available={available_proxies}, unused_list={len(unused_proxies_list)}")
        print(f"[DEBUG] cached_proxy_list: {cached_proxy_list[:3] if cached_proxy_list else 'None'}...")  # show only the first 3

        # Number of proxies actually used (checked from the ProxyStatus table)
        used_proxy_count = db.query(ProxyStatus).filter(
            ProxyStatus.ip.isnot(None),
            ProxyStatus.port.isnot(None)
        ).count()
        used_proxies = used_proxy_count

        # Total success/failure counts (actual DB query)
        success_count = db.query(ProxyStatus).filter(ProxyStatus.success == True).count()
        fail_count = db.query(ProxyStatus).filter(ProxyStatus.success == False).count()

        # Current proxy download count (active states only)
        active_proxy_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.use_proxy == True,
            DownloadRequest.status.in_(
                [StatusEnum.downloading, StatusEnum.proxying])
        ).count()

        # Number of pending proxy downloads
        pending_proxy_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.use_proxy == True,
            DownloadRequest.status == StatusEnum.pending
        ).count()

        # Number of proxy downloads currently parsing
        parsing_proxy_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.use_proxy == True,
            DownloadRequest.status == StatusEnum.parsing
        ).count()

        # Number of proxy downloads waiting (waiting status)
        waiting_proxy_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.use_proxy == True,
            DownloadRequest.status == StatusEnum.waiting
        ).count()

        # Determine the proxy status message (i18n support)
        config = get_config()
        lang = config.get("language", "ko")

        # Total in-progress proxy downloads (includes parsing, active, waiting)
        total_active_proxy = parsing_proxy_downloads + active_proxy_downloads + waiting_proxy_downloads

        if total_active_proxy > 0:
            if parsing_proxy_downloads > 0:
                proxy_status = get_message("proxy_status_parsing", lang).format(count=parsing_proxy_downloads)
            elif active_proxy_downloads > 0:
                proxy_status = get_message("proxy_status_downloading", lang).format(count=active_proxy_downloads)
            elif waiting_proxy_downloads > 0:
                proxy_status = get_message("proxy_status_waiting", lang)
        elif pending_proxy_downloads > 0:
            proxy_status = get_message("proxy_status_pending", lang).format(count=pending_proxy_downloads)
        else:
            # No proxy downloads at all, or all are done/failed/stopped
            proxy_status = get_message("proxy_idle", lang)

        return {
            "total_proxies": total_proxies,
            "available_proxies": available_proxies,
            "used_proxies": used_proxies,
            "success_count": success_count,
            "fail_count": fail_count,
            "active_downloads": active_proxy_downloads,
            "pending_downloads": pending_proxy_downloads,
            "parsing_downloads": parsing_proxy_downloads,
            "waiting_downloads": waiting_proxy_downloads,
            "status_message": proxy_status
        }

    except Exception as e:
        print(f"[ERROR] Get proxy status failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/proxies/available")
async def check_proxy_availability(request: Request, db: Session = Depends(get_db)):
    """Check whether proxies are available"""
    try:
        proxies = get_user_proxy_list(db)
        available = len(proxies) > 0

        return {"available": available, "count": len(proxies)}

    except Exception as e:
        print(f"[ERROR] Check proxy availability failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/proxy-status/reset")
async def reset_proxy_status(request: Request, db: Session = Depends(get_db)):
    """Reset proxy status"""
    try:
        # Reset proxy usage
        reset_proxy_usage(db)

        # Delete proxy stats from the DB
        db.query(ProxyStatus).delete()
        db.commit()

        # Clear the proxy manager cache (reloads the proxy list on next request)
        proxy_manager.proxy_cache.clear()
        print(f"[LOG] 프록시 캐시 삭제됨 - 다음 요청 시 프록시 목록을 다시 가져옴")

        return {"success": True, "message": "프록시 상태가 리셋되었습니다."}

    except Exception as e:
        print(f"[ERROR] Reset proxy status failed: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
