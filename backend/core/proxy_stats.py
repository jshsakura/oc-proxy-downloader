from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .db import get_db
from .models import ProxyStatus
from .proxy_manager import get_user_proxy_list

router = APIRouter()

@router.get("/proxy-status")
def get_proxy_status(db: Session = Depends(get_db)):
    """프록시 상태 정보를 반환"""
    try:
        # 전체 프록시 개수 (사용자 프록시만)
        user_proxies = get_user_proxy_list(db)
        total_proxies = len(user_proxies)
        
        # 사용된 프록시 개수
        used_proxies = db.query(ProxyStatus).count()
        
        # 사용 가능한 프록시 개수
        available_proxies = max(0, total_proxies - used_proxies)
        
        # 성공/실패 통계
        success_count = db.query(ProxyStatus).filter(ProxyStatus.last_status == 'success').count()
        fail_count = db.query(ProxyStatus).filter(ProxyStatus.last_status == 'fail').count()
        
        return {
            "total_proxies": total_proxies,
            "available_proxies": available_proxies,
            "used_proxies": used_proxies,
            "success_count": success_count,
            "fail_count": fail_count
        }
    except Exception as e:
        print(f"[ERROR] 프록시 상태 조회 실패: {e}")
        return {
            "total_proxies": 0,
            "available_proxies": 0,
            "used_proxies": 0,
            "success_count": 0,
            "fail_count": 0
        }

@router.post("/proxy-status/reset")
def reset_proxy_status(db: Session = Depends(get_db)):
    """프록시 사용 기록 초기화 및 프록시 목록 재로드"""
    try:
        # 1. 기존 프록시 사용 기록 초기화
        db.query(ProxyStatus).delete()
        db.commit()
        print("[LOG] 프록시 사용 기록 초기화 완료")
        
        # 2. 프록시 목록 재로드 (새로운 프록시 목록 가져오기)
        try:
            print("[LOG] 프록시 목록 재로드 시작")
            # 사용자 프록시 목록 확인
            new_proxies = get_user_proxy_list(db)
            print(f"[LOG] {len(new_proxies)}개의 새로운 프록시 로드 완료")
        except Exception as reload_e:
            print(f"[LOG] 프록시 재로드 중 오류 (계속 진행): {reload_e}")
        
        # 3. 프록시 리셋을 WebSocket으로 알림
        try:
            import json
            from core.shared import status_queue
            status_queue.put(json.dumps({
                "type": "proxy_reset", 
                "data": {"message": "All proxies reset and reloaded"}
            }, ensure_ascii=False))
        except Exception as ws_e:
            print(f"[LOG] 프록시 리셋 WebSocket 알림 실패: {ws_e}")
        
        return {"message": "Proxy status reset and reloaded successfully"}
    except Exception as e:
        db.rollback()
        print(f"[ERROR] 프록시 리셋 실패: {e}")
        raise HTTPException(status_code=500, detail="Failed to reset proxy status")