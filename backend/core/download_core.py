"""
핵심 다운로드 로직 모듈
- 1fichier 파일 다운로드
- 프록시 순환 다운로드
- 파일 관리
"""

import os
import re
import time
import threading
import requests
import json
from pathlib import Path
from sqlalchemy.orm import Session

from .db import get_db
from .models import DownloadRequest, StatusEnum
from .config import get_download_path
from .proxy_manager import get_unused_proxies, mark_proxy_used
from .parser_service import get_or_parse_direct_link


def send_websocket_message(message_type: str, data: dict):
    """WebSocket 메시지를 전송하는 함수"""
    try:
        # main.py의 status_queue에 메시지 전송
        from core.shared import status_queue
        message = json.dumps({
            "type": message_type,
            "data": data
        }, ensure_ascii=False)
        status_queue.put(message)
        # print(f"[LOG] WebSocket 메시지 전송: {message_type}")
    except Exception as e:
        print(f"[LOG] WebSocket 메시지 전송 실패: {e}")


def download_1fichier_file_new(request_id: int, lang: str = "ko", use_proxy: bool = True):
    """
    새로운 프록시 순환 로직을 사용한 1fichier 다운로드 함수
    """
    print("=" * 80)
    print(f"[LOG] *** 새로운 다운로드 시스템 시작 ***")
    print(f"[LOG] Request ID: {request_id}")
    print(f"[LOG] Use Proxy: {use_proxy}")
    print(f"[LOG] 시작 시간: {time.strftime('%H:%M:%S')}")
    print("=" * 80)
    
    # 새로운 DB 세션 생성
    from .db import SessionLocal
    db = SessionLocal()
    req = None
    
    try:
        # 요청 정보 조회
        req = db.query(DownloadRequest).filter(DownloadRequest.id == request_id).first()
        if req is None:
            print(f"[LOG] 다운로드 요청을 찾을 수 없음: ID {request_id}")
            return
        
        # 정지 상태 체크
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드가 이미 정지된 상태: ID {request_id}")
            return
        
        print(f"[LOG] URL: {req.url}")
        print(f"[LOG] 파일명: {req.file_name}")
        
        # 다운로드 경로 설정
        download_path = get_download_path()
        base_filename = req.file_name if req.file_name else f"download_{request_id}"
        
        # Windows에서 파일명에 사용할 수 없는 문자 제거
        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', base_filename)
        print(f"[LOG] 원본 파일명: {base_filename}, 안전한 파일명: {safe_filename}")
        
        file_path = download_path / safe_filename
        part_file_path = download_path / (safe_filename + ".part")
        
        # 기존 파일 확인
        initial_downloaded_size = 0
        if part_file_path.exists():
            file_path = part_file_path
            initial_downloaded_size = part_file_path.stat().st_size
            print(f"[LOG] 이어받기: {initial_downloaded_size} bytes")
        elif file_path.exists():
            initial_downloaded_size = file_path.stat().st_size
            print(f"[LOG] 기존 파일 발견: {initial_downloaded_size} bytes")
        else:
            file_path = part_file_path
            print(f"[LOG] 새 다운로드 시작")
        
        # 정지 상태 재체크
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 정지됨 (파싱 시작 전): ID {request_id}")
            return
        
        # 1단계: 프록시 순환으로 Direct Link 파싱
        req.status = StatusEnum.proxying
        db.commit()
        
        direct_link = None
        used_proxy_addr = None
        
        if use_proxy:
            print(f"[LOG] 프록시 모드로 Direct Link 파싱 시작")
            direct_link, used_proxy_addr = parse_with_proxy_cycling(req, db, force_reparse=initial_downloaded_size > 0)
        else:
            print(f"[LOG] 로컬 모드로 Direct Link 파싱")
            direct_link = get_or_parse_direct_link(req, use_proxy=False, force_reparse=initial_downloaded_size > 0)
        
        # 정지 상태 체크 (파싱 후)
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 정지됨 (파싱 후): ID {request_id}")
            return
        
        if not direct_link:
            raise Exception("Direct Link 파싱 실패")
        
        print(f"[LOG] Direct Link 획득: {direct_link}")
        req.direct_link = direct_link
        req.status = StatusEnum.downloading
        db.commit()
        
        # 정지 상태 체크 (다운로드 시작 전)
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 정지됨 (다운로드 시작 전): ID {request_id}")
            return
        
        # 2단계: 프록시 순환으로 실제 다운로드
        if use_proxy and used_proxy_addr:
            print(f"[LOG] 프록시 {used_proxy_addr}로 다운로드 시작")
            download_with_proxy(direct_link, file_path, used_proxy_addr, initial_downloaded_size, req, db)
        else:
            print(f"[LOG] 로컬 연결로 다운로드 시작")
            download_local(direct_link, file_path, initial_downloaded_size, req, db)
        
        # 정지 상태 체크 (완료 처리 전)
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 정지됨 (완료 처리 전): ID {request_id}")
            return
        
        # 3단계: 완료 처리
        req.status = StatusEnum.done
        db.commit()
        cleanup_download_file(file_path)
        print(f"[LOG] 다운로드 완료: {req.file_name}")
        
    except Exception as e:
        print(f"[LOG] 다운로드 실패: {e}")
        if req:
            # 정지 상태가 아닐 때만 실패로 처리
            db.refresh(req)
            if req.status != StatusEnum.stopped:
                req.status = StatusEnum.failed
                req.error = str(e)
                db.commit()
            else:
                print(f"[LOG] 다운로드가 정지 상태이므로 실패 처리하지 않음: ID {request_id}")
    
    finally:
        db.close()


