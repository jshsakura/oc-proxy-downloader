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
    
    # 로컬 다운로드 등록 (1fichier만)
    from .shared import download_manager
    
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
        
        # 로컬 다운로드 등록 (1fichier만)
        if not use_proxy:
            download_manager.register_local_download(request_id, req.url)
        
        # 다운로드 경로 설정
        download_path = get_download_path()
        base_filename = req.file_name if req.file_name else f"download_{request_id}"
        
        # Windows에서 파일명에 사용할 수 없는 문자 제거 (강화)
        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', base_filename)
        # 추가 Windows 제한사항 처리
        safe_filename = re.sub(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)', r'\1_\2', safe_filename, flags=re.IGNORECASE)
        # 파일명 끝의 점과 공백 제거 (Windows 제한)
        safe_filename = safe_filename.rstrip('. ')
        # 파일명이 너무 길면 자르기 (Windows 경로 제한 고려)
        if len(safe_filename) > 200:
            name_part, ext_part = safe_filename.rsplit('.', 1) if '.' in safe_filename else (safe_filename, '')
            safe_filename = name_part[:200-len(ext_part)-1] + ('.' + ext_part if ext_part else '')
        # 빈 파일명 방지
        if not safe_filename or safe_filename == '.':
            safe_filename = f"download_{request_id}"
            
        print(f"[LOG] 원본 파일명: '{base_filename}', 안전한 파일명: '{safe_filename}'")
        
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
        
        # 1단계: Direct Link 파싱
        direct_link = None
        used_proxy_addr = None
        
        if use_proxy:
            print(f"[LOG] 프록시 모드로 Direct Link 파싱 시작")
            req.status = StatusEnum.proxying
            db.commit()
            # 재시도이거나 이어받기인 경우 항상 강제 재파싱 (원본 URL로 새로 파싱)
            force_reparse = initial_downloaded_size > 0 or req.direct_link is None
            print(f"[LOG] 강제 재파싱 모드: {force_reparse} (이어받기: {initial_downloaded_size > 0}, 링크없음: {req.direct_link is None})")
            direct_link, used_proxy_addr = parse_with_proxy_cycling(req, db, force_reparse=force_reparse)
        else:
            print(f"[LOG] 로컬 모드로 Direct Link 파싱")
            req.status = StatusEnum.downloading
            db.commit()
            
            # 재시도이거나 이어받기인 경우 항상 강제 재파싱 (원본 URL로 새로 파싱)
            force_reparse = initial_downloaded_size > 0 or req.direct_link is None
            print(f"[LOG] 강제 재파싱 모드: {force_reparse} (이어받기: {initial_downloaded_size > 0}, 링크없음: {req.direct_link is None})")
            
            # 로컬 모드에서는 파일 정보와 함께 파싱
            from .parser_service import parse_direct_link_with_file_info
            direct_link, file_info = parse_direct_link_with_file_info(
                req.url, req.password, use_proxy=False
            )
            
            # 파일 정보 파싱 실패 시 기존 파싱 로직 사용
            if not direct_link:
                direct_link = get_or_parse_direct_link(req, use_proxy=False, force_reparse=force_reparse)
            
            # 파일 정보가 추출되면 DB에 저장 (기존 파일명이 없거나 빈 문자열인 경우)
            if file_info and file_info['name'] and (not req.file_name or req.file_name.strip() == ''):
                req.file_name = file_info['name']
                print(f"[LOG] 파일명 추출: {file_info['name']}")
                db.commit()
        
        # 정지 상태 체크 (파싱 후)
        db.refresh(req)
        if req.status == StatusEnum.stopped:
            print(f"[LOG] 다운로드 정지됨 (파싱 후): ID {request_id}")
            return
        
        if not direct_link:
            # URL 유효성 체크를 통한 더 자세한 에러 메시지
            try:
                import requests
                test_response = requests.head(req.url, timeout=5)
                if test_response.status_code == 404:
                    error_msg = "파일이 존재하지 않거나 삭제됨 (404 에러)"
                elif test_response.status_code == 403:
                    error_msg = "파일 접근이 거부됨 (403 에러)"
                else:
                    error_msg = f"Direct Link 파싱 실패 (HTTP {test_response.status_code})"
            except:
                error_msg = "Direct Link 파싱 실패 - URL에 접근할 수 없음"
            
            print(f"[LOG] {error_msg}")
            req.status = StatusEnum.failed
            req.error = error_msg
            db.commit()
            
            # WebSocket으로 실패 상태 전송
            send_websocket_message("status_update", {
                "id": req.id,
                "url": req.url,
                "file_name": req.file_name,
                "status": "failed",
                "error": error_msg,
                "downloaded_size": 0,
                "total_size": 0,
                "save_path": None,
                "requested_at": req.requested_at.isoformat() if req.requested_at else None,
                "finished_at": None,
                "password": req.password,
                "direct_link": req.direct_link,
                "use_proxy": req.use_proxy
            })
            
            raise Exception(error_msg)
        
        # 특별한 다운로드 모드 처리
        if direct_link in ["DIRECT_DOWNLOAD_STREAM", "DIRECT_FILE_RESPONSE"]:
            print(f"[LOG] 직접 다운로드 모드: {direct_link}")
            req.direct_link = direct_link
            req.status = StatusEnum.downloading
            db.commit()
            
            # 실제 파일 다운로드를 위해 다시 파싱 시도
            print(f"[LOG] 실제 다운로드를 위한 재파싱 시도...")
            try:
                if use_proxy:
                    real_link, used_proxy_addr = parse_with_proxy_cycling(req, db, force_reparse=True)
                    if real_link and real_link not in ["DIRECT_DOWNLOAD_STREAM", "DIRECT_FILE_RESPONSE"]:
                        direct_link = real_link
                        print(f"[LOG] 재파싱으로 실제 링크 획득: {direct_link}")
                    else:
                        print(f"[LOG] 재파싱 실패 - 기본 다운로드 방법 사용")
                else:
                    real_link = get_or_parse_direct_link(req, use_proxy=False, force_reparse=True)
                    if real_link and real_link not in ["DIRECT_DOWNLOAD_STREAM", "DIRECT_FILE_RESPONSE"]:
                        direct_link = real_link
                        print(f"[LOG] 재파싱으로 실제 링크 획득: {direct_link}")
                    else:
                        print(f"[LOG] 재파싱 실패 - 특별 처리 모드 유지")
            except Exception as e:
                print(f"[LOG] 재파싱 중 오류: {e}")
            
        else:
            print(f"[LOG] Direct Link 획득: {direct_link}")
            req.direct_link = direct_link
            req.status = StatusEnum.downloading
            db.commit()
            
            # 다운로드 시작 시 즉시 WebSocket 상태 업데이트 (프로그레스바 즉시 시작)
            send_websocket_message("status_update", {
                "id": req.id,
                "url": req.url,
                "file_name": req.file_name,
                "status": "downloading",
                "error": None,
                "downloaded_size": initial_downloaded_size,
                "total_size": req.total_size or 0,
                "save_path": req.save_path,
                "requested_at": req.requested_at.isoformat() if req.requested_at else None,
                "finished_at": None,
                "password": req.password,
                "direct_link": req.direct_link,
                "use_proxy": req.use_proxy
            })
            
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
                
                # WebSocket으로 실패 상태 전송
                send_websocket_message("status_update", {
                    "id": req.id,
                    "url": req.url,
                    "file_name": req.file_name,
                    "status": "failed",
                    "error": str(e),
                    "downloaded_size": req.downloaded_size or 0,
                    "total_size": req.total_size or 0,
                    "save_path": req.save_path,
                    "requested_at": req.requested_at.isoformat() if req.requested_at else None,
                    "finished_at": None,
                    "password": req.password,
                    "direct_link": req.direct_link,
                    "use_proxy": req.use_proxy
                })
                
            else:
                print(f"[LOG] 다운로드가 정지 상태이므로 실패 처리하지 않음: ID {request_id}")
    
    finally:
        # 로컬 다운로드 해제
        if not use_proxy:
            download_manager.unregister_local_download(request_id)
        db.close()


