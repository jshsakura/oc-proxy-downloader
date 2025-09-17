# -*- coding: utf-8 -*-
"""
비동기 다운로드 코어 모듈
- SSE 통합 메시징
- 비동기 다운로드 로직
- 상태 실시간 업데이트
"""

import asyncio
import aiofiles
import aiohttp
import os
import time
import datetime
import json
from pathlib import Path
from typing import Optional, Dict, Any, AsyncGenerator
from sqlalchemy.orm import Session

from .models import DownloadRequest, StatusEnum
from .config import get_download_path
from .db import SessionLocal
from services.sse_manager import sse_manager
from utils.file_helpers import download_file_content, generate_file_path, get_final_file_path


class DownloadCore:
    """비동기 다운로드 코어"""

    def __init__(self):
        self.download_tasks: Dict[int, asyncio.Task] = {}

    async def send_download_update(self, req_id: int, update_data: Dict[str, Any]):
        """통합 다운로드 상태 업데이트 SSE 전송"""
        try:
            await sse_manager.broadcast_message("status_update", {
                "id": req_id,
                **update_data
            })
        except Exception as e:
            print(f"[ERROR] SSE 업데이트 전송 실패: {e}")

    async def send_download_log(self, req_id: int, message: str, level: str = "info"):
        """다운로드 로그 SSE 전송"""
        try:
            await sse_manager.broadcast_message("download_log", {
                "id": req_id,
                "message": message,
                "level": level,
                "timestamp": datetime.datetime.now().isoformat()
            })
        except Exception as e:
            print(f"[ERROR] SSE 로그 전송 실패: {e}")

    async def start_download_async(self, req: DownloadRequest, db: Session) -> bool:
        """비동기 다운로드 시작"""
        try:
            # 상태를 parsing으로 변경
            req.status = StatusEnum.parsing
            req.downloaded_size = 0
            db.commit()

            await self.send_download_update(req.id, {
                "status": "parsing",
                "progress": 0,
                "message": "파싱 시작 중..."
            })

            # 비동기 다운로드 태스크 생성
            task = asyncio.create_task(self._download_task(req.id))
            self.download_tasks[req.id] = task

            # 태스크 완료 콜백 등록
            task.add_done_callback(lambda t: self._task_cleanup(req.id))

            return True

        except Exception as e:
            print(f"[ERROR] 다운로드 시작 실패: {e}")
            await self.send_download_update(req.id, {
                "status": "failed",
                "message": f"다운로드 시작 실패: {str(e)}"
            })
            return False

    async def _download_task(self, req_id: int):
        """실제 다운로드 수행 태스크"""
        db = SessionLocal()
        try:
            req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
            if not req:
                await self.send_download_log(req_id, "다운로드 요청을 찾을 수 없음", "error")
                return

            print(f"[DEBUG] 다운로드 태스크 시작: ID={req_id}, URL={req.url}, USE_PROXY={req.use_proxy}")

            # 다운로드 진행 - URL 기준으로 분기 (원래 로직)
            is_1fichier = "1fichier.com" in req.url

            if is_1fichier:
                print(f"[DEBUG] 1fichier 다운로드 시작: {req_id}")
                await self._download_with_proxy_async(req, db)  # 1fichier는 프록시 다운로드
            else:
                print(f"[DEBUG] 로컬 다운로드 시작: {req_id}")
                await self._download_local_async(req, db)  # 일반 URL은 로컬 다운로드

        except asyncio.CancelledError:
            # 다운로드 취소됨
            req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
            if req:
                req.status = StatusEnum.stopped
                db.commit()
                await self.send_download_update(req_id, {
                    "status": "stopped",
                    "message": "다운로드가 중지되었습니다."
                })
        except Exception as e:
            print(f"[ERROR] 다운로드 태스크 오류: {e}")
            req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
            if req:
                req.status = StatusEnum.failed
                req.error_message = str(e)
                db.commit()
                await self.send_download_update(req_id, {
                    "status": "failed",
                    "message": f"다운로드 실패: {str(e)}"
                })
        finally:
            db.close()

    async def _download_with_proxy_async(self, req: DownloadRequest, db: Session):
        """1fichier 프록시 다운로드 (원래 함수명)"""
        print(f"[DEBUG] _download_with_proxy_async 시작: {req.id}")
        await self.send_download_log(req.id, "1fichier 다운로드 시작")

        # 파싱 단계
        print(f"[DEBUG] 파싱 단계 시작: {req.id}")
        await self.send_download_update(req.id, {
            "status": "parsing",
            "progress": 0,
            "message": "링크 파싱 중..."
        })

        # 실제 1fichier 파싱 로직 실행
        try:
            from core.simple_parser import parse_1fichier_simple, preparse_1fichier_standalone

            # 프록시 설정 (간소화)
            proxies = None
            proxy_addr = None
            # TODO: 필요시 프록시 설정

            # 1fichier 파싱 실행 (이미 비동기 함수)
            # 1fichier인 경우에만 original_url 사용, 일반 다운로드는 현재 url 사용
            if "1fichier.com" in (req.original_url or req.url):
                parse_url = req.original_url if req.original_url else req.url
                print(f"[DEBUG] 1fichier 파싱 URL: {parse_url}")

                # 즉시 사전파싱으로 파일명/크기 추출
                print(f"[LOG] 사전파싱 시작: {req.id}")
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    preparse_info = await loop.run_in_executor(None, preparse_1fichier_standalone, parse_url)

                    if preparse_info:
                        if preparse_info.get('name') and not req.file_name:
                            req.file_name = preparse_info['name']
                            print(f"[LOG] 사전파싱 파일명: {req.file_name}")

                        if preparse_info.get('size') and not req.file_size:
                            req.file_size = preparse_info['size']
                            print(f"[LOG] 사전파싱 파일크기: {req.file_size}")

                        db.commit()

                        # 즉시 SSE로 파일 정보 전송
                        sse_data = {
                            "id": req.id,
                            "filename": req.file_name,
                            "file_size": req.file_size
                        }
                        print(f"[LOG] SSE filename_update 전송 시작: {sse_data}")
                        await sse_manager.broadcast_message("filename_update", sse_data)
                        print(f"[LOG] 사전파싱 완료 - SSE 전송 완료")
                except Exception as preparse_error:
                    print(f"[WARNING] 사전파싱 실패: {preparse_error}")
            else:
                parse_url = req.url
                print(f"[DEBUG] 일반 다운로드 URL: {parse_url}")

                # 일반 다운로드도 URL에서 파일명 추출 시도
                print(f"[LOG] 일반 다운로드 파일명 추출 시작: {parse_url}")
                try:
                    from urllib.parse import urlparse, unquote
                    parsed_url = urlparse(parse_url)
                    path = unquote(parsed_url.path)
                    filename = path.split('/')[-1] if '/' in path else path
                    print(f"[LOG] URL 파싱 결과 - path: {path}, filename: {filename}")

                    if filename and '.' in filename and not req.file_name:
                        req.file_name = filename
                        db.commit()
                        print(f"[LOG] 일반 다운로드 파일명 추출: {filename}")

                        # SSE로 파일 정보 전송
                        await sse_manager.broadcast_message("filename_update", {
                            "id": req.id,
                            "filename": req.file_name,
                            "file_size": req.file_size
                        })
                except Exception as url_parse_error:
                    print(f"[WARNING] URL 파일명 추출 실패: {url_parse_error}")

            # 1fichier만 파싱 로직 실행
            if "1fichier.com" in parse_url:
                parse_result = await parse_1fichier_simple(
                    parse_url,
                    req.password,
                    proxies,
                    proxy_addr,
                    req.id  # download_id 전달
                )
            else:
                # 일반 다운로드는 파싱 없이 바로 다운로드
                parse_result = {
                    'download_link': parse_url,  # 원본 URL을 다운로드 링크로 사용
                    'file_info': None,
                    'wait_time': None
                }

            # 1fichier 파일 정보가 있으면 즉시 저장 (사전파싱)
            if parse_result and parse_result.get('file_info'):
                file_info = parse_result['file_info']
                if file_info.get('name') and not req.file_name:
                    req.file_name = file_info['name']
                    print(f"[LOG] 파일명 저장: {req.file_name}")

                if file_info.get('size') and not req.file_size:
                    req.file_size = file_info['size']
                    print(f"[LOG] 파일크기 저장: {req.file_size}")

                db.commit()

                # SSE로 파일 정보 즉시 전송
                print(f"[LOG] SSE로 파일 정보 전송 중: ID={req.id}, 파일명={req.file_name}, 크기={req.file_size}")
                await sse_manager.broadcast_message("filename_update", {
                    "id": req.id,
                    "filename": req.file_name,
                    "file_size": req.file_size
                })
                print(f"[LOG] SSE 파일 정보 전송 완료")

            if parse_result and parse_result.get('wait_time'):
                # 대기시간이 있는 경우
                wait_seconds = parse_result['wait_time']
                req.status = StatusEnum.waiting
                db.commit()

                await self.send_download_update(req.id, {
                    "status": "waiting",
                    "progress": 0,
                    "message": f"{wait_seconds}초 대기 중..."
                })

                # 대기시간 동안 실제 대기
                await asyncio.sleep(wait_seconds)

            # 다운로드 링크 확인
            if parse_result and parse_result.get('download_link'):
                download_url = parse_result['download_link']
                print(f"[LOG] 다운로드 링크 획득: {download_url}")

                # 1fichier인 경우에만 원본 URL 저장 (처음 한 번만)
                if not req.original_url and "1fichier.com" in parse_url:
                    req.original_url = download_url  # 파싱된 다운로드 링크를 저장
                    db.commit()

                # URL은 변경하지 않고, 다운로드만 새로운 링크로 진행

                print(f"[DEBUG] 다운로드 상태를 downloading으로 변경: {req.id}")

                await self.send_download_update(req.id, {
                    "status": "downloading",
                    "progress": 0,
                    "message": "downloading_in_progress"
                })

                # 즉시 파일 다운로드 시작
                req.status = StatusEnum.downloading
                db.commit()

                print(f"[DEBUG] _perform_file_download_async 호출 시작: {req.id}")
                await self._perform_file_download_async(req, db, download_url)
                print(f"[DEBUG] _perform_file_download_async 완료: {req.id}")
                return True
            else:
                print(f"[LOG] 다운로드 링크 추출 실패 - 파일 정보는 저장 완료, 재시도 가능")
                # 파일 정보는 저장되었으므로 대기 상태로 두어 재시도 가능하게 함
                req.status = StatusEnum.pending
                req.error = "다운로드 링크 추출 실패 - 재시도 버튼으로 다시 시도하세요"
                db.commit()

                await self.send_download_update(req.id, {
                    "status": "pending",
                    "message": "다운로드 링크 추출 실패 - 재시도 가능"
                })
                return True  # 파일 정보 저장은 성공했으므로 True 반환

        except Exception as e:
            print(f"[ERROR] 1fichier 파싱 실패: {e}")
            import traceback
            print(f"[ERROR] 파싱 오류 상세:\n{traceback.format_exc()}")

            # 파싱 실패 시 실패 처리
            req.status = StatusEnum.failed
            req.error = f"파싱 실패: {str(e)}"
            req.finished_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "failed",
                "message": f"파싱 실패: {str(e)}"
            })
            return False

    async def _download_local_async(self, req: DownloadRequest, db: Session):
        """순수 로컬 다운로드 비동기 구현 (1fichier 제외)"""
        print(f"[DEBUG] _download_local_async 시작: {req.id}")
        await self.send_download_log(req.id, "로컬 다운로드 시작")

        # 로컬 다운로드 로직
        req.status = StatusEnum.downloading
        db.commit()

        await self.send_download_update(req.id, {
            "status": "downloading",
            "progress": 0,
            "message": "로컬 다운로드 중..."
        })

        # 실제 로컬 다운로드 구현
        await self._perform_local_download_async(req, db)

    async def _perform_file_download_async(self, req: DownloadRequest, db: Session, download_url: str = None):
        """실제 파일 다운로드 수행"""
        try:
            print(f"[DEBUG] 파일 다운로드 시작: {req.id}")

            # 파일 저장 경로 생성 (.part 확장자 포함)
            print(f"[LOG] 다운로드 파일명 확인: req.file_name={req.file_name}, save_path={req.save_path}")
            if not req.save_path:
                filename_to_use = req.file_name or f"download_{req.id}"
                print(f"[LOG] 파일명 결정: '{filename_to_use}'")
                req.save_path = generate_file_path(filename_to_use, is_temporary=True)
                print(f"[LOG] 생성된 저장 경로: '{req.save_path}'")
                db.commit()

            # HTTP 요청으로 파일 다운로드 (긴 타임아웃 설정)
            timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=300)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {}
                initial_size = 0

                # 기존 파일 확인 (이어받기 지원)
                if os.path.exists(req.save_path):
                    initial_size = os.path.getsize(req.save_path)
                    headers['Range'] = f'bytes={initial_size}-'
                    print(f"[DEBUG] 이어받기: {initial_size} bytes")

                actual_url = download_url if download_url else req.url
                async with session.get(actual_url, headers=headers) as response:
                    if response.status not in [200, 206]:
                        raise Exception(f"HTTP {response.status}: {response.reason}")

                    # Content-Length 가져오기
                    content_length = response.headers.get('Content-Length')
                    if content_length:
                        req.total_size = int(content_length) + initial_size
                        db.commit()

                    # 실제 파일 다운로드
                    print(f"[DEBUG] 파일 다운로드 시작 - 초기크기: {initial_size}, 총크기: {req.total_size}")
                    downloaded_size = await download_file_content(
                        response, req.save_path, initial_size, req.total_size, req, db
                    )
                    print(f"[DEBUG] 파일 다운로드 완료 - 최종크기: {downloaded_size}")

                    # .part 파일을 최종 파일명으로 리네임
                    final_path = get_final_file_path(req.save_path)
                    if req.save_path != final_path:
                        try:
                            import shutil
                            shutil.move(req.save_path, final_path)
                            print(f"[DEBUG] 파일 리네임: {req.save_path} -> {final_path}")
                            req.save_path = final_path
                        except Exception as rename_error:
                            print(f"[WARNING] 파일 리네임 실패: {rename_error}")

                    # 완료 처리
                    print(f"[LOG] 다운로드 완료 처리 시작: {req.id}")
                    req.status = StatusEnum.done
                    req.downloaded_size = downloaded_size
                    req.finished_at = datetime.datetime.now()
                    print(f"[LOG] 상태를 done으로 변경 완료")

                    db.commit()
                    print(f"[LOG] 데이터베이스 커밋 완료")

                    await self.send_download_update(req.id, {
                        "status": "done",
                        "progress": 100,
                        "message": f"다운로드 완료! 저장 위치: {req.save_path}"
                    })
                    print(f"[LOG] SSE 완료 메시지 전송 완료")

                    print(f"[LOG] 다운로드 완료 처리 전체 완료: {req.save_path}")

        except Exception as e:
            print(f"[ERROR] 파일 다운로드 실패: {e}")
            req.status = StatusEnum.failed
            req.error = str(e)
            req.finished_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "failed",
                "message": f"다운로드 실패: {str(e)}"
            })
        finally:
            # 강제 상태 확인 및 로그
            try:
                db.refresh(req)
                print(f"[LOG] 최종 상태 확인: ID={req.id}, 상태={req.status}, 완료시간={req.finished_at}")
            except Exception as final_error:
                print(f"[ERROR] 최종 상태 확인 실패: {final_error}")

    async def _perform_local_download_async(self, req: DownloadRequest, db: Session):
        """로컬 다운로드 수행"""
        try:
            print(f"[DEBUG] 로컬 다운로드 시작: {req.id}")

            # 파일명 추출 (아직 추출되지 않은 경우)
            if not req.file_name:
                await self._extract_filename_from_url(req, db)

            # 실제 파일 다운로드 수행
            await self._perform_file_download_async(req, db)

        except Exception as e:
            print(f"[ERROR] 로컬 다운로드 실패: {e}")
            req.status = StatusEnum.failed
            req.error = str(e)
            req.finished_at = datetime.datetime.now()
            db.commit()

            await self.send_download_update(req.id, {
                "status": "failed",
                "message": f"로컬 다운로드 실패: {str(e)}"
            })
            raise Exception(f"로컬 다운로드 실패: {e}")

    async def stop_download_async(self, req_id: int, db: Session) -> bool:
        """비동기 다운로드 중지"""
        try:
            # 실행 중인 태스크 취소
            if req_id in self.download_tasks:
                task = self.download_tasks[req_id]
                task.cancel()

                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

            # DB 상태 업데이트
            req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()
            if req:
                req.status = StatusEnum.stopped
                db.commit()

                await self.send_download_update(req_id, {
                    "status": "stopped",
                    "message": "다운로드가 중지되었습니다."
                })

            return True

        except Exception as e:
            print(f"[ERROR] 다운로드 중지 실패: {e}")
            return False

    async def _extract_filename_from_url(self, req: DownloadRequest, db: Session):
        """URL에서 파일명 추출"""
        try:
            print(f"[LOG] URL에서 파일명 추출 시도: {req.url}")

            from urllib.parse import urlparse, unquote
            import re

            parsed_url = urlparse(req.url)
            path = unquote(parsed_url.path)

            # Opendrive 특수 처리
            if "opendrive.com" in req.url.lower():
                # URL 패턴: https://www.opendrive.com/d/ODlfMzkzMTYwMTlf/Hollow%20Knight%20Silksong_U%201.0.28497%20%28Kor%29.nsp
                # 파일명이 URL 경로에 포함되어 있음
                path_parts = path.split('/')
                if len(path_parts) >= 3:
                    filename = unquote(path_parts[-1])  # 마지막 부분이 파일명
                    if filename and '.' in filename:
                        req.file_name = filename
                        print(f"[LOG] Opendrive 파일명 추출: {filename}")
                        db.commit()

                        # 새로운 파일명으로 저장 경로 재설정
                        req.save_path = generate_file_path(req.file_name, is_temporary=True)
                        print(f"[LOG] Opendrive 저장경로 재설정: {req.save_path}")

                        # SSE로 파일명 업데이트 전송
                        await sse_manager.broadcast_message("filename_update", {
                            "id": req.id,
                            "filename": req.file_name,
                            "file_size": req.file_size
                        })
                        return

            # 일반적인 URL에서 파일명 추출
            if path and '/' in path:
                filename = path.split('/')[-1]
                if filename and '.' in filename:
                    req.file_name = filename
                    print(f"[LOG] 일반 URL 파일명 추출: {filename}")

                    # 새로운 파일명으로 저장 경로 재설정
                    req.save_path = generate_file_path(req.file_name, is_temporary=True)
                    print(f"[LOG] 일반 URL 저장경로 재설정: {req.save_path}")
                    db.commit()

                    # SSE로 파일명 업데이트 전송
                    await sse_manager.broadcast_message("filename_update", {
                        "id": req.id,
                        "filename": req.file_name,
                        "file_size": req.file_size
                    })
                    return

            # Content-Disposition 헤더에서 파일명 추출 시도
            try:
                import aiohttp
                timeout = aiohttp.ClientTimeout(total=30, connect=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.head(req.url) as response:
                        if response.status == 200:
                            content_disposition = response.headers.get('Content-Disposition', '')
                            if content_disposition:
                                # Content-Disposition: attachment; filename="filename.ext"
                                filename_match = re.search(r'filename[*]?=([^;]+)', content_disposition, re.IGNORECASE)
                                if filename_match:
                                    filename = filename_match.group(1).strip().strip('"\'')
                                    if filename:
                                        req.file_name = filename
                                        print(f"[LOG] Content-Disposition에서 파일명 추출: {filename}")

                                        # 새로운 파일명으로 저장 경로 재설정
                                        req.save_path = generate_file_path(req.file_name, is_temporary=True)
                                        print(f"[LOG] Content-Disposition 저장경로 재설정: {req.save_path}")
                                        db.commit()

                                        # SSE로 파일명 업데이트 전송
                                        await sse_manager.broadcast_message("filename_update", {
                                            "id": req.id,
                                            "filename": req.file_name,
                                            "file_size": req.file_size
                                        })
                                        return
            except Exception as head_error:
                print(f"[WARNING] HEAD 요청 실패: {head_error}")

            print(f"[WARNING] URL에서 파일명 추출 실패: {req.url}")

        except Exception as e:
            print(f"[ERROR] 파일명 추출 실패: {e}")

    def _task_cleanup(self, req_id: int):
        """태스크 정리"""
        if req_id in self.download_tasks:
            del self.download_tasks[req_id]
            print(f"[LOG] 다운로드 태스크 정리: {req_id}")

    async def get_download_status(self, req_id: int) -> Dict[str, Any]:
        """다운로드 상태 조회"""
        try:
            db = SessionLocal()
            req = db.query(DownloadRequest).filter(DownloadRequest.id == req_id).first()

            if not req:
                return {"error": "다운로드 요청을 찾을 수 없음"}

            return {
                "id": req.id,
                "status": req.status.value if req.status else "unknown",
                "progress": round((req.downloaded_size / req.total_size * 100), 1) if req.total_size and req.total_size > 0 else 0,
                "url": req.url,
                "filename": req.file_name,
                "error_message": req.error
            }
        except Exception as e:
            return {"error": f"상태 조회 실패: {e}"}
        finally:
            db.close()

    async def cleanup_all_tasks(self):
        """모든 다운로드 태스크 정리"""
        for req_id, task in list(self.download_tasks.items()):
            try:
                task.cancel()
                await asyncio.wait_for(task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            finally:
                if req_id in self.download_tasks:
                    del self.download_tasks[req_id]

        print(f"[LOG] 모든 다운로드 태스크 정리 완료")


# 전역 인스턴스
download_core = DownloadCore()