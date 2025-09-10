# -*- coding: utf-8 -*-
import sys
import os
import re

# UTF-8 인코딩 강제 설정
if sys.platform.startswith('win'):
    try:
        os.environ['PYTHONIOENCODING'] = 'utf-8'
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

import requests
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, HttpUrl
from core.models import DownloadRequest, Base, StatusEnum
from core.db import engine, get_db
from core.auth import get_current_user_optional, AUTHENTICATION_ENABLED
from typing import Dict, Any
from core.i18n import get_message
import json
import os
import re
import time

# 테이블 생성은 main.py에서 처리

# 기존 'paused' 상태를 'stopped'로 마이그레이션
try:
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text("UPDATE download_requests SET status = 'stopped' WHERE status = 'paused'"))
        conn.commit()
        if result.rowcount > 0:
            print(f"[LOG] {result.rowcount}개의 'paused' 레코드를 'stopped'로 변경")
except Exception as e:
    print(f"[LOG] 상태 마이그레이션 실패: {e}")

router = APIRouter()

class DownloadRequestCreate(BaseModel):
    url: HttpUrl
    password: str = ""
    use_proxy: bool = True
    file_name: str = None  # 재다운로드시 기존 파일명 전달용

@router.post("/parse-info/")
def parse_file_info_only(request: DownloadRequestCreate, db: Session = Depends(get_db)):
    """파일 정보만 파싱하고 대기 상태로 설정"""
    try:
        # 로그 파일에도 기록
        try:
            import os
            log_path = "/tmp/debug.log" if os.path.exists("/tmp") else "debug.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] PARSE INFO API CALLED: {request.url}\n")
                f.flush()
        except PermissionError:
            print(f"[{time.strftime('%H:%M:%S')}] PARSE INFO API CALLED: {request.url}")
        
        print("="*80)
        print("[LOG] *** PARSE FILE INFO API CALLED ***")
        print(f"[LOG] URL: {request.url}")
        print(f"[LOG] Use Proxy: {request.use_proxy}")
        print("="*80)
        
        # 기존 요청이 있는지 확인 (파일명이 있는 경우 재사용)
        existing_req = db.query(DownloadRequest).filter(
            DownloadRequest.url == str(request.url),
            DownloadRequest.file_name.isnot(None),
            DownloadRequest.file_name != ''
        ).order_by(DownloadRequest.requested_at.desc()).first()
        
        if existing_req and existing_req.file_name and existing_req.file_name.strip():
            print(f"[LOG] 기존 파싱 결과 재사용: {existing_req.file_name}")
            return {
                "id": existing_req.id,
                "status": "parsed",
                "file_name": existing_req.file_name,
                "file_size": existing_req.file_size,
                "message": "File info reused from existing request"
            }
        
        # 새 요청 생성
        db_req = DownloadRequest(
            url=str(request.url),
            status=StatusEnum.pending,  # 대기 상태로 설정
            password=request.password,
            use_proxy=request.use_proxy,
            file_name=request.file_name  # 재다운로드시 기존 파일명 사용
        )
        db.add(db_req)
        db.commit()
        db.refresh(db_req)
        
        print(f"[LOG] 파일 정보 파싱 요청 생성: ID {db_req.id}")
        
        # URL 타입 확인 후 적절한 파싱 방법 선택
        url_str = str(request.url)
        if re.match(r'https?://(?:[^\.]+\.)?1fichier\.com/', url_str.lower()):
            # 1fichier URL - 기존 파서 사용
            from .parser_service import parse_direct_link_with_file_info
            
            try:
                print(f"[LOG] 1fichier 파일 정보 파싱 시작...")
                direct_link, file_info = parse_direct_link_with_file_info(
                    url_str,
                    request.password,
                    use_proxy=request.use_proxy
                )
            except Exception as parse_error:
                print(f"[ERROR] 1fichier 파일 정보 파싱 실패: {parse_error}")
                db_req.error = f"파싱 실패: {str(parse_error)}"
                db_req.status = StatusEnum.failed
                db.commit()
                
                return {
                    "id": db_req.id,
                    "status": "failed",
                    "error": str(parse_error)
                }
        else:
            # 일반 URL - Content-Type 체크 후 파일 정보 추출
            try:
                print(f"[LOG] 일반 URL 파일 정보 체크 시작...")
                import requests
                from urllib.parse import urlparse, unquote
                
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                
                head_response = requests.head(url_str, headers=headers, timeout=30, allow_redirects=True)
                if head_response.status_code == 200:
                    # Content-Type 체크 - 웹페이지는 바로 차단
                    content_type = head_response.headers.get('Content-Type', '').lower()
                    
                    if any(web_type in content_type for web_type in ['text/html', 'text/xml', 'application/json', 'text/plain']):
                        print(f"[LOG] 웹페이지 Content-Type 감지: {content_type} - 파싱 불가")
                        db_req.error = f"웹페이지는 다운로드할 수 없습니다. (Content-Type: {content_type})"
                        db_req.status = StatusEnum.failed
                        db.commit()
                        
                        return {
                            "id": db_req.id,
                            "status": "failed",
                            "error": f"웹페이지는 다운로드할 수 없습니다. (Content-Type: {content_type})"
                        }
                    
                    # 파일 정보 추출
                    file_info = {}
                    direct_link = url_str  # 일반 URL은 그 자체가 다운로드 링크
                    
                    # URL에서 파일명 추출
                    parsed_url = urlparse(url_str)
                    if parsed_url.path and '/' in parsed_url.path:
                        url_filename = unquote(parsed_url.path.split('/')[-1])
                        if url_filename and len(url_filename) > 3 and '.' in url_filename:
                            file_info['name'] = url_filename
                    
                    # Content-Disposition에서 파일명 재추출 시도
                    content_disposition = head_response.headers.get('Content-Disposition')
                    if content_disposition and 'filename=' in content_disposition:
                        filename_match = re.search(r'filename[*]?=(?:UTF-8\'\')?["\']?([^"\';]+)["\']?', content_disposition, re.IGNORECASE)
                        if filename_match:
                            file_info['name'] = unquote(filename_match.group(1))
                    
                    # Content-Length에서 파일 크기 추출
                    content_length = head_response.headers.get('Content-Length')
                    if content_length:
                        bytes_size = int(content_length)
                        
                        # 포맷팅된 크기 생성
                        if bytes_size >= 1024**3:
                            file_info['size'] = f"{bytes_size / (1024**3):.1f} GB"
                        elif bytes_size >= 1024**2:
                            file_info['size'] = f"{bytes_size / (1024**2):.1f} MB"
                        elif bytes_size >= 1024:
                            file_info['size'] = f"{bytes_size / 1024:.1f} KB"
                        else:
                            file_info['size'] = f"{bytes_size} bytes"
                    
                    print(f"[LOG] 일반 URL 파일 정보 추출 완료: {file_info}")
                    
                else:
                    print(f"[LOG] HEAD 요청 실패: {head_response.status_code}")
                    db_req.error = f"서버 응답 오류: {head_response.status_code}"
                    db_req.status = StatusEnum.failed
                    db.commit()
                    
                    return {
                        "id": db_req.id,
                        "status": "failed",
                        "error": f"서버 응답 오류: {head_response.status_code}"
                    }
                    
            except Exception as parse_error:
                print(f"[ERROR] 일반 URL 파일 정보 체크 실패: {parse_error}")
                db_req.error = f"파일 정보 체크 실패: {str(parse_error)}"
                db_req.status = StatusEnum.failed
                db.commit()
                
                return {
                    "id": db_req.id,
                    "status": "failed",
                    "error": str(parse_error)
                }
        
        try:
            
            # 파일 정보 업데이트
            if file_info and file_info.get('name'):
                db_req.file_name = file_info['name']
                print(f"[LOG] 파일명 추출: {file_info['name']}")
            
            if file_info and file_info.get('size'):
                # 크기를 바이트로 변환해서 저장
                size_str = file_info['size']
                try:
                    import re
                    match = re.search(r'(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)', size_str, re.IGNORECASE)
                    if match:
                        value = float(match.group(1))
                        unit = match.group(2).upper()
                        
                        multipliers = {'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
                        if unit in multipliers:
                            total_bytes = int(value * multipliers[unit])
                            db_req.total_size = total_bytes
                            print(f"[LOG] 파일 크기 추출: {size_str} ({total_bytes} bytes)")
                except Exception as e:
                    print(f"[LOG] 파일 크기 파싱 실패: {e}")
            
            # direct_link도 저장 (나중에 다운로드할 때 사용)
            if direct_link:
                db_req.direct_link = direct_link
                print(f"[LOG] Direct link 저장됨")
            
            db.commit()
            
            return {
                "id": db_req.id, 
                "status": "parsed",
                "file_name": db_req.file_name or "Unknown",
                "file_size": file_info.get('size') if file_info else None,
                "message": "File info parsed successfully, ready to download"
            }
            
        except Exception as parse_error:
            print(f"[ERROR] 파일 정보 파싱 실패: {parse_error}")
            db_req.error = f"파싱 실패: {str(parse_error)}"
            db_req.status = StatusEnum.failed
            db.commit()
            
            return {
                "id": db_req.id,
                "status": "failed",
                "error": str(parse_error)
            }
            
    except Exception as e:
        print(f"[ERROR] Parse info API 실패: {e}")
        return {
            "error": str(e),
            "status": "failed"
        }

@router.post("/download/")
def create_download_task(
    request: DownloadRequestCreate, 
    db: Session = Depends(get_db),
    user: Dict[str, Any] = Depends(get_current_user_optional)
):
    # 로그 파일에도 기록 (도커 환경을 위해 /tmp 경로 사용)
    try:
        import os
        log_path = "/tmp/debug.log" if os.path.exists("/tmp") else "debug.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] API CALLED: {request.url}\n")
            f.flush()
    except PermissionError:
        # 권한 없으면 그냥 콘솔에만 출력
        print(f"[{time.strftime('%H:%M:%S')}] API CALLED: {request.url}")
    
    print("="*80)
    print("[LOG] *** CREATE DOWNLOAD TASK API CALLED ***")
    print(f"[LOG] URL: {request.url}")
    print(f"[LOG] Use Proxy: {request.use_proxy}")
    print("="*80)
    import sys
    sys.stdout.flush()  # 즉시 출력 강제
    
    # URL 타입별 사전 검증
    url_str = str(request.url)
    
    # 1fichier가 아닌 일반 URL인 경우 Content-Type 미리 체크
    if not re.match(r'https?://(?:[^\.]+\.)?1fichier\.com/', url_str.lower()):
        print(f"[LOG] 일반 URL 감지, Content-Type 사전 체크: {url_str}")
        
        try:
            import requests
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            head_response = requests.head(url_str, headers=headers, timeout=30, allow_redirects=True)
            if head_response.status_code == 200:
                content_type = head_response.headers.get('Content-Type', '').lower()
                
                # 웹페이지는 바로 거부
                if any(web_type in content_type for web_type in ['text/html', 'text/xml', 'application/json', 'text/plain']):
                    print(f"[LOG] 웹페이지 Content-Type 감지: {content_type} - 다운로드 요청 거부")
                    raise HTTPException(status_code=400, detail=f"웹페이지는 다운로드할 수 없습니다. (Content-Type: {content_type})")
                
                print(f"[LOG] 다운로드 가능한 Content-Type 확인: {content_type}")
            else:
                print(f"[LOG] HEAD 요청 실패: {head_response.status_code}")
                raise HTTPException(status_code=400, detail=f"URL에 접근할 수 없습니다. (응답 코드: {head_response.status_code})")
                
        except requests.exceptions.RequestException as e:
            print(f"[LOG] URL 접근 실패: {e}")
            raise HTTPException(status_code=400, detail=f"URL에 접근할 수 없습니다: {str(e)}")
    else:
        print(f"[LOG] 1fichier URL 감지: {url_str}")
    
    db_req = DownloadRequest(
        url=str(request.url),
        status=StatusEnum.pending,
        password=request.password,
        use_proxy=request.use_proxy
    )
    db.add(db_req)
    db.commit()
    db.refresh(db_req)
    
    # 파일 정보 미리 파싱 (동기적으로) - 파일명이 없을 때만 실행
    if not db_req.file_name or db_req.file_name.strip() == '':
        print(f"[LOG] 파일명이 없어서 사전 파싱 시작...")
        try:
            from .parser_service import parse_file_info_only
            file_info = parse_file_info_only(str(request.url), request.password, request.use_proxy)
            if file_info and file_info.get('name'):
                # 현재 DB 세션에서 바로 업데이트
                db_req.file_name = file_info['name']
                db_req.file_size = file_info.get('size')
                db.commit()
                db.refresh(db_req)
                print(f"[LOG] 📁 파일 정보 사전 파싱 완료: {file_info['name']} ({file_info.get('size', '알 수 없음')})")
                
                # SSE로 UI 업데이트
                from main import notify_status_update
                notify_status_update(db, db_req.id)
            else:
                print(f"[LOG] ⚠️ 파일 정보 파싱 실패 - 파일명을 가져올 수 없음")
        except Exception as e:
            print(f"[LOG] ❌ 파일 정보 사전 파싱 실패: {e}")
    else:
        print(f"[LOG] 파일명이 이미 존재하여 사전 파싱 스킵: {db_req.file_name}")
    
    # 새로운 다운로드 시스템 사용
    print(f"[LOG] 데이터베이스에 저장된 요청 ID: {db_req.id}")
    print(f"[LOG] 다운로드 스레드 시작 준비")
    
    from .download_core import download_1fichier_file_new
    from .shared import download_manager
    import threading
    
    # URL 타입에 따라 적절한 다운로드 함수 선택
    if re.match(r'https?://(?:[^\.]+\.)?1fichier\.com/', db_req.url.lower()):
        # 1fichier 다운로드
        from .download_core import download_1fichier_file_new
        target_function = download_1fichier_file_new
        print(f"[LOG] 1fichier 다운로드 함수 선택: {db_req.url}")
    else:
        # 일반 다운로드
        from .download_core import download_general_file
        target_function = download_general_file
        print(f"[LOG] 일반 다운로드 함수 선택: {db_req.url}")
    
    # 모든 다운로드는 스레드를 시작함 (제한 체크는 각 함수 내부에서)
    thread = threading.Thread(
        target=target_function,
        args=(db_req.id, "ko", request.use_proxy),
        daemon=True
    )
    print(f"[LOG] 스레드 시작 중...")
    thread.start()
    print(f"[LOG] 스레드 시작 완료: {thread.is_alive()}")
    
    # 제한 확인 후 즉시 응답 (비동기 처리)
    if not request.use_proxy:
        # 1fichier 다운로드인 경우 즉시 쿨다운 확인
        if "1fichier.com" in str(request.url).lower():
            cooldown_applied = download_manager.check_immediate_cooldown(db_req.id)
            if cooldown_applied:
                cooldown_remaining = download_manager.get_1fichier_cooldown_remaining()
                return {"id": db_req.id, "status": "cooldown", "message_key": "fichier_cooldown_active", "message_args": {"seconds": max(1, int(cooldown_remaining))}}
        
        if not download_manager.can_start_download(str(request.url)):
            print(f"[LOG] 다운로드 제한으로 대기 상태 예상: {db_req.id}")
            # 어떤 제한인지 확인하여 적절한 메시지 반환
            if len(download_manager.all_downloads) >= download_manager.MAX_TOTAL_DOWNLOADS:
                return {"id": db_req.id, "status": "waiting", "message_key": "total_download_limit_reached", "message_args": {"limit": download_manager.MAX_TOTAL_DOWNLOADS}}
            elif len(download_manager.local_downloads) >= download_manager.MAX_LOCAL_DOWNLOADS:
                return {"id": db_req.id, "status": "waiting", "message_key": "local_download_limit_reached", "message_args": {"limit": download_manager.MAX_LOCAL_DOWNLOADS}}
            else:
                cooldown_remaining = download_manager.get_1fichier_cooldown_remaining()
                if cooldown_remaining > 0:
                    return {"id": db_req.id, "status": "waiting", "message_key": "fichier_cooldown_active", "message_args": {"seconds": max(1, int(cooldown_remaining))}}
                # 쿨다운이 끝난 경우는 정상 진행
    
    return {"id": db_req.id, "status": db_req.status}