def parse_with_proxy_cycling(req, db: Session, force_reparse=False):
    """프록시를 순환하면서 Direct Link 파싱"""
    unused_proxies = get_unused_proxies(db)
    
    if not unused_proxies:
        print(f"[LOG] 사용 가능한 프록시가 없음")
        return None, None
    
    # print(f"[LOG] {len(unused_proxies)}개 프록시로 파싱 시도")
    
    for i, proxy_addr in enumerate(unused_proxies):
        # 매 프록시 시도마다 정지 상태 체크
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 프록시 파싱 중 정지됨: {req.id}")
            return None, None
        
        try:
            # print(f"[LOG] 파싱 시도 {i+1}/{len(unused_proxies)}: {proxy_addr}")
            
            # WebSocket으로 프록시 시도 중 알림
            send_websocket_message("proxy_trying", {
                "proxy": proxy_addr,
                "step": "파싱 중",
                "current": i + 1,
                "total": len(unused_proxies),
                "url": req.url
            })
            
            direct_link = get_or_parse_direct_link(
                req, 
                use_proxy=True, 
                force_reparse=force_reparse, 
                proxy_addr=proxy_addr
            )
            
            # 파싱 완료 후 정지 상태 체크
            db.refresh(req)
            if req.status == StatusEnum.stopped:
                print(f"[LOG] 프록시 파싱 완료 후 정지됨: {req.id}")
                return None, None
            
            if direct_link:
                print(f"[LOG] 파싱 성공 - 프록시: {proxy_addr}")
                mark_proxy_used(db, proxy_addr, success=True)
                
                # WebSocket으로 프록시 성공 알림
                send_websocket_message("proxy_success", {
                    "proxy": proxy_addr,
                    "step": "파싱 완료",
                    "url": req.url
                })
                
                return direct_link, proxy_addr
                
        except (requests.exceptions.ConnectTimeout, 
                requests.exceptions.ReadTimeout, 
                requests.exceptions.Timeout, 
                requests.exceptions.ProxyError) as e:
            
            print(f"[LOG] 파싱 실패 - 프록시 {proxy_addr}: {e}")
            mark_proxy_used(db, proxy_addr, success=False)
            
            # WebSocket으로 프록시 실패 알림
            send_websocket_message("proxy_failed", {
                "proxy": proxy_addr,
                "step": "파싱 실패",
                "error": str(e),
                "url": req.url
            })
            
            continue
            
        except Exception as e:
            print(f"[LOG] 파싱 오류 - 프록시 {proxy_addr}: {e}")
            mark_proxy_used(db, proxy_addr, success=False)
            
            # WebSocket으로 프록시 실패 알림
            send_websocket_message("proxy_failed", {
                "proxy": proxy_addr,
                "step": "파싱 오류",
                "error": str(e),
                "url": req.url
            })
            
            continue
    
    print(f"[LOG] 모든 프록시에서 파싱 실패")
    return None, None


