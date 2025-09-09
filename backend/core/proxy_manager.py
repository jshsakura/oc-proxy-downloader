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
from .models import ProxyStatus, UserProxy, StatusEnum
from .db import get_db

# FastAPI 라우터
router = APIRouter()

# 프록시 목록 캐시 (URL -> (프록시 목록, 캐시 시간))
import time
_proxy_list_cache = {}

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
            # 캐시 확인 (5분간 유효)
            cache_key = user_proxy.address
            current_time = time.time()
            
            if (cache_key in _proxy_list_cache and 
                current_time - _proxy_list_cache[cache_key][1] < 300):  # 5분
                cached_proxies = _proxy_list_cache[cache_key][0]
                proxy_list.extend(cached_proxies)
                print(f"[LOG] 프록시 목록 캐시 사용: {len(cached_proxies)}개 - {user_proxy.address}")
            else:
                # 프록시 목록 URL에서 프록시들 가져오기
                try:
                    response = requests.get(user_proxy.address, timeout=10)
                    if response.status_code == 200:
                        # 각 줄을 프록시로 처리
                        lines = response.text.strip().split('\n')
                        url_proxies = []
                        for line in lines:
                            line = line.strip()
                            if line and ':' in line:
                                # IP:PORT 형태인지 확인
                                if detect_proxy_type(line) == "single":
                                    url_proxies.append(line)
                        
                        # 캐시에 저장
                        _proxy_list_cache[cache_key] = (url_proxies, current_time)
                        proxy_list.extend(url_proxies)
                        print(f"[LOG] 프록시 목록 URL에서 {len(url_proxies)} 개 프록시 로드 (캐시됨): {user_proxy.address}")
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
        
        current_time = datetime.datetime.now()
        
        if existing:
            # 기존 레코드 업데이트
            existing.last_status = 'success' if success else 'fail'
            existing.success = success  # 호환성을 위해 추가
            existing.last_used_at = current_time
            if not success:
                existing.last_failed_at = current_time
        else:
            # 새 레코드 생성
            new_record = ProxyStatus(
                ip=ip,
                port=int(port),
                last_status='success' if success else 'fail',
                success=success,  # 호환성을 위해 추가
                last_used_at=current_time,
                last_failed_at=current_time if not success else None
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

def reset_recent_failed_proxies(db: Session, hours_back: int = 1):
    """최근 실패한 프록시만 초기화 (재시작 복구용)"""
    try:
        import datetime
        cutoff_time = datetime.datetime.now() - datetime.timedelta(hours=hours_back)
        
        # 최근 1시간 이내에 실패한 프록시들만 삭제
        deleted_count = db.query(ProxyStatus).filter(
            ProxyStatus.last_status == 'fail',
            ProxyStatus.last_failed_at >= cutoff_time
        ).delete()
        
        db.commit()
        print(f"[LOG] 최근 {hours_back}시간 이내 실패 프록시 {deleted_count}개 초기화 완료")
    except Exception as e:
        print(f"[LOG] 최근 실패 프록시 초기화 실패: {e}")
        db.rollback()


def test_proxy(proxy_addr, timeout=15, lenient_mode=False):
    """프록시 연결 테스트 - 실제 파싱과 동일한 조건으로 테스트
    
    Args:
        proxy_addr: 프록시 주소 (IP:PORT)
        timeout: 타임아웃 (초)
        lenient_mode: 관대한 모드 (재시작 직후 등에 사용, 간단한 연결 테스트만)
    """
    import cloudscraper
    import ssl
    import urllib3
    
    # SSL 경고 무시
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    # 1fichier는 HTTPS만 지원하므로 HTTPS 프록시만 테스트
    proxy_config = {
        "http": f"http://{proxy_addr}",
        "https": f"http://{proxy_addr}"
    }
    
    try:
        if lenient_mode:
            # 관대한 모드: 간단한 HTTP 연결 테스트만 수행 (재시작 직후용)
            print(f"[DEBUG] 프록시 {proxy_addr} 간단 연결 테스트 (관대한 모드)")
            
            import requests
            proxy_config = {
                "http": f"http://{proxy_addr}",
                "https": f"http://{proxy_addr}"
            }
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            # 더 간단한 테스트 URL (google.com 대신 httpbin.org 사용)
            response = requests.get(
                "http://httpbin.org/ip", 
                proxies=proxy_config, 
                headers=headers,
                timeout=8  # 더 짧은 타임아웃
            )
            
            if response.status_code == 200 and 'origin' in response.text:
                print(f"[LOG] ✅ 간단 연결 테스트 성공: {proxy_addr}")
                return True
            else:
                print(f"[LOG] ❌ 간단 연결 테스트 실패: {proxy_addr} (상태: {response.status_code})")
                return False
        
        print(f"[DEBUG] 프록시 {proxy_addr} HTTPS 터널 테스트")
        
        # 실제 파싱에서 사용하는 것과 동일한 CloudScraper 설정
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            },
            delay=1
        )
        scraper.verify = False
        
        # SSL 컨텍스트 설정 (파싱 서비스와 동일)
        from requests.adapters import HTTPAdapter
        from urllib3.util.ssl_ import create_urllib3_context
        
        class NoSSLVerifyHTTPAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                context = create_urllib3_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                kwargs['ssl_context'] = context
                return super().init_poolmanager(*args, **kwargs)
        
        scraper.mount('https://', NoSSLVerifyHTTPAdapter())
        
        # 파싱 서비스와 동일한 헤더 설정
        import random
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0'
        ]
        
        headers = {
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'DNT': '1'
        }
        
        # 실제 1fichier 파일 URL 패턴에 GET 요청 (실제 파싱과 동일한 조건)
        # 터널 테스트에서도 CloudScraper가 정상 작동하는지 확인
        response = scraper.get(
            "https://1fichier.com/", 
            proxies=proxy_config, 
            headers=headers,
            timeout=(10, 30)  # 파싱 서비스와 동일한 타임아웃
        )
        
        print(f"[DEBUG] 프록시 {proxy_addr} HTTPS 터널 응답: {response.status_code}")
        
        # CloudScraper 처리 가능한 응답 코드들 (실제 파싱과 동일한 기준)
        success_codes = [200, 301, 302, 403, 429, 404, 503]
        if response.status_code in success_codes:
            # 응답 내용이 있는지 확인 (빈 응답이면 프록시 문제)
            if len(response.text) > 100:  # 최소한의 HTML 내용이 있어야 함
                print(f"[LOG] ✅ HTTPS 터널 작동: {proxy_addr}")
                return True
            else:
                print(f"[LOG] ❌ 터널 실패: {proxy_addr} (응답 내용 없음)")
                return False
        else:
            print(f"[LOG] ❌ 터널 실패: {proxy_addr} (응답 코드: {response.status_code})")
            return False
            
    except (requests.exceptions.ProxyError, 
            requests.exceptions.ConnectTimeout, 
            requests.exceptions.ReadTimeout) as e:
        error_msg = str(e)
        if "Tunnel connection failed" in error_msg or "400 Bad Request" in error_msg:
            print(f"[LOG] ❌ HTTPS 터널 실패: {proxy_addr}")
        elif "Unable to connect to proxy" in error_msg:
            print(f"[LOG] ❌ 프록시 연결 불가: {proxy_addr}")
        else:
            print(f"[LOG] ❌ 터널 테스트 실패: {proxy_addr} ({str(e)[:100]})")
        return False
    except Exception as e:
        print(f"[LOG] ❌ 터널 테스트 오류: {proxy_addr} ({str(e)[:100]})")
        return False


