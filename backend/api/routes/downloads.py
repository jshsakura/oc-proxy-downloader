# -*- coding: utf-8 -*-
"""
비동기 다운로드 API 라우터
- 비동기 다운로드 시작/중지
- SSE를 통한 실시간 상태 업데이트
- 유기적 프론트엔드 통신
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
import asyncio
import httpx
import re
from urllib.parse import urlparse, unquote

from core.db import get_db
from core.models import DownloadRequest, StatusEnum
from core.download_core import download_core
from core.parser import fichier_parser
from core.simple_parser import parse_1fichier_simple_sync
from services.sse_manager import sse_manager

router = APIRouter(prefix="/api", tags=["downloads"])



@router.post("/download/")
async def add_download(
    request: dict,
    db: Session = Depends(get_db)
):
    """새 다운로드 요청 추가"""
    try:
        url = request.get("url", "").strip()
        password = request.get("password", "")
        use_proxy = request.get("use_proxy", False)

        if not url:
            raise HTTPException(status_code=400, detail="URL이 필요합니다")

        # 새 다운로드 요청 생성
        new_request = DownloadRequest(
            url=url,
            original_url=url if "1fichier.com" in url else None,  # 1fichier인 경우에만 원본 URL 설정
            password=password if password else None,
            use_proxy=use_proxy,
            status=StatusEnum.pending
        )

        db.add(new_request)
        db.commit()
        db.refresh(new_request)

        # 즉시 다운로드 시작
        print(f"[LOG] 다운로드 즉시 시작: {new_request.id}")
        success = await download_core.start_download_async(new_request, db)

        if success:
            # SSE로 다운로드 시작 알림
            await sse_manager.broadcast_message("download_started", {
                "id": new_request.id,
                "url": url,
                "status": "parsing",
                "message": "다운로드가 시작되었습니다"
            })
        else:
            # 실패 시에도 사용자에게 알림
            await sse_manager.broadcast_message("download_added", {
                "id": new_request.id,
                "url": url,
                "status": "failed",
                "message": "다운로드 시작 실패"
            })


        return {
            "success": True,
            "message": "다운로드가 추가되었습니다",
            "id": new_request.id,
            "url": url,
            "status": "pending"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 다운로드 추가 API 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")


@router.post("/downloads/start/{download_id}")
async def start_download(download_id: int, db: Session = Depends(get_db)):
    """비동기 다운로드 시작"""
    try:
        # 다운로드 요청 조회
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다")

        # 이미 실행 중인지 확인
        if req.status in [StatusEnum.parsing, StatusEnum.downloading, StatusEnum.waiting]:
            raise HTTPException(status_code=400, detail="이미 실행 중인 다운로드입니다")

        # 비동기 다운로드 시작
        success = await download_core.start_download_async(req, db)

        if success:
            # SSE로 즉시 상태 알림
            await sse_manager.broadcast_message("download_started", {
                "id": download_id,
                "status": "parsing",
                "message": "다운로드가 시작되었습니다"
            })

            return {
                "success": True,
                "message": "다운로드가 시작되었습니다",
                "id": download_id
            }
        else:
            raise HTTPException(status_code=500, detail="다운로드 시작에 실패했습니다")

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 다운로드 시작 API 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")


@router.post("/resume/{download_id}")
async def resume_download(download_id: int, use_proxy: Optional[bool] = None, db: Session = Depends(get_db)):
    """비동기 다운로드 재시작/이어받기"""
    try:
        # 다운로드 요청 조회
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다")

        # 이미 실행 중인지 확인
        if req.status in [StatusEnum.parsing, StatusEnum.downloading, StatusEnum.waiting]:
            raise HTTPException(status_code=400, detail="이미 실행 중인 다운로드입니다")

        # 완료된 다운로드는 재시작 불가
        if req.status == StatusEnum.done:
            raise HTTPException(status_code=400, detail="이미 완료된 다운로드입니다")

        # 프록시 설정 업데이트 (요청에 포함된 경우)
        if use_proxy is not None:
            req.use_proxy = use_proxy

        # 비동기 다운로드 시작 (resume은 start와 동일한 로직)
        success = await download_core.start_download_async(req, db)

        if success:
            # SSE로 즉시 상태 알림
            await sse_manager.broadcast_message("download_resumed", {
                "id": download_id,
                "status": "parsing",
                "message": "다운로드가 재시작되었습니다"
            })

            return {
                "success": True,
                "message": "다운로드가 재시작되었습니다",
                "id": download_id
            }
        else:
            raise HTTPException(status_code=500, detail="다운로드 재시작에 실패했습니다")

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 다운로드 재시작 API 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")


@router.post("/retry/{download_id}")
async def retry_download(
    download_id: int,
    db: Session = Depends(get_db)
):
    """실패한 다운로드 재시도"""
    try:
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Download request not found")

        if req.status not in [StatusEnum.failed, StatusEnum.stopped]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot retry in current status: {req.status}"
            )

        # 만료된 링크에 대한 로깅 (URL 복원 불필요 - 파싱 시 original_url 자동 사용)
        if req.error and "410" in str(req.error):
            print(f"[LOG] 만료된 다운로드 링크 감지, 재파싱으로 새 링크 획득 예정")

        if req.url and "1fichier.com/c" in req.url:
            print(f"[LOG] 1fichier 직접 다운로드 링크, 재파싱으로 새 링크 획득 예정")

        # 상태를 pending으로 변경하고 오류 메시지 초기화
        req.status = StatusEnum.pending
        req.error = None
        req.downloaded_size = 0  # 처음부터 다시 시작
        req.finished_at = None
        db.commit()

        # 비동기 다운로드 시작
        success = await download_core.start_download_async(req, db)

        if success:
            # SSE로 즉시 상태 알림
            await sse_manager.broadcast_message("download_retried", {
                "id": download_id,
                "status": "parsing",
                "message": "retry_request_sent"
            })

            return {
                "success": True,
                "message": "retry_request_sent",
                "id": download_id
            }
        else:
            raise HTTPException(status_code=500, detail="Retry failed")

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 다운로드 재시도 실패: {e}")
        raise HTTPException(status_code=500, detail=f"Retry failed: {str(e)}")


@router.post("/downloads/stop/{download_id}")
async def stop_download(download_id: int, db: Session = Depends(get_db)):
    """비동기 다운로드 중지"""
    try:
        # 다운로드 요청 조회
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다")

        # 비동기 다운로드 중지
        success = await download_core.stop_download_async(download_id, db)

        if success:
            # 최신 다운로드 상태 조회
            updated_req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()

            # SSE로 즉시 상태 알림
            await sse_manager.broadcast_message("download_stopped", {
                "id": download_id,
                "status": "stopped",
                "progress": 0,
                "message": "다운로드가 중지되었습니다"
            })

            # 추가로 download_updated 메시지도 전송하여 UI 즉시 갱신
            if updated_req:
                await sse_manager.broadcast_message("download_updated", {
                    "id": download_id,
                    "status": updated_req.status.value,
                    "progress": updated_req.progress or 0,
                    "message": updated_req.message or "다운로드가 중지되었습니다"
                })


            return {
                "success": True,
                "message": "stop_request_sent",
                "id": download_id
            }
        else:
            raise HTTPException(status_code=500, detail="다운로드 중지에 실패했습니다")

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 다운로드 중지 API 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")


@router.get("/downloads/status/{download_id}")
async def get_download_status(download_id: int):
    """비동기 다운로드 상태 조회"""
    try:
        status = await download_core.get_download_status(download_id)
        return status
    except Exception as e:
        print(f"[ERROR] 다운로드 상태 조회 오류: {e}")
        raise HTTPException(status_code=500, detail=f"상태 조회 실패: {str(e)}")


@router.post("/downloads/batch-start")
async def start_batch_downloads(download_ids: List[int], db: Session = Depends(get_db)):
    """배치 다운로드 시작"""
    try:
        results = []

        for download_id in download_ids:
            req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
            if not req:
                results.append({"id": download_id, "success": False, "message": "요청을 찾을 수 없음"})
                continue

            if req.status in [StatusEnum.parsing, StatusEnum.downloading, StatusEnum.waiting]:
                results.append({"id": download_id, "success": False, "message": "이미 실행 중"})
                continue

            # 비동기 다운로드 시작
            success = await download_core.start_download_async(req, db)
            results.append({
                "id": download_id,
                "success": success,
                "message": "시작됨" if success else "시작 실패"
            })

            if success:
                # SSE 알림
                await sse_manager.broadcast_message("download_started", {
                    "id": download_id,
                    "status": "parsing",
                    "message": "배치 다운로드 시작"
                })

        # 배치 시작 완료 알림
        await sse_manager.broadcast_message("batch_started", {
            "message": f"{len([r for r in results if r['success']])}개 다운로드가 시작되었습니다",
            "results": results
        })

        return {
            "success": True,
            "message": f"{len(results)}개 다운로드 처리 완료",
            "results": results
        }

    except Exception as e:
        print(f"[ERROR] 배치 다운로드 시작 오류: {e}")
        raise HTTPException(status_code=500, detail=f"배치 시작 실패: {str(e)}")


@router.post("/downloads/batch-stop")
async def stop_batch_downloads(download_ids: List[int], db: Session = Depends(get_db)):
    """배치 다운로드 중지"""
    try:
        results = []

        for download_id in download_ids:
            success = await download_core.stop_download_async(download_id, db)
            results.append({
                "id": download_id,
                "success": success,
                "message": "중지됨" if success else "중지 실패"
            })

            if success:
                # SSE 알림
                await sse_manager.broadcast_message("download_stopped", {
                    "id": download_id,
                    "status": "stopped",
                    "message": "배치 다운로드 중지"
                })

        # 배치 중지 완료 알림
        await sse_manager.broadcast_message("batch_stopped", {
            "message": f"{len([r for r in results if r['success']])}개 다운로드가 중지되었습니다",
            "results": results
        })

        return {
            "success": True,
            "message": f"{len(results)}개 다운로드 처리 완료",
            "results": results
        }

    except Exception as e:
        print(f"[ERROR] 배치 다운로드 중지 오류: {e}")
        raise HTTPException(status_code=500, detail=f"배치 중지 실패: {str(e)}")


@router.delete("/delete/{download_id}")
async def delete_download(download_id: int, db: Session = Depends(get_db)):
    """다운로드 삭제"""
    try:
        # 다운로드 요청 조회
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다")

        # 실행 중인 다운로드는 먼저 중지
        if req.status in [StatusEnum.parsing, StatusEnum.downloading, StatusEnum.waiting]:
            await download_core.stop_download_async(download_id, db)

        # 데이터베이스에서 삭제
        db.delete(req)
        db.commit()

        # SSE로 삭제 알림
        await sse_manager.broadcast_message("download_deleted", {
            "id": download_id,
            "message": "다운로드가 삭제되었습니다"
        })

        return {
            "success": True,
            "message": "다운로드가 삭제되었습니다",
            "id": download_id
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 다운로드 삭제 API 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")


@router.post("/downloads/force-refresh")
async def force_refresh_downloads():
    """프론트엔드 강제 새로고침 요청"""
    try:
        await sse_manager.broadcast_message("force_refresh", {
            "message": "다운로드 목록을 새로고침하세요",
            "timestamp": asyncio.get_event_loop().time()
        })

        return {
            "success": True,
            "message": "강제 새로고침 신호를 전송했습니다"
        }

    except Exception as e:
        print(f"[ERROR] 강제 새로고침 오류: {e}")
        raise HTTPException(status_code=500, detail=f"새로고침 실패: {str(e)}")


@router.put("/downloads/{download_id}/proxy-toggle")
async def toggle_proxy_mode(download_id: int, db: Session = Depends(get_db)):
    """다운로드 프록시 모드 토글"""
    try:
        # 다운로드 요청 조회
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다")

        # 실행 중인 다운로드는 토글 불가
        if req.status in [StatusEnum.parsing, StatusEnum.downloading, StatusEnum.waiting]:
            raise HTTPException(status_code=400, detail="실행 중인 다운로드는 프록시 모드를 변경할 수 없습니다")

        # 프록시 모드 토글
        req.use_proxy = not req.use_proxy
        db.commit()

        # SSE로 상태 변경 알림
        await sse_manager.broadcast_message("proxy_toggled", {
            "id": download_id,
            "use_proxy": req.use_proxy,
            "message": f"프록시 모드가 {'활성화' if req.use_proxy else '비활성화'}되었습니다"
        })

        return {
            "success": True,
            "use_proxy": req.use_proxy,
            "message": f"프록시 모드가 {'활성화' if req.use_proxy else '비활성화'}되었습니다"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 프록시 토글 API 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")


@router.get("/downloads/health-check")
async def download_health_check():
    """다운로드 시스템 헬스 체크"""
    try:
        active_tasks = len(download_core.download_tasks)
        sse_connections = len(sse_manager.connections)

        return {
            "success": True,
            "message": "다운로드 시스템 정상",
            "stats": {
                "active_downloads": active_tasks,
                "sse_connections": sse_connections,
                "system_status": "healthy"
            }
        }

    except Exception as e:
        print(f"[ERROR] 헬스 체크 오류: {e}")
        return {
            "success": False,
            "message": f"시스템 오류: {str(e)}",
            "stats": {
                "active_downloads": 0,
                "sse_connections": 0,
                "system_status": "unhealthy"
            }
        }


async def _perform_pre_parsing(req: DownloadRequest, db: Session):
    """파일 정보 사전 파싱 (파일명, 크기 추출)"""
    try:
        print(f"[LOG] 사전 파싱 시작: {req.url}")

        # URL 타입 판단
        is_1fichier = "1fichier.com" in req.url

        if is_1fichier:
            # 1fichier 파싱 - 간단한 HTTP 요청으로 파일 정보만 추출
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            # 프록시 설정
            client_kwargs = {"headers": headers, "timeout": 10.0}
            if req.use_proxy:
                # TODO: 프록시 설정이 필요하면 여기서 추가
                # client_kwargs["proxies"] = {"http": "proxy_url", "https": "proxy_url"}
                pass

            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(req.url)

                if response.status_code == 200:
                    # 파일 정보 추출
                    file_info = fichier_parser.extract_file_info(response.text)

                    if file_info and file_info.get('name'):
                        req.file_name = file_info['name']
                        print(f"[LOG] 파일명 추출: {req.file_name}")

                    if file_info and file_info.get('size'):
                        # 크기 정보를 바이트로 변환
                        size_str = file_info['size']
                        try:
                            # "1.5 GB" -> 바이트 변환
                            size_match = re.search(r'(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)', size_str, re.IGNORECASE)
                            if size_match:
                                size_value = float(size_match.group(1))
                                size_unit = size_match.group(2).upper()

                                multipliers = {'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
                                total_bytes = int(size_value * multipliers.get(size_unit, 1))

                                req.total_size = total_bytes
                                print(f"[LOG] 파일 크기 추출: {size_str} ({total_bytes} bytes)")
                        except Exception as e:
                            print(f"[WARN] 크기 변환 실패: {e}")

                    # DB 업데이트
                    db.commit()

                    # SSE로 파일 정보 업데이트 알림
                    await sse_manager.broadcast_message("file_info_updated", {
                        "id": req.id,
                        "filename": req.file_name,
                        "total_size": req.total_size,
                        "message": "파일 정보가 업데이트되었습니다"
                    })

                    print(f"[LOG] 사전 파싱 완료: {req.file_name} ({file_info.get('size', 'Unknown size')})")
                else:
                    print(f"[WARN] HTTP {response.status_code}: 사전 파싱을 위한 페이지 로드 실패")

        else:
            # 일반 다운로드 - URL에서 파일명 추출 시도
            print(f"[LOG] 일반 다운로드 파일명 추출 시작: {req.url}")
            parsed_url = urlparse(req.url)
            path = unquote(parsed_url.path)
            filename = path.split('/')[-1] if '/' in path else path
            print(f"[LOG] URL 파싱 결과 - path: {path}, filename: {filename}")

            if filename and '.' in filename:
                old_name = req.file_name
                req.file_name = filename
                db.commit()
                print(f"[LOG] 파일명 업데이트: {old_name} → {filename}")

                # SSE로 파일 정보 업데이트 알림
                await sse_manager.broadcast_message("filename_update", {
                    "id": req.id,
                    "filename": req.file_name,
                    "file_size": req.file_size
                })

                print(f"[LOG] 일반 다운로드 파일명 추출 완료: {filename}")
            else:
                print(f"[WARNING] URL에서 유효한 파일명을 추출할 수 없음: {filename}")

    except Exception as e:
        print(f"[ERROR] 사전 파싱 실패: {e}")
        raise e


@router.post("/downloads/stop-all")
async def stop_all_downloads(db: Session = Depends(get_db)):
    """모든 다운로드 정지"""
    try:
        # 진행 중인 모든 다운로드 찾기 (pending, downloading, parsing)
        active_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([StatusEnum.pending, StatusEnum.downloading, StatusEnum.parsing])
        ).all()

        stopped_count = 0
        for download in active_downloads:
            download.status = StatusEnum.stopped
            download.error_message = "사용자에 의해 일괄 정지됨"
            stopped_count += 1

            # SSE로 정지 상태 전송
            await sse_manager.broadcast_message("status_update", {
                "id": download.id,
                "status": "stopped",
                "message": "일괄 정지됨"
            })

        if stopped_count > 0:
            db.commit()
            print(f"[LOG] {stopped_count}개 다운로드 일괄 정지 완료")

        # 전체 상태 업데이트 완료 알림 (프론트엔드 새로고침 트리거)
        await sse_manager.broadcast_message("force_refresh", {
            "message": f"{stopped_count}개 다운로드가 정지되었습니다.",
            "timestamp": asyncio.get_event_loop().time()
        })

        return {
            "success": True,
            "message": f"{stopped_count}개 다운로드가 정지되었습니다.",
            "stopped_count": stopped_count
        }

    except Exception as e:
        print(f"[ERROR] 일괄 정지 실패: {e}")
        raise HTTPException(status_code=500, detail=f"일괄 정지 실패: {str(e)}")


@router.post("/downloads/restart-failed")
async def restart_failed_downloads(db: Session = Depends(get_db)):
    """실패/정지된 다운로드 재시작"""
    try:
        # 실패 또는 정지 상태인 다운로드 찾기
        failed_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([StatusEnum.failed, StatusEnum.stopped])
        ).all()

        restarted_count = 0
        # 배치 처리로 DB 연결 절약 (10개씩 처리)
        batch_size = 10
        for i in range(0, len(failed_downloads), batch_size):
            batch = failed_downloads[i:i + batch_size]
            for download in batch:
                # 상태를 pending으로 변경
                download.status = StatusEnum.pending
                download.error_message = None
                download.downloaded_size = 0  # 다운로드 크기 초기화

            # 배치 단위로 커밋
            db.commit()
            print(f"[LOG] {len(batch)}개 다운로드 상태 업데이트 완료")

            # 배치 내 다운로드들 시작
            for download in batch:
                success = await download_core.start_download_async(download, db)
                if success:
                    restarted_count += 1
                    print(f"[LOG] 다운로드 재시작 성공: {download.id}")
                else:
                    print(f"[WARNING] 다운로드 재시작 실패: {download.id}")

            # 배치 간 잠깐 대기 (DB 부하 분산)
            if i + batch_size < len(failed_downloads):
                await asyncio.sleep(0.1)

        if restarted_count > 0:
            print(f"[LOG] {restarted_count}개 다운로드 재시작 완료")

        return {
            "success": True,
            "message": f"{restarted_count}개 다운로드가 재시작되었습니다.",
            "restarted_count": restarted_count
        }

    except Exception as e:
        print(f"[ERROR] 일괄 재시작 실패: {e}")
        raise HTTPException(status_code=500, detail=f"일괄 재시작 실패: {str(e)}")


@router.post("/downloads/stop-all-local")
async def stop_all_local_downloads(db: Session = Depends(get_db)):
    """모든 로컬 다운로드 정지"""
    try:
        # 진행 중인 로컬 다운로드 찾기 (use_proxy=False)
        active_local_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([StatusEnum.pending, StatusEnum.downloading, StatusEnum.parsing]),
            DownloadRequest.use_proxy == False
        ).all()

        print(f"[DEBUG] stop-all-local: 진행 중인 로컬 다운로드 {len(active_local_downloads)}개 발견")
        for download in active_local_downloads:
            print(f"[DEBUG] stop-all-local: 다운로드 ID {download.id}, 상태: {download.status}, 프록시 사용: {download.use_proxy}")

        stopped_count = 0
        for download in active_local_downloads:
            old_status = download.status
            download.status = StatusEnum.stopped
            download.error_message = "사용자에 의해 로컬 다운로드 일괄 정지됨"
            stopped_count += 1

            print(f"[DEBUG] stop-all-local: 다운로드 ID {download.id} 상태 변경: {old_status} → {StatusEnum.stopped}")

            # 실행 중인 태스크 강제 취소 (DB 업데이트는 이미 위에서 했으므로 태스크만 취소)
            if download.id in download_core.download_tasks:
                task = download_core.download_tasks[download.id]
                task.cancel()
                del download_core.download_tasks[download.id]
                print(f"[DEBUG] 태스크 강제 취소: {download.id}")

            # SSE로 정지 상태 전송
            await sse_manager.broadcast_message("status_update", {
                "id": download.id,
                "status": "stopped",
                "message": "로컬 다운로드 일괄 정지됨"
            })

        if stopped_count > 0:
            db.commit()
            print(f"[LOG] {stopped_count}개 로컬 다운로드 일괄 정지 완료")

        # 전체 상태 업데이트 완료 알림 (프론트엔드 새로고침 트리거)
        await sse_manager.broadcast_message("force_refresh", {
            "message": f"{stopped_count}개 로컬 다운로드가 정지되었습니다.",
            "timestamp": asyncio.get_event_loop().time()
        })

        return {
            "success": True,
            "message": f"{stopped_count}개 로컬 다운로드가 정지되었습니다.",
            "stopped_count": stopped_count
        }

    except Exception as e:
        print(f"[ERROR] 로컬 다운로드 일괄 정지 실패: {e}")
        raise HTTPException(status_code=500, detail=f"로컬 다운로드 일괄 정지 실패: {str(e)}")


@router.post("/downloads/restart-failed-local")
async def restart_failed_local_downloads(db: Session = Depends(get_db)):
    """실패/정지된 로컬 다운로드 재시작"""
    try:
        # 실패 또는 정지 상태인 로컬 다운로드 찾기 (use_proxy=False)
        failed_local_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([StatusEnum.failed, StatusEnum.stopped]),
            DownloadRequest.use_proxy == False
        ).all()

        # 모든 다운로드를 pending 상태로 변경 (한 번에 처리)
        for download in failed_local_downloads:
            download.status = StatusEnum.pending
            download.error_message = None
            download.downloaded_size = 0  # 다운로드 크기 초기화

        # 한 번에 커밋
        db.commit()
        print(f"[LOG] {len(failed_local_downloads)}개 로컬 다운로드 상태 업데이트 완료")

        # 전체 중에서 가장 오래된 다운로드 하나만 시작
        restarted_count = 0
        if failed_local_downloads:
            oldest_download = min(failed_local_downloads, key=lambda d: d.requested_at)
            success = await download_core.start_download_async(oldest_download, db)
            if success:
                restarted_count = 1
                print(f"[LOG] 가장 오래된 로컬 다운로드 시작: {oldest_download.id}")
            else:
                print(f"[WARNING] 가장 오래된 로컬 다운로드 시작 실패: {oldest_download.id}")

            # 나머지 다운로드들은 pending 상태로 유지 (세마포어로 자동 관리됨)
            pending_count = len(failed_local_downloads) - 1
            if pending_count > 0:
                print(f"[LOG] {pending_count}개 로컬 다운로드가 대기 상태로 설정됨")

        if restarted_count > 0:
            print(f"[LOG] {restarted_count}개 로컬 다운로드 재시작 완료")

        # 전체 상태 업데이트 완료 알림 (프론트엔드 새로고침 트리거)
        await sse_manager.broadcast_message("force_refresh", {
            "message": f"{len(failed_local_downloads)}개 로컬 다운로드가 대기상태로 변경되었습니다.",
            "timestamp": asyncio.get_event_loop().time()
        })

        # 나머지 대기중인 다운로드들을 자동으로 시작
        if len(failed_local_downloads) > 1:  # 2개 이상인 경우만
            print(f"[LOG] 나머지 {len(failed_local_downloads) - 1}개 대기중인 다운로드 자동 시작 트리거")
            await download_core.auto_start_pending_downloads()

        return {
            "success": True,
            "message": f"{restarted_count}개 로컬 다운로드가 재시작되었습니다.",
            "restarted_count": restarted_count
        }

    except Exception as e:
        print(f"[ERROR] 로컬 다운로드 일괄 재시작 실패: {e}")
        raise HTTPException(status_code=500, detail=f"로컬 다운로드 일괄 재시작 실패: {str(e)}")


@router.post("/downloads/stop-all-proxy")
async def stop_all_proxy_downloads(db: Session = Depends(get_db)):
    """모든 프록시 다운로드 정지"""
    try:
        # 진행 중인 프록시 다운로드 찾기 (use_proxy=True)
        active_proxy_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([StatusEnum.pending, StatusEnum.downloading, StatusEnum.parsing]),
            DownloadRequest.use_proxy == True
        ).all()

        stopped_count = 0
        for download in active_proxy_downloads:
            download.status = StatusEnum.stopped
            download.error_message = "사용자에 의해 프록시 다운로드 일괄 정지됨"
            stopped_count += 1

            # SSE로 정지 상태 전송
            await sse_manager.broadcast_message("status_update", {
                "id": download.id,
                "status": "stopped",
                "message": "프록시 다운로드 일괄 정지됨"
            })

        if stopped_count > 0:
            db.commit()
            print(f"[LOG] {stopped_count}개 프록시 다운로드 일괄 정지 완료")

        # 전체 상태 업데이트 완료 알림 (프론트엔드 새로고침 트리거)
        await sse_manager.broadcast_message("force_refresh", {
            "message": f"{stopped_count}개 프록시 다운로드가 정지되었습니다.",
            "timestamp": asyncio.get_event_loop().time()
        })

        return {
            "success": True,
            "message": f"{stopped_count}개 프록시 다운로드가 정지되었습니다.",
            "stopped_count": stopped_count
        }

    except Exception as e:
        print(f"[ERROR] 프록시 다운로드 일괄 정지 실패: {e}")
        raise HTTPException(status_code=500, detail=f"프록시 다운로드 일괄 정지 실패: {str(e)}")


@router.post("/downloads/restart-failed-proxy")
async def restart_failed_proxy_downloads(db: Session = Depends(get_db)):
    """실패/정지된 프록시 다운로드 재시작"""
    try:
        # 실패 또는 정지 상태인 프록시 다운로드 찾기 (use_proxy=True)
        failed_proxy_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([StatusEnum.failed, StatusEnum.stopped]),
            DownloadRequest.use_proxy == True
        ).all()

        restarted_count = 0
        # 배치 처리로 DB 연결 절약 (10개씩 처리)
        batch_size = 10
        for i in range(0, len(failed_proxy_downloads), batch_size):
            batch = failed_proxy_downloads[i:i + batch_size]
            for download in batch:
                # 상태를 pending으로 변경
                download.status = StatusEnum.pending
                download.error_message = None
                download.downloaded_size = 0  # 다운로드 크기 초기화

            # 배치 단위로 커밋
            db.commit()
            print(f"[LOG] {len(batch)}개 프록시 다운로드 상태 업데이트 완료")

            # 배치 내 다운로드들 시작
            for download in batch:
                success = await download_core.start_download_async(download, db)
                if success:
                    restarted_count += 1
                    print(f"[LOG] 프록시 다운로드 재시작 성공: {download.id}")
                else:
                    print(f"[WARNING] 프록시 다운로드 재시작 실패: {download.id}")

            # 배치 간 잠깐 대기 (DB 부하 분산)
            if i + batch_size < len(failed_proxy_downloads):
                await asyncio.sleep(0.1)

        if restarted_count > 0:
            print(f"[LOG] {restarted_count}개 프록시 다운로드 재시작 완료")

        return {
            "success": True,
            "message": f"{restarted_count}개 프록시 다운로드가 재시작되었습니다.",
            "restarted_count": restarted_count
        }

    except Exception as e:
        print(f"[ERROR] 프록시 다운로드 일괄 재시작 실패: {e}")
        raise HTTPException(status_code=500, detail=f"프록시 다운로드 일괄 재시작 실패: {str(e)}")