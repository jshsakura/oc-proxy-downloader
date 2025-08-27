"""
프록시 관리 모듈
- 프록시 목록 관리
- 프록시 상태 추적  
- 프록시 테스트
- 사용자 프록시 관리
"""

import requests
import datetime
import re
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from .models import ProxyStatus, UserProxy
from .db import get_db

# FastAPI 라우터
router = APIRouter()

class ProxyCreate(BaseModel):
    address: str
    description: str = ""

class ProxyResponse(BaseModel):
    id: int
    address: str
    proxy_type: str
    is_active: bool
    added_at: datetime.datetime
    last_used: Optional[datetime.datetime]
    description: Optional[str]

def detect_proxy_type(address: str) -> str:
    """프록시 주소 형태를 자동 감지"""
    # URL 형태인지 확인 (http:// 또는 https://로 시작)
    if address.startswith(('http://', 'https://')):
        return "list"
    
    # IP:PORT 형태인지 확인
    ip_port_pattern = r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d+$'
    if re.match(ip_port_pattern, address):
        return "single"
    
    # 도메인:PORT 형태
    domain_port_pattern = r'^[a-zA-Z0-9.-]+:\d+$'
    if re.match(domain_port_pattern, address):
        return "single"
    
    # 기본값은 list로 처리
    return "list"


def get_user_proxy_list(db: Session):
    """사용자가 추가한 프록시 목록을 가져와서 처리"""
    user_proxies = db.query(UserProxy).filter(UserProxy.is_active == True).all()
    proxy_list = []
    
    for user_proxy in user_proxies:
        if user_proxy.proxy_type == "single":
            # 개별 프록시 추가
            proxy_list.append(user_proxy.address)
        elif user_proxy.proxy_type == "list":
            # 프록시 목록 URL에서 프록시들 가져오기
            try:
                response = requests.get(user_proxy.address, timeout=10)
                if response.status_code == 200:
                    # 각 줄을 프록시로 처리
                    lines = response.text.strip().split('\n')
                    for line in lines:
                        line = line.strip()
                        if line and ':' in line:
                            # IP:PORT 형태인지 확인
                            if detect_proxy_type(line) == "single":
                                proxy_list.append(line)
                    print(f"[LOG] 프록시 목록 URL에서 {len(lines)} 개 프록시 로드: {user_proxy.address}")
                else:
                    print(f"[LOG] 프록시 목록 URL 접근 실패: {user_proxy.address} ({response.status_code})")
            except Exception as e:
                print(f"[LOG] 프록시 목록 URL 처리 실패: {user_proxy.address} -> {e}")
    
    return proxy_list

def get_unused_proxies(db: Session):
    """사용하지 않은 프록시 목록 반환 (사용자 프록시만)"""
    # 사용자가 추가한 프록시들만 사용
    user_proxy_list = get_user_proxy_list(db)
    
    # 전체 프록시 목록 (사용자 프록시만)
    all_proxies = user_proxy_list
    
    # 4. 이미 사용된 프록시 주소들 
    used_proxies = db.query(ProxyStatus).filter(
        ProxyStatus.ip.isnot(None),
        ProxyStatus.port.isnot(None)
    ).all()
    used_proxy_addresses = {f"{p.ip}:{p.port}" for p in used_proxies}
    
    # 5. 전체 프록시에서 사용된 것들 제외
    unused_proxies = [p for p in all_proxies if p not in used_proxy_addresses]
    
    # 성공한 프록시들을 우선적으로 배치
    successful_proxies = db.query(ProxyStatus).filter(
        ProxyStatus.last_status == 'success'
    ).all()
    priority_proxies = [f"{p.ip}:{p.port}" for p in successful_proxies if f"{p.ip}:{p.port}" in unused_proxies]
    other_proxies = [p for p in unused_proxies if p not in priority_proxies]
    
    # 성공한 프록시를 앞에 배치
    final_proxies = priority_proxies + other_proxies
    
    print(f"[LOG] 사용자 프록시: {len(user_proxy_list)}개")
    print(f"[LOG] 전체 프록시: {len(all_proxies)}개, 사용된 프록시: {len(used_proxy_addresses)}개")
    print(f"[LOG] 미사용 프록시: {len(unused_proxies)}개 (우선순위: {len(priority_proxies)}개)")
    
    return final_proxies


def mark_proxy_used(db: Session, proxy_addr: str, success: bool):
    """프록시 사용 결과를 데이터베이스에 기록"""
    try:
        if ':' not in proxy_addr:
            print(f"[LOG] 잘못된 프록시 주소 형식: {proxy_addr}")
            return
            
        ip, port = proxy_addr.strip().split(':', 1)
        
        # 기존 레코드 확인
        existing = db.query(ProxyStatus).filter(
            ProxyStatus.ip == ip,
            ProxyStatus.port == int(port)
        ).first()
        
        if existing:
            # 기존 레코드 업데이트
            existing.last_status = 'success' if success else 'fail'
            existing.success = success  # 호환성을 위해 추가
            existing.last_used_at = datetime.datetime.now()
        else:
            # 새 레코드 생성
            new_record = ProxyStatus(
                ip=ip,
                port=int(port),
                last_status='success' if success else 'fail',
                success=success,  # 호환성을 위해 추가
                last_used_at=datetime.datetime.now()
            )
            db.add(new_record)
        
        db.commit()
        status_text = "성공" if success else "실패"
        # print(f"[LOG] 프록시 {proxy_addr} 사용 결과 기록: {status_text}")
        
    except Exception as e:
        print(f"[LOG] 프록시 사용 기록 실패 ({proxy_addr}): {e}")
        db.rollback()