def parse_with_proxy_cycling(req, db: Session, force_reparse=False):
    """프록시를 순환하면서 Direct Link 파싱"""
    from .proxy_manager import get_working_proxy
    
    # 먼저 작동하는 프록시를 찾아서 시도
    working_proxy = get_working_proxy(db, max_test=50)
    if working_proxy:
        print(f"[LOG] 검증된 프록시로 파싱 시도: {working_proxy}")
        try:
            # WebSocket으로 프록시 시도 중 알림
            send_websocket_message("proxy_trying", {
                "proxy": working_proxy,
                "step": "파싱 중 (검증됨)",
                "current": 1,
                "total": 1,
                "url": req.url
            })
            
            # 프록시로 파싱 시도 (카운트다운 처리 포함) - 파일 정보도 함께 추출
            try:
                from .parser_service import parse_direct_link_with_file_info
                direct_link, file_info = parse_direct_link_with_file_info(
                    req.url, 
                    req.password, 
                    use_proxy=True, 
                    proxy_addr=working_proxy
                )
                
                # 파일 정보가 추출되면 DB에 저장 (기존 파일명이 없거나 빈 문자열인 경우)
                if file_info and file_info['name'] and (not req.file_name or req.file_name.strip() == ''):
                    req.file_name = file_info['name']
                    print(f"[LOG] 프록시 모드에서 파일명 추출: {file_info['name']}")
                    db.commit()
            except Exception as e:
                error_msg = str(e)
                # 카운트다운 제한인 경우 프록시 문제가 아님
                if "카운트다운 감지" in error_msg or "countdown" in error_msg.lower():
                    print(f"[LOG] 프록시에서 카운트다운 감지 - 다른 프록시들도 동일할 가능성 높음")
                    # 카운트다운 정보 추출
                    import re
                    countdown_match = re.search(r'(\d+)초', error_msg)
                    if countdown_match:
                        countdown_seconds = int(countdown_match.group(1))
                        print(f"[LOG] 모든 프록시에서 {countdown_seconds}초 대기 예상")
                    raise e  # 카운트다운은 재발생시켜서 상위에서 처리
                else:
                    raise e  # 다른 에러는 그대로 전파
            
            if direct_link:
                print(f"[LOG] 검증된 프록시로 파싱 성공: {working_proxy}")
                mark_proxy_used(db, working_proxy, success=True)
                return direct_link, working_proxy
                
        except Exception as e:
            print(f"[LOG] 검증된 프록시 파싱 실패 - {working_proxy}: {e}")
            mark_proxy_used(db, working_proxy, success=False)
    
    # 검증된 프록시가 없거나 실패한 경우 전체 프록시로 폴백
    unused_proxies = get_unused_proxies(db)
    
    if not unused_proxies:
        print(f"[LOG] 사용 가능한 프록시가 없음")
        return None, None
    
    print(f"[LOG] {len(unused_proxies)}개 프록시로 파싱 시도 (폴백)")
    
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
            
            # 프록시로 파싱 시도 (카운트다운 감지) - 파일 정보도 함께 추출
            try:
                from .parser_service import parse_direct_link_with_file_info
                direct_link, file_info = parse_direct_link_with_file_info(
                    req.url, 
                    req.password, 
                    use_proxy=True, 
                    proxy_addr=proxy_addr
                )
                
                # 파일 정보가 추출되면 DB에 저장 (기존 파일명이 없거나 빈 문자열인 경우)
                if file_info and file_info['name'] and (not req.file_name or req.file_name.strip() == ''):
                    req.file_name = file_info['name']
                    print(f"[LOG] 프록시 모드에서 파일명 추출: {file_info['name']}")
                    db.commit()
            except Exception as e:
                error_msg = str(e)
                # 카운트다운 제한인 경우 모든 프록시에서 동일할 것
                if "카운트다운 감지" in error_msg or "countdown" in error_msg.lower():
                    print(f"[LOG] 프록시 {proxy_addr}에서 카운트다운 감지 - 프록시 순환 중단")
                    # 카운트다운은 전체적인 사이트 제한이므로 다른 프록시 시도 중단
                    raise e
                else:
                    # 일반적인 프록시 오류는 계속 진행
                    raise e
            
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
            
            content_length = int(response.headers.get('Content-Length', 0))
            content_type = response.headers.get('Content-Type', '').lower()
            
            # 응답 검증: HTML이나 빈 파일인지 확인
            print(f"[LOG] 프록시 응답 분석 - Content-Length: {content_length}, Content-Type: {content_type}")
            
            # Content-Type이 HTML인 경우 - 내용을 확인해서 실제 HTML인지 판단
            if 'text/html' in content_type:
                print(f"[LOG] HTML Content-Type 감지 - 내용 검사 중...")
                # 처음 1024바이트를 확인해서 실제 HTML인지 판단
                peek_content = response.content[:1024] if hasattr(response, 'content') else b''
                try:
                    peek_text = peek_content.decode('utf-8', errors='ignore').lower()
                    # 실제 HTML 태그와 에러 메시지가 있는지 확인
                    html_indicators = ['<html', '<body', '<head', '<!doctype']
                    error_indicators = ['error', '404', '403', 'not found', 'access denied', 'forbidden']
                    
                    has_html_tags = any(indicator in peek_text for indicator in html_indicators)
                    has_error_msg = any(indicator in peek_text for indicator in error_indicators)
                    
                    # HTML 태그가 있고 에러 메시지도 있으면 실제 에러 페이지
                    if has_html_tags and has_error_msg:
                        print(f"[LOG] 실제 HTML 에러 페이지 감지: {peek_text[:100]}...")
                        raise Exception("다운로드 링크가 에러 페이지로 리다이렉트됨 (HTML 응답)")
                    elif has_html_tags:
                        print(f"[LOG] HTML 페이지지만 에러가 아닐 수 있음 - 계속 진행")
                    else:
                        print(f"[LOG] HTML Content-Type이지만 실제 파일 데이터로 보임 - 계속 진행")
                except:
                    print(f"[LOG] HTML 내용 검사 실패 - 계속 진행")
                    pass
            
            # Content-Length가 너무 작은 경우 (1KB 미만)
            if content_length < 1024 and initial_size == 0:
                print(f"[LOG] 파일 크기가 너무 작음: {content_length} bytes - 에러 응답일 가능성")
                # 작은 응답의 내용을 확인해봄
                peek_content = response.content[:500]  # 처음 500바이트만 확인
                try:
                    peek_text = peek_content.decode('utf-8', errors='ignore').lower()
                    # HTML 태그나 에러 메시지가 포함되어 있는지 확인
                    error_indicators = ['<html', '<body', 'error', '404', '403', 'not found', 'access denied']
                    if any(indicator in peek_text for indicator in error_indicators):
                        print(f"[LOG] 응답에 에러 내용 감지: {peek_text[:100]}...")
                        raise Exception(f"다운로드 실패 - 에러 응답 감지 (크기: {content_length} bytes)")
                except:
                    pass  # 디코딩 실패해도 계속 진행
            
            if initial_size > 0:
                # 이어받기: 전체 크기 = 기존 크기 + 남은 크기
                total_size = initial_size + content_length
                print(f"[LOG] 이어받기 - 기존: {initial_size}, 남은 크기: {content_length}")
            else:
                # 새 다운로드: 전체 크기 = Content-Length
                total_size = content_length
            
            # 파일 크기가 0인 경우 다운로드 중단
            if total_size == 0:
                print(f"[LOG] 파일 크기가 0 - 다운로드 중단")
                raise Exception("파일 크기가 0입니다. 다운로드 링크가 올바르지 않습니다.")
            
            req.total_size = total_size
            db.commit()
            
            print(f"[LOG] 프록시 다운로드 시작 - 총 크기: {total_size} bytes, Content-Type: {content_type}")
            
            # 파일 경로 검증 및 디렉토리 생성
            try:
                download_path.mkdir(parents=True, exist_ok=True)
                print(f"[LOG] 파일 저장 경로: {file_path}")
            except Exception as e:
                raise Exception(f"다운로드 디렉토리 생성 실패: {e}")
            
            try:
                with open(file_path, 'ab' if initial_size > 0 else 'wb') as f:
                    downloaded = initial_size
                    last_update_size = downloaded
                    
                    chunk_count = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            chunk_count += 1
                            
                            # 매 64KB마다(8개 청크) 정지 상태 체크
                            if chunk_count % 8 == 0:
                                db.refresh(req)
                                if req.status == StatusEnum.stopped:
                                    print(f"[LOG] 다운로드 중 정지됨: {req.id} (진행률: {downloaded}/{total_size})")
                                    return
                            
                            # 진행률 업데이트 - 적절한 빈도 (매 512KB마다) + WebSocket 실시간 전송  
                            if downloaded - last_update_size >= 524288:  # 512KB
                                req.downloaded_size = downloaded
                                db.commit()
                                last_update_size = downloaded
                                
                                progress = (downloaded / total_size * 100) if total_size > 0 else 0
                                print(f"[LOG] 프록시 진행률: {progress:.1f}% ({downloaded}/{total_size})")
                                
                                # WebSocket으로 실시간 진행률 전송
                                print(f"[LOG] WebSocket 진행률 전송: ID={req.id}, progress={progress:.1f}%")
                                send_websocket_message("progress_update", {
                                    "id": req.id,
                                    "downloaded_size": downloaded,
                                    "total_size": total_size,
                                    "progress": round(progress, 1),
                                    "status": "downloading"
                                })
                    
                    req.downloaded_size = downloaded
                    db.commit()
                
            except Exception as file_error:
                raise Exception(f"파일 쓰기 실패: {file_error}")
                
        print(f"[LOG] 프록시 다운로드 완료: {downloaded} bytes")
        
        # 다운로드 완료 후 파일 검증
        if downloaded == 0:
            print(f"[LOG] 경고: 다운로드된 데이터가 0 bytes")
            raise Exception("다운로드 실패 - 받은 데이터가 없습니다")
        elif downloaded < 1024:
            print(f"[LOG] 경고: 다운로드된 파일이 매우 작음 ({downloaded} bytes)")
            # 작은 파일의 내용을 확인해봄
            try:
                with open(file_path, 'rb') as check_file:
                    content = check_file.read(500)
                    try:
                        text_content = content.decode('utf-8', errors='ignore').lower()
                        if any(indicator in text_content for indicator in ['<html', 'error', '404', '403']):
                            print(f"[LOG] 다운로드된 파일이 에러 페이지임: {text_content[:100]}...")
                            raise Exception(f"다운로드 실패 - 에러 페이지 받음 ({downloaded} bytes)")
                    except:
                        pass
            except:
                pass
        
        mark_proxy_used(db, proxy_addr, success=True)
        
        # WebSocket으로 다운로드 성공 알림
        send_websocket_message("proxy_success", {
            "proxy": proxy_addr,
            "step": "다운로드 완료",
            "url": req.url
        })
        
    except Exception as e:
        error_str = str(e)
        print(f"[LOG] 프록시 다운로드 실패: {e}")
        mark_proxy_used(db, proxy_addr, success=False)
        
        # DNS 오류 감지 시 재파싱 시도 (프록시에서도)
        if any(dns_error in error_str for dns_error in [
            "NameResolutionError", "Failed to resolve", "Name or service not known", 
            "No address associated with hostname", "nodename nor servname provided"
        ]):
            print(f"[LOG] 프록시에서 DNS 해상도 오류 감지 - 다운로드 링크 재파싱 시도")
            print(f"[LOG] 만료된 링크: {direct_link}")
            
            try:
                # 기존 direct_link 완전 초기화
                req.direct_link = None
                db.commit()
                
                # 강제 재파싱 시도 (여러 프록시로 시도)
                print(f"[LOG] 원본 URL로 강제 재파싱 시도: {req.url}")
                new_direct_link, used_proxy = parse_with_proxy_cycling(req, db, force_reparse=True)
                
                if new_direct_link and new_direct_link != direct_link:
                    print(f"[LOG] 프록시에서 DNS 오류 후 재파싱 성공: {new_direct_link}")
                    req.direct_link = new_direct_link
                    db.commit()
                    
                    # 재파싱된 링크로 다시 다운로드 시도
                    if used_proxy:
                        return download_with_proxy(new_direct_link, file_path, used_proxy, initial_size, req, db)
                    else:
                        return download_local(new_direct_link, file_path, initial_size, req, db)
                else:
                    print(f"[LOG] 프록시에서 DNS 오류 후 재파싱 실패 - 프록시 순환으로도 새 링크 획득 불가")
                    
            except Exception as reparse_error:
                print(f"[LOG] 프록시에서 DNS 오류 후 재파싱 중 예외: {reparse_error}")
                
                # 마지막 시도: 로컬 연결로 재파싱
                try:
                    print(f"[LOG] 마지막 시도: 로컬 연결로 재파싱")
                    from .parser_service import parse_direct_link_simple
                    local_direct_link = parse_direct_link_simple(req.url, req.password, use_proxy=False)
                    if local_direct_link and local_direct_link != direct_link:
                        print(f"[LOG] 로컬 연결로 재파싱 성공: {local_direct_link}")
                        req.direct_link = local_direct_link
                        db.commit()
                        return download_local(local_direct_link, file_path, initial_size, req, db)
                except Exception as local_error:
                    print(f"[LOG] 로컬 연결 재파싱도 실패: {local_error}")
        
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
        
        print(f"[LOG] 로컬 연결로 다운로드 시작")
        
        with requests.get(direct_link, stream=True, headers=headers, timeout=(10, 30)) as response:
            response.raise_for_status()
            
            # 응답 받은 후 정지 상태 체크
            db.refresh(req)
            if req.status == StatusEnum.stopped:
                print(f"[LOG] 응답 받은 후 정지됨: {req.id}")
                return
            
            content_length = int(response.headers.get('Content-Length', 0))
            content_type = response.headers.get('Content-Type', '').lower()
            
            # 응답 검증: HTML이나 빈 파일인지 확인
            print(f"[LOG] 로컬 응답 분석 - Content-Length: {content_length}, Content-Type: {content_type}")
            
            # Content-Type이 HTML인 경우 - 내용을 확인해서 실제 HTML인지 판단
            if 'text/html' in content_type:
                print(f"[LOG] HTML Content-Type 감지 - 내용 검사 중...")
                # 처음 1024바이트를 확인해서 실제 HTML인지 판단
                peek_content = response.content[:1024] if hasattr(response, 'content') else b''
                try:
                    peek_text = peek_content.decode('utf-8', errors='ignore').lower()
                    # 실제 HTML 태그와 에러 메시지가 있는지 확인
                    html_indicators = ['<html', '<body', '<head', '<!doctype']
                    error_indicators = ['error', '404', '403', 'not found', 'access denied', 'forbidden']
                    
                    has_html_tags = any(indicator in peek_text for indicator in html_indicators)
                    has_error_msg = any(indicator in peek_text for indicator in error_indicators)
                    
                    # HTML 태그가 있고 에러 메시지도 있으면 실제 에러 페이지
                    if has_html_tags and has_error_msg:
                        print(f"[LOG] 실제 HTML 에러 페이지 감지: {peek_text[:100]}...")
                        raise Exception("다운로드 링크가 에러 페이지로 리다이렉트됨 (HTML 응답)")
                    elif has_html_tags:
                        print(f"[LOG] HTML 페이지지만 에러가 아닐 수 있음 - 계속 진행")
                    else:
                        print(f"[LOG] HTML Content-Type이지만 실제 파일 데이터로 보임 - 계속 진행")
                except:
                    print(f"[LOG] HTML 내용 검사 실패 - 계속 진행")
                    pass
            
            # Content-Length가 너무 작은 경우 (1KB 미만)
            if content_length < 1024 and initial_size == 0:
                print(f"[LOG] 파일 크기가 너무 작음: {content_length} bytes - 에러 응답일 가능성")
                # 작은 응답의 내용을 확인해봄
                peek_content = response.content[:500]  # 처음 500바이트만 확인
                try:
                    peek_text = peek_content.decode('utf-8', errors='ignore').lower()
                    # HTML 태그나 에러 메시지가 포함되어 있는지 확인
                    error_indicators = ['<html', '<body', 'error', '404', '403', 'not found', 'access denied']
                    if any(indicator in peek_text for indicator in error_indicators):
                        print(f"[LOG] 응답에 에러 내용 감지: {peek_text[:100]}...")
                        raise Exception(f"다운로드 실패 - 에러 응답 감지 (크기: {content_length} bytes)")
                except:
                    pass  # 디코딩 실패해도 계속 진행
            
            if initial_size > 0:
                # 이어받기: 전체 크기 = 기존 크기 + 남은 크기
                total_size = initial_size + content_length
                print(f"[LOG] 이어받기 - 기존: {initial_size}, 남은 크기: {content_length}")
            else:
                # 새 다운로드: 전체 크기 = Content-Length
                total_size = content_length
            
            # 파일 크기가 0인 경우 다운로드 중단
            if total_size == 0:
                print(f"[LOG] 파일 크기가 0 - 다운로드 중단")
                raise Exception("파일 크기가 0입니다. 다운로드 링크가 올바르지 않습니다.")
            
            req.total_size = total_size
            db.commit()
            
            print(f"[LOG] 로컬 다운로드 시작 - 총 크기: {total_size} bytes, Content-Type: {content_type}")
            
            # 파일 경로 검증 및 디렉토리 생성
            try:
                download_path.mkdir(parents=True, exist_ok=True)
                print(f"[LOG] 파일 저장 경로: {file_path}")
            except Exception as e:
                raise Exception(f"다운로드 디렉토리 생성 실패: {e}")
            
            try:
                with open(file_path, 'ab' if initial_size > 0 else 'wb') as f:
                    downloaded = initial_size
                    last_update_size = downloaded
                    
                    chunk_count = 0
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            chunk_count += 1
                            
                            # 매 64KB마다(8개 청크) 정지 상태 체크
                            if chunk_count % 8 == 0:
                                db.refresh(req)
                                if req.status == StatusEnum.stopped:
                                    print(f"[LOG] 다운로드 중 정지됨: {req.id} (진행률: {downloaded}/{total_size})")
                                    return
                            
                            # 진행률 업데이트 - 적절한 빈도 (매 512KB마다) + WebSocket 실시간 전송  
                            if downloaded - last_update_size >= 524288:  # 512KB
                                req.downloaded_size = downloaded
                                db.commit()
                                last_update_size = downloaded
                                
                                progress = (downloaded / total_size * 100) if total_size > 0 else 0
                                print(f"[LOG] 로컬 진행률: {progress:.1f}% ({downloaded}/{total_size})")
                                
                                # WebSocket으로 실시간 진행률 전송
                                print(f"[LOG] WebSocket 진행률 전송: ID={req.id}, progress={progress:.1f}%")
                                send_websocket_message("progress_update", {
                                    "id": req.id,
                                    "downloaded_size": downloaded,
                                    "total_size": total_size,
                                    "progress": round(progress, 1),
                                    "status": "downloading"
                                })
                    
                    req.downloaded_size = downloaded
                    db.commit()
                
            except Exception as file_error:
                raise Exception(f"파일 쓰기 실패: {file_error}")
                
        print(f"[LOG] 로컬 다운로드 완료: {downloaded} bytes")
        
        # 다운로드 완료 후 파일 검증
        if downloaded == 0:
            print(f"[LOG] 경고: 다운로드된 데이터가 0 bytes")
            raise Exception("다운로드 실패 - 받은 데이터가 없습니다")
        elif downloaded < 1024:
            print(f"[LOG] 경고: 다운로드된 파일이 매우 작음 ({downloaded} bytes)")
            # 작은 파일의 내용을 확인해봄
            try:
                with open(file_path, 'rb') as check_file:
                    content = check_file.read(500)
                    try:
                        text_content = content.decode('utf-8', errors='ignore').lower()
                        if any(indicator in text_content for indicator in ['<html', 'error', '404', '403']):
                            print(f"[LOG] 다운로드된 파일이 에러 페이지임: {text_content[:100]}...")
                            raise Exception(f"다운로드 실패 - 에러 페이지 받음 ({downloaded} bytes)")
                    except:
                        pass
            except:
                pass
        
    except Exception as e:
        error_str = str(e)
        print(f"[LOG] 로컬 다운로드 실패: {e}")
        
        # DNS 오류 감지 시 재파싱 시도
        if any(dns_error in error_str for dns_error in [
            "NameResolutionError", "Failed to resolve", "Name or service not known", 
            "No address associated with hostname", "nodename nor servname provided"
        ]):
            print(f"[LOG] DNS 해상도 오류 감지 - 다운로드 링크 재파싱 시도")
            print(f"[LOG] 만료된 링크: {direct_link}")
            
            try:
                # 기존 direct_link 완전 초기화
                req.direct_link = None
                db.commit()
                
                # 우선 로컬 연결로 재파싱 시도
                print(f"[LOG] 로컬 연결으로 강제 재파싱 시도: {req.url}")
                from .parser_service import parse_direct_link_simple
                new_direct_link = parse_direct_link_simple(req.url, req.password, use_proxy=False)
                
                if new_direct_link and new_direct_link != direct_link:
                    print(f"[LOG] 로컬 연결 DNS 오류 후 재파싱 성공: {new_direct_link}")
                    req.direct_link = new_direct_link
                    db.commit()
                    return download_local(new_direct_link, file_path, initial_size, req, db)
                else:
                    print(f"[LOG] 로컬 재파싱 실패 - 프록시 순환 시도")
                    
                    # 로컬 재파싱 실패 시 프록시로 시도
                    try:
                        new_direct_link, used_proxy = parse_with_proxy_cycling(req, db, force_reparse=True)
                        if new_direct_link and new_direct_link != direct_link:
                            print(f"[LOG] 프록시 순환으로 재파싱 성공: {new_direct_link}")
                            req.direct_link = new_direct_link
                            db.commit()
                            
                            if used_proxy:
                                return download_with_proxy(new_direct_link, file_path, used_proxy, initial_size, req, db)
                            else:
                                return download_local(new_direct_link, file_path, initial_size, req, db)
                        else:
                            print(f"[LOG] 프록시 순환 재파싱도 실패")
                    except Exception as proxy_error:
                        print(f"[LOG] 프록시 순환 재파싱 중 예외: {proxy_error}")
                        
            except Exception as reparse_error:
                print(f"[LOG] DNS 오류 후 재파싱 중 예외: {reparse_error}")
        
        # WebSocket으로 로컬 다운로드 실패 상태 전송
        send_websocket_message("status_update", {
            "id": req.id,
            "url": req.url,
            "file_name": req.file_name,
            "status": "failed",
            "error": str(e),
            "downloaded_size": req.downloaded_size or 0,
            "total_size": req.total_size or 0,
            "save_path": req.save_path,
            "requested_at": req.requested_at.isoformat() if req.requested_at else None,
            "finished_at": None,
            "password": req.password,
            "direct_link": req.direct_link,
            "use_proxy": req.use_proxy
        })
        
        raise e


