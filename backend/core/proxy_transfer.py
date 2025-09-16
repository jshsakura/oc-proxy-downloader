"""
프록시 다운로드 서비스
- 프록시를 통한 파일 다운로드
- 프록시 순환 기능
- 실시간 진행률 업데이트
"""

import httpx
import time
from pathlib import Path
from urllib.parse import unquote
from .models import StatusEnum
from .proxy_manager import get_unused_proxies, mark_proxy_used
from utils.sse import send_sse_message
from services.download_manager import download_manager
from utils.file_helpers import (
    extract_filename_from_headers,
    calculate_total_size,
    download_file_content,
    validate_downloaded_file,
    check_file_resume_status
)


async def download_with_proxy(direct_link, file_path, proxy_addr, initial_size, req, db):
    """지정된 프록시로 다운로드 (비동기)"""
    print(f"[LOG] 프록시 다운로드 시작 - Download ID: {req.id}, Proxy: {proxy_addr}")
    
    # 파일 상태 검사
    file_status, current_file_size = check_file_resume_status(file_path, initial_size, req)
    
    if file_status == "completed":
        print(f"[LOG] 프록시: 파일이 이미 완료되었습니다: {file_path}")
        req.status = StatusEnum.done
        req.downloaded_size = current_file_size
        req.total_size = current_file_size
        db.commit()
        return
    
    req._last_sse_send_time = 0
    
    # 프록시 설정
    proxies = {
        'http': proxy_addr,
        'https': proxy_addr
    } if proxy_addr else None
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Accept-Language': 'ko-KR,ko;q=0.9',
        'Connection': 'keep-alive'
    }
    
    if initial_size > 0:
        headers['Range'] = f'bytes={initial_size}-'
        print(f"[LOG] 프록시 이어받기 시도: {initial_size} bytes부터")
    
    db.refresh(req)
    if req.status == StatusEnum.stopped:
        print(f"[LOG] 프록시 다운로드 시작 전 정지됨: {req.id}")
        return
    
    print(f"[LOG] 프록시 연결로 다운로드 시작: {proxy_addr}")
    
    timeout = httpx.Timeout(15.0, read=90.0)
    proxy_url = proxies['http'] if proxies else None
    
    # 압축 완전 비활성화를 위한 설정
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    async with httpx.AsyncClient(
        follow_redirects=True,
        proxy=proxy_url,
        limits=limits
    ) as client:
        try:
            async with client.stream('GET', direct_link, headers=headers, timeout=timeout) as response:
                if initial_size > 0 and response.status_code not in [206, 200]:
                    print(f"[LOG] 프록시 Range 요청 실패 (status: {response.status_code}), 처음부터 다시 시작")
                    initial_size = 0
                    if file_path.exists():
                        file_path.unlink()
                        print(f"[LOG] 기존 파일 삭제: {file_path}")
                
                response.raise_for_status()
                
                content_length = int(response.headers.get('Content-Length', 0))
                content_type = response.headers.get('Content-Type', '').lower()
                
                print(f"[DEBUG] 프록시 응답 헤더 Content-Type: {content_type}")
                
                db.refresh(req)
                if req.status == StatusEnum.stopped:
                    print(f"[LOG] 프록시 응답 받은 후 정지됨: {req.id}")
                    return
                
                extract_filename_from_headers(response, req, db)
                
                total_size = calculate_total_size(initial_size, content_length)
                req.total_size = total_size
                db.commit()
                
                print(f"[LOG] 프록시 다운로드 시작 - 총 크기: {total_size} bytes")
                
                download_path = Path(file_path).parent
                download_path.mkdir(parents=True, exist_ok=True)
                print(f"[LOG] 파일 저장 경로: {file_path}")
                
                downloaded = await download_file_content(
                    response, file_path, initial_size, total_size, req, db
                )
                
                print(f"[LOG] 프록시 다운로드 완료: {downloaded} bytes")
                
                validate_downloaded_file(downloaded, content_type, file_path)
                
        except Exception as proxy_error:
            error_msg = str(proxy_error)
            print(f"[ERROR] 프록시 다운로드 중 오류: {error_msg}")
            
            # 이어받기를 시도했던 경우에만 파일 정리
            if initial_size > 0 and file_path.exists():
                print(f"[LOG] 프록시: 이어받기 실패로 파일 삭제 후 새로 시작: {file_path}")
                try:
                    file_path.unlink()
                    print(f"[LOG] 프록시: 이어받기 실패 파일 삭제 완료")
                except Exception as cleanup_error:
                    print(f"[LOG] 프록시: 파일 삭제 실패 (무시): {cleanup_error}")
                print(f"[LOG] 프록시: 이어받기 포기 - 새로운 다운로드로 재시도됩니다")
            else:
                print(f"[LOG] 프록시: 새 다운로드 시도 중 오류 발생")
            
            # 압축 해제 오류 처리
            if "decompressing" in error_msg.lower() or "invalid block type" in error_msg.lower():
                print(f"[ERROR] 압축 해제 오류 - 서버에서 잘못된 데이터를 전송했습니다")
                raise Exception(f"서버 압축 데이터 오류: {error_msg}")
            elif "stream" in error_msg.lower() and "closed" in error_msg.lower():
                print(f"[ERROR] 스트림 연결 중단 - 네트워크 문제입니다")
                raise Exception(f"네트워크 연결 오류: {error_msg}")
            else:
                # 기타 오류는 그대로 전달
                raise proxy_error