def reset_proxy_usage(db: Session):
    """프록시 사용 기록 초기화"""
    try:
        deleted_count = db.query(ProxyStatus).delete()
        db.commit()
        print(f"[LOG] 프록시 사용 기록 {deleted_count}개 초기화 완료")
    except Exception as e:
        print(f"[LOG] 프록시 사용 기록 초기화 실패: {e}")
        db.rollback()


def test_proxy(proxy_addr, timeout=3):
    """프록시 연결 테스트 - CloudScraper와 동일한 환경으로 테스트"""
    import cloudscraper
    
    proxy_config = {
        "http": f"http://{proxy_addr}",
        "https": f"http://{proxy_addr}"
    }
    
    # CloudScraper로 실제 파싱과 동일한 환경에서 테스트
    try:
        scraper = cloudscraper.create_scraper()
        scraper.verify = False
        response = scraper.head("https://1fichier.com", proxies=proxy_config, timeout=timeout)
        return response.status_code in [200, 301, 302, 403, 429]
    except Exception as e:
        # 모든 예외는 실패로 처리 (빠른 필터링)
        return False


def get_working_proxy(db: Session, max_test=15):
    """작동하는 프록시 하나를 찾아서 반환"""
    unused_proxies = get_unused_proxies(db)
    
    for i, proxy_addr in enumerate(unused_proxies[:max_test]):
        print(f"[LOG] 프록시 테스트 {i+1}/{max_test}: {proxy_addr}")
        
        if test_proxy(proxy_addr, timeout=3):
            print(f"[LOG] 작동하는 프록시 발견: {proxy_addr}")
            return proxy_addr
            
        mark_proxy_used(db, proxy_addr, success=False)
    
    print(f"[LOG] {max_test}개 프록시 테스트 결과: 작동하는 프록시 없음")
    return None


# ==================== 사용자 프록시 관리 API ====================

@router.get("/proxies", response_model=List[ProxyResponse])
def get_user_proxies(db: Session = Depends(get_db)):
    """사용자 프록시 목록 조회"""
    proxies = db.query(UserProxy).order_by(UserProxy.added_at.desc()).all()
    return proxies

@router.post("/proxies", response_model=ProxyResponse)
def add_user_proxy(proxy: ProxyCreate, db: Session = Depends(get_db)):
    """사용자 프록시 추가"""
    
    # 중복 체크
    existing = db.query(UserProxy).filter(UserProxy.address == proxy.address).first()
    if existing:
        raise HTTPException(status_code=400, detail="이미 등록된 프록시 주소입니다")
    
    # 프록시 타입 자동 감지
    proxy_type = detect_proxy_type(proxy.address)
    
    # 프록시 유효성 검증 (선택적)
    if proxy_type == "list":
        try:
            # URL 형태인 경우 접근 가능한지 확인
            response = requests.head(proxy.address, timeout=5)
            print(f"[LOG] 프록시 목록 URL 검증: {proxy.address} -> {response.status_code}")
        except Exception as e:
            print(f"[LOG] 프록시 목록 URL 검증 실패: {proxy.address} -> {e}")
            # 검증 실패해도 추가는 허용
    
    # DB에 저장
    db_proxy = UserProxy(
        address=proxy.address,
        proxy_type=proxy_type,
        description=proxy.description,
        is_active=True
    )
    
    db.add(db_proxy)
    db.commit()
    db.refresh(db_proxy)
    
    print(f"[LOG] 사용자 프록시 추가: {proxy.address} (타입: {proxy_type})")
    return db_proxy

@router.delete("/proxies/{proxy_id}")
def delete_user_proxy(proxy_id: int, db: Session = Depends(get_db)):
    """사용자 프록시 삭제"""
    
    proxy = db.query(UserProxy).filter(UserProxy.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="프록시를 찾을 수 없습니다")
    
    db.delete(proxy)
    db.commit()
    
    print(f"[LOG] 사용자 프록시 삭제: {proxy.address}")
    return {"message": "프록시가 삭제되었습니다"}

@router.put("/proxies/{proxy_id}/toggle")
def toggle_user_proxy(proxy_id: int, db: Session = Depends(get_db)):
    """사용자 프록시 활성/비활성 토글"""
    
    proxy = db.query(UserProxy).filter(UserProxy.id == proxy_id).first()
    if not proxy:
        raise HTTPException(status_code=404, detail="프록시를 찾을 수 없습니다")
    
    proxy.is_active = not proxy.is_active
    db.commit()
    db.refresh(proxy)
    
    status = "활성화" if proxy.is_active else "비활성화"
    print(f"[LOG] 사용자 프록시 {status}: {proxy.address}")
    
    return proxy

@router.get("/proxies/available")
def check_proxy_availability(db: Session = Depends(get_db)):
    """프록시 사용 가능 여부 확인"""
    active_proxies = db.query(UserProxy).filter(UserProxy.is_active == True).count()
    return {"available": active_proxies > 0, "count": active_proxies}