def download_with_proxy(direct_link, file_path, proxy_addr, initial_size, req, db):
    """지정된 프록시로 다운로드"""
    proxies = {
        'http': f'http://{proxy_addr}',
        'https': f'http://{proxy_addr}'
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Accept-Language': 'ko-KR,ko;q=0.9',
        'Connection': 'keep-alive'
    }
    
    if initial_size > 0:
        headers['Range'] = f'bytes={initial_size}-'
        print(f"[LOG] 이어받기 헤더: Range={headers['Range']}")
    
    try:
        # 다운로드 시작 전 정지 상태 체크
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 시작 전 정지됨: {req.id}")
            return
        
        # WebSocket으로 다운로드 시작 알림
        send_websocket_message("proxy_trying", {
            "proxy": proxy_addr,
            "step": "다운로드 중",
            "current": 1,
            "total": 1,
            "url": req.url
        })
        
        with requests.get(direct_link, stream=True, headers=headers, proxies=proxies, timeout=(3, 10)) as response:
            response.raise_for_status()
            
            # 응답 받은 후 정지 상태 체크
            db.refresh(req)
            if req.status == StatusEnum.stopped:
                print(f"[LOG] 응답 받은 후 정지됨: {req.id}")
                return
            
            total_size = int(response.headers.get('Content-Length', 0))
            if initial_size > 0:
                total_size += initial_size
            
            req.total_size = total_size
            db.commit()
            
            print(f"[LOG] 다운로드 시작 - 총 크기: {total_size} bytes")
            
            with open(file_path, 'ab' if initial_size > 0 else 'wb') as f:
                downloaded = initial_size
                
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        # 진행률 업데이트 (매 1MB마다) + 정지 상태 체크
                        if downloaded % 1048576 == 0:  # 1MB
                            req.downloaded_size = downloaded
                            db.commit()
                            
                            # 진행률 업데이트할 때만 정지 상태 체크
                            db.refresh(req)
                            if req.status == StatusEnum.stopped:
                                print(f"[LOG] 다운로드 중 정지됨: {req.id} (진행률: {downloaded}/{total_size})")
                                return
                            
                            progress = (downloaded / total_size * 100) if total_size > 0 else 0
                            print(f"[LOG] 진행률: {progress:.1f}% ({downloaded}/{total_size})")
                
                req.downloaded_size = downloaded
                db.commit()
                
        print(f"[LOG] 다운로드 완료: {downloaded} bytes")
        mark_proxy_used(db, proxy_addr, success=True)
        
        # WebSocket으로 다운로드 성공 알림
        send_websocket_message("proxy_success", {
            "proxy": proxy_addr,
            "step": "다운로드 완료",
            "url": req.url
        })
        
    except Exception as e:
        print(f"[LOG] 프록시 다운로드 실패: {e}")
        mark_proxy_used(db, proxy_addr, success=False)
        
        # WebSocket으로 다운로드 실패 알림
        send_websocket_message("proxy_failed", {
            "proxy": proxy_addr,
            "step": "다운로드 실패",
            "error": str(e),
            "url": req.url
        })
        
        raise e


def download_local(direct_link, file_path, initial_size, req, db):
    """로컬 연결로 다운로드"""
    print(f"[LOG] 로컬 다운로드는 아직 구현되지 않음")
    # TODO: 로컬 다운로드 구현
    pass


def cleanup_download_file(file_path):
    """다운로드 완료 후 파일 정리"""
    try:
        if str(file_path).endswith('.part'):
            final_path = str(file_path)[:-5]  # .part 제거
            os.rename(file_path, final_path)
            print(f"[LOG] 파일명 정리: {final_path}")
    except Exception as e:
        print(f"[LOG] 파일 정리 실패: {e}")