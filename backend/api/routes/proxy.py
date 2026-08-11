# -*- coding: utf-8 -*-
import asyncio
import datetime
from fastapi import APIRouter, Request, HTTPException, Depends, Body
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.db import get_db
from core import db_async
from core.i18n import get_message
from core.config import get_config
from core.models import DownloadRequest, StatusEnum, ProxyStatus, UserProxy
from core.proxy_manager import proxy_manager, detect_proxy_type

async def get_available_proxies(db):
    """Proxies that can be handed out right now.

    "Available" has to mean what the downloader means by it. This used to
    return proxies with no ProxyStatus row at all — i.e. never tried — so a
    single VPN that had recorded one failure counted as consumed forever and
    the UI announced "모든 프록시 소진" while that VPN sat idle and usable.

    The picker excludes a proxy only while its failure cooldown is running, so
    that is the question asked here, through the picker's own helper rather
    than a second copy of the rule.
    """
    try:
        proxy_list = await proxy_manager.get_user_proxy_list(db)
        cooling = await asyncio.to_thread(proxy_manager.cooling_addresses, db)
        return [addr for addr in proxy_list if addr not in cooling]
    except Exception as e:
        print(f"[ERROR] get_available_proxies failed: {e}")
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
def get_proxies(request: Request, db: Session = Depends(get_db)):
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
def add_proxy(request: Request, db: Session = Depends(get_db), data: dict = Body(...)):
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
def delete_proxy(proxy_id: int, request: Request, db: Session = Depends(get_db)):
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
def toggle_proxy(proxy_id: int, request: Request, db: Session = Depends(get_db)):
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


def _collect_proxy_counts(db: Session) -> dict:
    """Every counter this endpoint reports, in three grouped queries.

    It used to run seven separate COUNTs straight on the event loop while proxy
    downloads were committing progress to the same database. Grouping collapses
    the four per-status scans into one, and the whole thing runs in a single
    thread hop.
    """
    by_status = {
        status: n
        for status, n in db.query(DownloadRequest.status, func.count(DownloadRequest.id))
        .filter(DownloadRequest.use_proxy == True)
        .group_by(DownloadRequest.status)
        .all()
        if status is not None
    }

    # ``success`` is nullable, and the previous ``== True`` / ``== False``
    # filters both skipped NULL — grouping keeps that by only reading the two
    # boolean keys.
    by_success = dict(
        db.query(ProxyStatus.success, func.count(ProxyStatus.id))
        .group_by(ProxyStatus.success)
        .all()
    )

    used_proxies = db.query(func.count(ProxyStatus.id)).filter(
        ProxyStatus.ip.isnot(None),
        ProxyStatus.port.isnot(None),
    ).scalar() or 0

    return {
        "used_proxies": used_proxies,
        "success_count": by_success.get(True, 0),
        "fail_count": by_success.get(False, 0),
        "active_downloads": by_status.get(StatusEnum.downloading, 0)
        + by_status.get(StatusEnum.proxying, 0),
        "pending_downloads": by_status.get(StatusEnum.pending, 0),
        "parsing_downloads": by_status.get(StatusEnum.parsing, 0),
        "waiting_downloads": by_status.get(StatusEnum.waiting, 0),
    }


@router.get("/proxy-status")
async def get_proxy_status(request: Request, db: Session = Depends(get_db)):
    """Get proxy status"""
    try:
        # Use proxy_manager's cached proxy list
        cached_proxy_list = await proxy_manager.get_user_proxy_list(db)

        # Get overall proxy stats (no limit)
        total_proxies = len(cached_proxy_list)
        available_list = await get_available_proxies(db)
        available_proxies = len(available_list)

        print(f"[DEBUG] proxy_status: total={total_proxies}, available={available_proxies}")
        print(f"[DEBUG] cached_proxy_list: {cached_proxy_list[:3] if cached_proxy_list else 'None'}...")  # show only the first 3

        counts = await asyncio.to_thread(_collect_proxy_counts, db)
        used_proxies = counts["used_proxies"]
        success_count = counts["success_count"]
        fail_count = counts["fail_count"]
        active_proxy_downloads = counts["active_downloads"]
        pending_proxy_downloads = counts["pending_downloads"]
        parsing_proxy_downloads = counts["parsing_downloads"]
        waiting_proxy_downloads = counts["waiting_downloads"]

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
def check_proxy_availability(request: Request, db: Session = Depends(get_db)):
    """Check whether proxies are available"""
    try:
        proxies = get_user_proxy_list(db)
        available = len(proxies) > 0

        return {"available": available, "count": len(proxies)}

    except Exception as e:
        print(f"[ERROR] Check proxy availability failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/proxy-status/reset")
def reset_proxy_status(request: Request, db: Session = Depends(get_db)):
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
