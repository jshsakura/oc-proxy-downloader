"""
프록시 관리 모듈
- 프록시 목록 관리
- 프록시 상태 추적  
- 프록시 테스트
"""

import requests
import datetime
from sqlalchemy.orm import Session
from .common import get_all_proxies
from .models import ProxyStatus
from .db import get_db


def get_unused_proxies(db: Session):
    """사용하지 않은 프록시 목록 반환 (성공한 프록시 우선순위)"""
    # 이미 사용된 프록시 주소들 
    used_proxies = db.query(ProxyStatus).filter(
        ProxyStatus.ip.isnot(None),
        ProxyStatus.port.isnot(None)
    ).all()
    used_proxy_addresses = {f"{p.ip}:{p.port}" for p in used_proxies}
    
    # 전체 프록시에서 사용된 것들 제외
    all_proxies = get_all_proxies()
    unused_proxies = [p for p in all_proxies if p not in used_proxy_addresses]
    
    # 성공한 프록시들을 우선적으로 배치
    successful_proxies = db.query(ProxyStatus).filter(
        ProxyStatus.last_status == 'success'
    ).all()
    priority_proxies = [f"{p.ip}:{p.port}" for p in successful_proxies if f"{p.ip}:{p.port}" in unused_proxies]
    other_proxies = [p for p in unused_proxies if p not in priority_proxies]
    
    # 성공한 프록시를 앞에 배치
    final_proxies = priority_proxies + other_proxies
    
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


def test_proxy(proxy_addr, timeout=8):
    """프록시 연결 테스트 - 1fichier.com HTTPS 지원 여부 확인"""
    proxy_config = {
        "http": f"http://{proxy_addr}",
        "https": f"http://{proxy_addr}"
    }
    
    # 1단계: 간단한 HTTP 테스트
    try:
        response = requests.get("http://httpbin.org/ip", proxies=proxy_config, timeout=timeout)
        if response.status_code != 200:
            return False
    except Exception:
        return False
    
    # 2단계: HTTPS 터널링 테스트 (1fichier.com과 유사한 환경)
    try:
        response = requests.head("https://1fichier.com", proxies=proxy_config, timeout=timeout, verify=False)
        return response.status_code in [200, 301, 302, 403, 429]  # 연결은 되지만 차단될 수 있음
    except requests.exceptions.ProxyError as e:
        if "Tunnel connection failed" in str(e):
            return False  # HTTPS 터널링 미지원
        return False
    except Exception:
        return False


def get_working_proxy(db: Session, max_test=15):
    """작동하는 프록시 하나를 찾아서 반환"""
    unused_proxies = get_unused_proxies(db)
    
    for i, proxy_addr in enumerate(unused_proxies[:max_test]):
        print(f"[LOG] 프록시 테스트 {i+1}/{max_test}: {proxy_addr}")
        
        if test_proxy(proxy_addr, timeout=10):
            print(f"[LOG] 작동하는 프록시 발견: {proxy_addr}")
            return proxy_addr
            
        mark_proxy_used(db, proxy_addr, success=False)
    
    print(f"[LOG] {max_test}개 프록시 테스트 결과: 작동하는 프록시 없음")
    return None