def test_proxy_batch(db: Session, batch_proxies, req=None, lenient_mode=False):
    """주어진 프록시 배치를 병렬 테스트해서 성공한 것들을 반환"""
    
    if not batch_proxies:
        print(f"[LOG] 테스트할 프록시가 없음")
        return [], []

    mode_text = " (관대한 모드)" if lenient_mode else ""
    print(f"[LOG] {len(batch_proxies)}개 프록시 병렬 테스트 시작{mode_text}... (캐시된 목록 사용)")
    
    # 요청이 있는 경우 정지 상태 체크 (즉시 정지 플래그 + DB 상태)
    if req:
        from .shared import download_manager
        if download_manager.is_download_stopped(req.id):
            print(f"[LOG] 프록시 테스트 중 즉시 정지 플래그 감지: {req.id}")
            return [], []
        
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 프록시 테스트 중 정지됨: {req.id}")
            return [], []
    
    working_proxies = []
    failed_proxies = []
    
    # 병렬 테스트 함수 (지연 포함)
    def test_single_proxy(proxy_addr):
        try:
            # 연속 요청 방지를 위한 랜덤 지연 (0.5~1.5초)
            import time
            import random
            delay = random.uniform(0.5, 1.5)
            time.sleep(delay)
            
            if test_proxy(proxy_addr, timeout=10, lenient_mode=lenient_mode):
                return proxy_addr, True
            else:
                return proxy_addr, False
        except Exception as e:
            print(f"[LOG] 프록시 {proxy_addr} 테스트 중 오류: {e}")
            return proxy_addr, False
    
    # ThreadPoolExecutor로 병렬 실행
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    
    with ThreadPoolExecutor(max_workers=min(len(batch_proxies), 10)) as executor:
        # 모든 프록시 테스트를 동시에 시작
        future_to_proxy = {executor.submit(test_single_proxy, proxy): proxy for proxy in batch_proxies}
        
        for future in as_completed(future_to_proxy):
            proxy_addr, is_working = future.result()
            
            if is_working:
                working_proxies.append(proxy_addr)
                print(f"[LOG] ✅ 작동 프록시: {proxy_addr}")
            else:
                failed_proxies.append(proxy_addr)
                print(f"[LOG] ❌ 실패 프록시: {proxy_addr}")
    
    # 배치 테스트 중에는 실패한 프록시를 DB에 기록하지 않음 (캐시 유지를 위해)
    print(f"[LOG] 배치 테스트 완료: 성공 {len(working_proxies)}개, 실패 {len(failed_proxies)}개")
    return working_proxies, failed_proxies  # 실패한 프록시도 반환