def download_from_stream(proxy_addr, file_path, initial_size, req, db, use_proxy):
    """직접 다운로드 스트림에서 파일 다운로드"""
    print(f"[LOG] 직접 스트림 다운로드 시작 (프록시: {proxy_addr})")
    
    # 스트림 다운로드는 parser_service에서 이미 시작되었으므로
    # 여기서는 재시도 메커니즘을 구현
    try:
        # 새로운 요청으로 다운로드 재시작
        from .parser_service import get_or_parse_direct_link
        
        if use_proxy and proxy_addr:
            # 프록시 사용하여 다운로드 재시작
            print(f"[LOG] 프록시 {proxy_addr}로 스트림 다운로드 재시작")
            download_with_proxy("STREAM_RETRY", file_path, proxy_addr, initial_size, req, db)
        else:
            # 로컬 연결로 다운로드 재시작
            print(f"[LOG] 로컬 연결로 스트림 다운로드 재시작")
            download_local("STREAM_RETRY", file_path, initial_size, req, db)
            
    except Exception as e:
        print(f"[LOG] 스트림 다운로드 실패: {e}")
        raise e


def cleanup_download_file(file_path):
    """다운로드 완료 후 파일 정리"""
    try:
        if str(file_path).endswith('.part'):
            final_path = str(file_path)[:-5]  # .part 제거
            
            # 파일 크기 확인
            if os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                print(f"[LOG] 최종 파일 크기: {file_size} bytes")
                
                # 파일이 매우 작거나 빈 경우 내용 검증
                if file_size < 1024:
                    print(f"[LOG] 작은 파일 검증 중... ({file_size} bytes)")
                    try:
                        with open(file_path, 'rb') as f:
                            content = f.read(500)
                            try:
                                text_content = content.decode('utf-8', errors='ignore').lower()
                                error_indicators = ['<html', '<body', 'error', '404', '403', 'not found']
                                if any(indicator in text_content for indicator in error_indicators):
                                    print(f"[LOG] 에러 파일 감지 - 삭제함: {text_content[:100]}...")
                                    os.remove(file_path)
                                    raise Exception(f"다운로드 실패 - 에러 페이지 받음 ({file_size} bytes)")
                            except UnicodeDecodeError:
                                # 바이너리 파일인 경우 통과
                                pass
                    except Exception as e:
                        if "에러 페이지" in str(e):
                            raise e  # 에러 페이지인 경우 예외 전파
                        pass  # 기타 파일 읽기 에러는 무시
                
                # 정상 파일인 경우 이름 변경
                os.rename(file_path, final_path)
                print(f"[LOG] 파일명 정리 완료: {final_path}")
            else:
                print(f"[LOG] 파일이 존재하지 않음: {file_path}")
    except Exception as e:
        print(f"[LOG] 파일 정리 실패: {e}")
        raise e