@router.get("/history/")
def get_download_history(db: Session = Depends(get_db), limit: int = 100):
    try:
        # 최근 100개만 가져오기 (페이지네이션 최적화)
        history = db.query(DownloadRequest).order_by(DownloadRequest.requested_at.desc()).limit(limit).all()
        print(f"[LOG] History API: Found {len(history)} records (limit: {limit})")
        result = [item.as_dict() for item in history]
        print(f"[LOG] History API: Returning {len(result)} items")
        return result
    except Exception as e:
        print(f"[ERROR] History API failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch history: {str(e)}")

@router.get("/history/{download_id}")
def get_download_detail(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    return item.as_dict()

@router.post("/start-download/{download_id}")
def start_actual_download(download_id: int, db: Session = Depends(get_db)):
    """파싱된 파일의 실제 다운로드 시작"""
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    # pending 상태에서만 다운로드 시작 가능
    if getattr(item, 'status', None) != StatusEnum.pending:
        raise HTTPException(status_code=400, detail=f"Download is not in pending state. Current status: {item.status}")
    
    print(f"[LOG] 실제 다운로드 시작: ID {download_id}, 파일명: {item.file_name}")
    
    # 다운로드 제한 체크
    from .shared import download_manager
    original_use_proxy = getattr(item, 'use_proxy', False)
    
    # 다운로드 제한 체크 (프록시 사용 여부와 관계없이 모든 다운로드에서 체크)
    if not download_manager.can_start_download(item.url):
        # 대기 상태 유지 (다운로드 제한이나 쿨다운 때문에 시작할 수 없음)
        setattr(item, "status", StatusEnum.pending)
        db.commit()
        return {"id": item.id, "status": "waiting", "message": "Download limit reached, staying in queue"}
    
    # 다운로드 시작
    setattr(item, "status", StatusEnum.downloading)
    db.commit()
    
    # URL 타입에 따라 적절한 다운로드 함수 선택
    if "1fichier.com" in item.url.lower():
        from .download_core import download_1fichier_file_new
        target_function = download_1fichier_file_new
    else:
        from .download_core import download_general_file
        target_function = download_general_file
    
    import threading
    
    thread = threading.Thread(
        target=target_function,
        args=(download_id, "ko", original_use_proxy),
        daemon=True
    )
    thread.start()
    
    return {"id": item.id, "status": item.status, "message": "Download started"}

@router.post("/resume/{download_id}")
def resume_download(download_id: int, use_proxy: bool = False, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    # stopped 또는 pending 상태인 경우 재개/시작
    if getattr(item, 'status', None) in [StatusEnum.stopped, StatusEnum.pending]:
        print(f"[LOG] 다운로드 재개 요청: ID {download_id}, 현재 상태: {item.status}")
        
        # 새로운 프록시 설정 적용 (쿼리 파라미터 우선)
        print(f"[LOG] 프록시 설정 - 요청된 use_proxy: {use_proxy}, DB 저장된 use_proxy: {getattr(item, 'use_proxy', None)}")
        
        # 새 설정을 DB에 저장
        setattr(item, 'use_proxy', use_proxy)
        db.commit()
        
        print(f"[LOG] 새 프록시 설정으로 재개: use_proxy={use_proxy}, ID {download_id}")
        
        # 로컬 다운로드인 경우 다운로드 제한 체크
        if not use_proxy:
            from .shared import download_manager
            if not download_manager.can_start_download(item.url):
                # 대기 상태로 설정
                setattr(item, "status", StatusEnum.pending)
                db.commit()
                
                # SSE로 상태 업데이트 알림 (대기 상태)
                try:
                    from main import notify_status_update
                    notify_status_update(db, download_id)
                    print(f"[LOG] ★ 대기 상태 SSE 알림 전송 완료: ID={download_id}")
                except Exception as e:
                    print(f"[LOG] SSE 알림 전송 실패: {e}")
                
                # 어떤 제한인지 확인하고 DB 상태를 pending으로 설정
                if len(download_manager.all_downloads) >= download_manager.MAX_TOTAL_DOWNLOADS:
                    print(f"[LOG] 재개 - 전체 다운로드 제한 도달 ({download_manager.MAX_TOTAL_DOWNLOADS}개). 대기 상태로 설정: {download_id}")
                    setattr(item, "status", StatusEnum.pending)
                    db.commit()
                    return {"id": item.id, "status": "waiting", "message_key": "total_download_limit_reached", "message_args": {"limit": download_manager.MAX_TOTAL_DOWNLOADS}}
                elif len(download_manager.local_downloads) >= download_manager.MAX_LOCAL_DOWNLOADS:
                    print(f"[LOG] 재개 - 1fichier 로컬 다운로드 제한 도달 ({download_manager.MAX_LOCAL_DOWNLOADS}개). 대기 상태로 설정: {download_id}")
                    setattr(item, "status", StatusEnum.pending)
                    db.commit()
                    return {"id": item.id, "status": "waiting", "message_key": "local_download_limit_reached", "message_args": {"limit": download_manager.MAX_LOCAL_DOWNLOADS}}
                else:
                    # 쿨다운 제한인 경우
                    cooldown_remaining = download_manager.get_1fichier_cooldown_remaining()
                    if cooldown_remaining > 0:
                        print(f"[LOG] 재개 - 1fichier 쿨다운 중 ({cooldown_remaining:.1f}초 남음). 대기 상태로 설정: {download_id}")
                        setattr(item, "status", StatusEnum.pending)
                        db.commit()
                        return {"id": item.id, "status": "waiting", "message_key": "fichier_cooldown_active", "message_args": {"seconds": max(1, int(cooldown_remaining))}}
                    # 쿨다운이 끝난 경우는 정상 진행
        
        # 제한에 걸리지 않은 경우 즉시 시작
        setattr(item, "status", StatusEnum.downloading)
        db.commit()
        
        # WebSocket으로 상태 업데이트 알림 (다운로드 시작)
        try:
            from main import notify_status_update
            notify_status_update(db, download_id)
            print(f"[LOG] ★ 재개 SSE 알림 전송 완료: ID={download_id}")
        except Exception as e:
            print(f"[LOG] SSE 알림 전송 실패: {e}")
        
        # URL 타입에 따라 적절한 다운로드 함수 선택 (재시작)
        if "1fichier.com" in item.url.lower():
            from .download_core import download_1fichier_file_new
            target_function = download_1fichier_file_new
        else:
            from .download_core import download_general_file
            target_function = download_general_file
        
        import threading
        
        thread = threading.Thread(
            target=target_function,
            args=(download_id, "ko", use_proxy),
            daemon=True
        )
        thread.start()
        
        # 실제로 이어받기인지 새 다운로드인지 구분하여 메시지 반환
        downloaded_size = getattr(item, 'downloaded_size', 0) or 0
        
        # 실제 파일 존재 여부도 체크
        is_actual_resume = False
        if item.file_name:
            from .config import get_download_path
            from pathlib import Path
            import os
            
            download_dir = Path(get_download_path())
            part_file = download_dir / f"{item.file_name}.part"
            complete_file = download_dir / item.file_name
            
            if part_file.exists() and part_file.stat().st_size > 0:
                is_actual_resume = True
                print(f"[LOG] Resume API - .part 파일 존재: {part_file.stat().st_size} bytes")
            elif complete_file.exists():
                is_actual_resume = True
                print(f"[LOG] Resume API - 완료 파일 존재: {complete_file.stat().st_size} bytes")
        
        print(f"[LOG] Resume API - downloaded_size: {downloaded_size}, file_exists: {is_actual_resume}")
        
        if downloaded_size > 0 or is_actual_resume:
            return {"id": item.id, "status": item.status, "message": "Download resumed"}
        else:
            return {"id": item.id, "status": item.status, "message": "Download started"}
    else:
        raise HTTPException(status_code=400, detail="Download is not in a stopped or pending state")

@router.delete("/delete/{download_id}")
def delete_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    print(f"[LOG] 다운로드 삭제 요청: ID {download_id}, 현재 상태: {item.status}")
    
    # 다운로드 중인 경우 먼저 정지
    if item.status in [StatusEnum.downloading, StatusEnum.proxying, StatusEnum.parsing, StatusEnum.pending]:
        print(f"[LOG] 다운로드 중이므로 먼저 정지: ID {download_id}")
        setattr(item, "status", StatusEnum.stopped)
        db.commit()
        
        # 잠시 대기 (다운로드 함수가 정지를 감지할 시간)
        import time
        time.sleep(1)
    
    # 삭제 전에 다운로드 매니저에서 해제 (대기 중인 다운로드 시작을 위해)
    from .shared import download_manager
    download_manager.unregister_download(download_id)
    
    # DB에서 삭제
    db.delete(item)
    db.commit()
    
    print(f"[LOG] 다운로드 삭제 완료: ID {download_id}")
    
    return {"message": "Download deleted successfully"}

@router.post("/pause/{download_id}")
def pause_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    print(f"[LOG] 다운로드 정지 요청: ID {download_id}, 현재 상태: {item.status}")
    
    # pending, downloading, proxying, parsing 상태만 정지 가능
    if item.status not in [StatusEnum.pending, StatusEnum.downloading, StatusEnum.proxying, StatusEnum.parsing]:
        raise HTTPException(status_code=400, detail=f"현재 상태({item.status})에서는 정지할 수 없습니다")
    
    # 상태를 stopped로 변경
    setattr(item, "status", StatusEnum.stopped)
    db.commit()
    
    print(f"[LOG] 다운로드 상태를 stopped로 변경 완료: ID {download_id}")
    
    # 즉시 정지 플래그 설정 (안전한 즉시 정지)
    from .shared import download_manager
    download_manager.stop_download_immediately(download_id)
    
    # 정지 후 다운로드 매니저에서 해제 (정지 시에는 자동 시작 안 함)
    download_manager.unregister_download(download_id, auto_start_next=False)
    
    # SSE로 상태 업데이트 알림 (강제 새로고침)
    try:
        from main import notify_status_update
        notify_status_update(db, download_id)
        print(f"[LOG] ★ 정지 SSE 알림 전송 완료: ID={download_id}")
        
    except Exception as e:
        print(f"[LOG] SSE 알림 전송 실패: {e}")
    
    return {"id": item.id, "status": item.status, "message": "Download stopped successfully", "success": True}

@router.post("/retry/{download_id}")
def retry_download(download_id: int, db: Session = Depends(get_db)):
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    print(f"[LOG] 다운로드 재시도 요청: ID {download_id}, 현재 상태: {item.status}")
    
    # 원래 프록시 설정 사용 (기본값 없이)
    original_use_proxy = getattr(item, 'use_proxy', None)
    if original_use_proxy is None:
        # DB에 use_proxy가 없는 경우 (구버전 호환) - 기본값 False (로컬)
        original_use_proxy = False
        print(f"[LOG] retry에서 use_proxy 설정이 없어 기본값 False(로컬) 사용: ID {download_id}")
    else:
        print(f"[LOG] retry에서 원래 프록시 설정 사용: use_proxy={original_use_proxy}, ID {download_id}")
    
    # 재시도 시에는 항상 대기 상태로 추가 (큐에서 순서 대기)
    setattr(item, "status", StatusEnum.pending)
    setattr(item, "error", None)
    setattr(item, "direct_link", None)  # 재시도 시 새로운 링크 파싱 강제
    db.commit()
    
    print(f"[LOG] 재시도 요청이 대기 큐에 추가됨: ID {download_id}")
    
    # 프록시 다운로드인 경우 즉시 시작 가능
    if original_use_proxy:
        from .download_core import download_1fichier_file_new
        import threading
        
        setattr(item, "status", StatusEnum.downloading)
        db.commit()
        
        # URL 타입에 따라 적절한 다운로드 함수 선택 (재시도)
        if "1fichier.com" in item.url.lower():
            from .download_core import download_1fichier_file_new
            target_function = download_1fichier_file_new
        else:
            from .download_core import download_general_file
            target_function = download_general_file
        
        thread = threading.Thread(
            target=target_function,
            args=(download_id, "ko", original_use_proxy),
            daemon=True
        )
        thread.start()
        
        return {"id": item.id, "status": item.status, "message": "Download retry started (proxy mode)"}
    else:
        # 로컬 다운로드 - 큐 상황에 따라 즉시 시작 또는 대기
        from core.shared import download_manager
        
        if download_manager.can_start_download(item.url):
            # 즉시 시작 가능
            # URL 타입에 따라 적절한 다운로드 함수 선택 (재시도 로컬)
            if "1fichier.com" in item.url.lower():
                from .download_core import download_1fichier_file_new
                target_function = download_1fichier_file_new
            else:
                from .download_core import download_general_file
                target_function = download_general_file
            
            import threading
            
            setattr(item, "status", StatusEnum.downloading)
            db.commit()
            
            thread = threading.Thread(
                target=target_function,
                args=(download_id, "ko", original_use_proxy),
                daemon=True
            )
            thread.start()
            
            return {"id": item.id, "status": item.status, "message": "Download retry started (local mode)"}
        else:
            # 대기 상태로 유지 (자동 큐 시스템이 처리)
            return {"id": item.id, "status": "waiting", "message": "Download added to queue for retry"}

@router.put("/downloads/{download_id}/proxy-toggle")
def toggle_download_proxy_mode(download_id: int, db: Session = Depends(get_db)):
    """다운로드 항목의 프록시 모드 토글"""
    item = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Download not found")
    
    # 실행 중인 다운로드는 토글 불가
    if item.status not in [StatusEnum.stopped, StatusEnum.failed, StatusEnum.done]:
        raise HTTPException(status_code=400, detail="Cannot toggle proxy mode for active downloads")
    
    # 프록시 모드 토글
    current_use_proxy = getattr(item, 'use_proxy', False)
    new_use_proxy = not current_use_proxy
    setattr(item, 'use_proxy', new_use_proxy)
    db.commit()
    
    print(f"[LOG] 다운로드 ID {download_id} 프록시 모드 변경: {current_use_proxy} -> {new_use_proxy}")
    
    return {
        "id": item.id,
        "use_proxy": new_use_proxy,
        "message": f"Proxy mode changed to {'proxy' if new_use_proxy else 'local'}"
    }