def get_working_proxy_batch(db: Session, batch_size=10, req=None):
    """배치 단위로 프록시를 병렬 테스트해서 성공한 것들을 반환 (기존 호환성)"""
    unused_proxies = get_unused_proxies(db)
    
    if not unused_proxies:
        print(f"[LOG] 사용 가능한 프록시가 없음")
        return []
    
    batch_proxies = unused_proxies[:batch_size]
    print(f"[LOG] {len(batch_proxies)}개 프록시 병렬 테스트 시작...")
    
    # 요청이 있는 경우 정지 상태 체크 (즉시 정지 플래그 + DB 상태)
    if req:
        from .shared import download_manager
        if download_manager.is_download_stopped(req.id):
            print(f"[LOG] 프록시 테스트 중 즉시 정지 플래그 감지: {req.id}")
            return []
        
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 프록시 테스트 중 정지됨: {req.id}")
            return []
    
    working_proxies = []
    failed_proxies = []
    
    # 병렬 테스트 함수 (지연 포함)
    def test_single_proxy(proxy_addr):
        try:
            # 연속 요청 방지를 위한 랜덤 지연 (0.5~1.5초)
            import time
            import random
            delay = random.uniform(0.5, 1.5)
            time.sleep(delay)
            
            if test_proxy(proxy_addr, timeout=10, lenient_mode=lenient_mode):
                return proxy_addr, True
            else:
                return proxy_addr, False
        except Exception as e:
            print(f"[LOG] 프록시 {proxy_addr} 테스트 중 오류: {e}")
            return proxy_addr, False
    
    # ThreadPoolExecutor로 병렬 실행
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    
    with ThreadPoolExecutor(max_workers=min(batch_size, 10)) as executor:
        # 모든 프록시 테스트를 동시에 시작
        future_to_proxy = {executor.submit(test_single_proxy, proxy): proxy for proxy in batch_proxies}
        
        for future in as_completed(future_to_proxy):
            proxy_addr, is_working = future.result()
            
            if is_working:
                working_proxies.append(proxy_addr)
                print(f"[LOG] ✅ 작동 프록시: {proxy_addr}")
            else:
                failed_proxies.append(proxy_addr)
                print(f"[LOG] ❌ 실패 프록시: {proxy_addr}")
    
    # 실패한 프록시들을 사용됨으로 표시
    for failed_proxy in failed_proxies:
        mark_proxy_used(db, failed_proxy, success=False)
    
    print(f"[LOG] 배치 테스트 완료: 성공 {len(working_proxies)}개, 실패 {len(failed_proxies)}개")
    return working_proxies

def get_working_proxy(db: Session, max_test=15, req=None):
    """기존 호환성을 위한 래퍼 - 배치 테스트에서 첫 번째 성공한 프록시 반환"""
    working_proxies = get_working_proxy_batch(db, batch_size=max_test, req=req)
    return working_proxies[0] if working_proxies else None


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