async def download_with_proxy_cycling(direct_link, file_path, preferred_proxy, initial_size, req, db):
    """프록시를 순환하면서 다운로드 - 실패시 자동으로 다음 프록시로 이동 (비동기)"""
    
    print(f"[LOG] ===== 프록시 순환 다운로드 시작 =====")
    print(f"[LOG] Download ID: {req.id}, 파일경로: {file_path}")
    
    proxies = get_unused_proxies(db)
    if not proxies:
        raise Exception("사용 가능한 프록시가 없습니다")
    
    # 선호 프록시가 있으면 맨 앞으로 이동
    if preferred_proxy and preferred_proxy in proxies:
        proxies.remove(preferred_proxy)
        proxies.insert(0, preferred_proxy)
        print(f"[LOG] 선호 프록시를 첫 번째로 설정: {preferred_proxy}")
    
    last_error = None
    
    for i, proxy_addr in enumerate(proxies):
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 프록시 순환 중 정지됨: {req.id}")
            return
        
        print(f"[LOG] 프록시 {i+1}/{len(proxies)} 시도: {proxy_addr}")
        
        try:
            # 프록시별 임시 속성 초기화
            for attr in ['_last_sse_send_time', '_last_local_download_speed', '_last_db_update_size']:
                if hasattr(req, attr):
                    delattr(req, attr)
            
            # 프록시로 다운로드 시도
            await download_with_proxy(direct_link, file_path, proxy_addr, initial_size, req, db)
            
            # 성공하면 프록시 성공 마킹하고 종료
            mark_proxy_used(db, proxy_addr, success=True)
            print(f"[LOG] ===== 프록시 순환 성공 완료 =====")
            print(f"[LOG] 성공한 프록시: {proxy_addr}")
            return
            
        except Exception as e:
            error_msg = str(e)
            print(f"[LOG] 프록시 {proxy_addr} 실패: {error_msg}")
            mark_proxy_used(db, proxy_addr, success=False)
            last_error = e
            
            # 마지막 프록시가 아니면 계속 시도
            if i < len(proxies) - 1:
                print(f"[LOG] 다음 프록시로 계속 시도...")
                continue
    
    print(f"[LOG] 모든 프록시에서 다운로드 실패")
    if last_error:
        raise last_error