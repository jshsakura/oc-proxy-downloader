# -*- coding: utf-8 -*-
"""
Async download API router
- Start/stop async downloads
- Real-time status updates via SSE
- Tightly integrated frontend communication
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
import asyncio
import httpx
import re
from urllib.parse import urlparse, unquote, urlunparse

from core.db import get_db
from core.models import DownloadRequest, StatusEnum
from core.download_core import download_core
from core.parser import fichier_parser
from core.simple_parser import parse_1fichier_simple_sync, clean_1fichier_url, derive_display_name
from core.hoster_parsers import should_preserve_original_url
from core.config import get_config
from core.error_messages import (
    classify_failure_text,
    is_terminal_failure,
    is_auth_required_failure,
    is_retry_blocked_now,
    KIND_DEAD,
    KIND_AUTH_REQUIRED,
)
from services.sse_manager import sse_manager
from services.ouo_unwrap_service import is_ouo_url, unwrap_if_ouo


def _has_fichier_credentials() -> bool:
    """Check whether a 1fichier account is registered in the config.

    Used as the criterion for skipping auth_required failures in batch
    restarts, since retrying them is pointless without credentials.
    """
    cfg = get_config()
    email = (cfg.get("fichier_email") or "").strip()
    password = cfg.get("fichier_password") or ""
    return bool(email and password)


def _should_skip_retry(req: DownloadRequest, has_credentials: bool) -> Optional[str]:
    """Reason to skip a batch/single retry — None if there is none.

    Prefers the ``failure_kind`` / ``next_retry_at`` columns, falling back to
    the ``error`` text for pre-migration records (columns NULL).

    Returns:
      - ``dead``: always blocked. The UI also disables the retry button.
      - ``auth_required``: only when no account is configured.
      - ``cooldown``: next retry time not yet reached. Clears naturally once
        the time passes.
    """
    return is_retry_blocked_now(req, has_credentials)

router = APIRouter(prefix="/api", tags=["downloads"])



@router.post("/download/")
async def add_download(
    request: dict,
    db: Session = Depends(get_db)
):
    """Add a new download request"""
    try:
        url = request.get("url", "").strip()
        password = request.get("password", "")
        use_proxy = request.get("use_proxy", False)

        if not url:
            raise HTTPException(status_code=400, detail="URL이 필요합니다")

        # Automatically unwrap ouo.io / ouo.press shortlinks. The unwrapped
        # result is the real download URL. On failure, keep the original and
        # let the user retry.
        original_ouo_url: Optional[str] = None
        if is_ouo_url(url):
            original_ouo_url = url
            unwrapped = unwrap_if_ouo(url)
            if unwrapped:
                print(f"[LOG] ouo unwrap: {url} -> {unwrapped}")
                url = unwrapped
            else:
                raise HTTPException(
                    status_code=502,
                    detail=f"ouo 단축링크 우회 실패: {url} — 잠시 후 다시 시도해주세요",
                )

        # Clean up the 1fichier URL (strip affiliate params etc. from file
        # pages, but preserve the download host).
        url = clean_1fichier_url(url)

        # Create the new download request. For URLs that came in via ouo
        # unwrap, preserve the original ouo link in original_url so it can be
        # used later for diagnostics / re-unwrapping.
        # Stamp a provisional name derived from the URL so an identifier is
        # visible even before parsing — preparse overwrites it with the real
        # filename on success, so the placeholder only persists in dead cases,
        # and even then it's far more identifiable than "Unknown".
        preserved_original_url = url if (
            "1fichier.com" in url or should_preserve_original_url(url)
        ) else None

        new_request = DownloadRequest(
            url=url,
            original_url=original_ouo_url or preserved_original_url,
            password=password if password else None,
            use_proxy=use_proxy,
            status=StatusEnum.pending,
            file_name=derive_display_name(original_ouo_url or url),
        )

        db.add(new_request)
        db.commit()
        db.refresh(new_request)

        # Start the download immediately
        print(f"[LOG] 다운로드 즉시 시작: {new_request.id}")
        success = await download_core.start_download_async(new_request, db)

        if success:
            # Notify download start via SSE
            await sse_manager.broadcast_message("download_started", {
                "id": new_request.id,
                "url": url,
                "status": "parsing",
                "message": "다운로드가 시작되었습니다"
            })
        else:
            # Notify the user on failure as well
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
    """Start an async download"""
    try:
        # Look up the download request
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다")

        # Check whether it is already running
        if req.status in [StatusEnum.parsing, StatusEnum.downloading, StatusEnum.waiting]:
            raise HTTPException(status_code=400, detail="이미 실행 중인 다운로드입니다")

        # Start the async download
        success = await download_core.start_download_async(req, db)

        if success:
            # Immediately notify status via SSE
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
    """Restart / resume an async download"""
    try:
        # Look up the download request
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다")

        # Check whether it is already running
        if req.status in [StatusEnum.parsing, StatusEnum.downloading, StatusEnum.waiting]:
            raise HTTPException(status_code=400, detail="이미 실행 중인 다운로드입니다")

        # Completed downloads cannot be restarted
        if req.status == StatusEnum.done:
            raise HTTPException(status_code=400, detail="이미 완료된 다운로드입니다")

        # Update the proxy setting (if included in the request)
        if use_proxy is not None:
            req.use_proxy = use_proxy

        # Start the async download (resume uses the same logic as start)
        success = await download_core.start_download_async(req, db)

        if success:
            # Immediately notify status via SSE
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
    """Retry a failed download"""
    try:
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="Download request not found")

        if req.status not in [StatusEnum.failed, StatusEnum.stopped]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot retry in current status: {req.status}"
            )

        # Permanent failure — retrying yields the same result. Even if a
        # client calls this carelessly it only loads 1fichier and hands the
        # user the same failure again, so block it.
        skip_reason = _should_skip_retry(req, _has_fichier_credentials())
        if skip_reason == "dead":
            raise HTTPException(
                status_code=409,
                detail="retry_blocked_dead",
            )
        if skip_reason == "auth_required":
            raise HTTPException(
                status_code=409,
                detail="retry_blocked_auth_required",
            )
        if skip_reason == "cooldown":
            # A cooldown is picked up automatically by batch restarts once it
            # clears, but a manual single retry means the user intends to force
            # it, so clear the column and let it through.
            req.next_retry_at = None

        # Logging for expired links (no URL restore needed — parsing uses
        # original_url automatically).
        if req.error and "410" in str(req.error):
            print(f"[LOG] 만료된 다운로드 링크 감지, 재파싱으로 새 링크 획득 예정")

        if req.url and "1fichier.com/c" in req.url:
            print(f"[LOG] 1fichier 직접 다운로드 링크, 재파싱으로 새 링크 획득 예정")

        # Change status to pending and clear the error message. Also blank the
        # classification/cooldown columns and reset attempt_count/attempts_json
        # — the user's intent is a "forced retry", so carrying over accumulated
        # backoff is wrong (this prevents a regression where the next failure
        # immediately gets a 30-minute cooldown).
        req.status = StatusEnum.pending
        req.error = None
        req.failure_kind = None
        req.next_retry_at = None
        req.attempt_count = 0
        req.attempts_json = None
        req.downloaded_size = 0  # start over from the beginning
        req.finished_at = None
        db.commit()

        # Start the async download
        success = await download_core.start_download_async(req, db)

        if success:
            # Immediately notify status via SSE
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
    """Stop an async download"""
    try:
        # Look up the download request
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다")

        # Stop the async download
        success = await download_core.stop_download_async(download_id, db)

        if success:
            # Look up the latest download status
            updated_req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()

            # Immediately notify status via SSE
            await sse_manager.broadcast_message("download_stopped", {
                "id": download_id,
                "status": "stopped",
                "progress": 0,
                "message": "다운로드가 중지되었습니다"
            })

            # Also send a download_updated message so the UI refreshes immediately
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
    """Get async download status"""
    try:
        status = await download_core.get_download_status(download_id)
        return status
    except Exception as e:
        print(f"[ERROR] 다운로드 상태 조회 오류: {e}")
        raise HTTPException(status_code=500, detail=f"상태 조회 실패: {str(e)}")


@router.post("/downloads/batch-start")
async def start_batch_downloads(download_ids: List[int], db: Session = Depends(get_db)):
    """Start batch downloads"""
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

            # Start the async download
            success = await download_core.start_download_async(req, db)
            results.append({
                "id": download_id,
                "success": success,
                "message": "시작됨" if success else "시작 실패"
            })

            if success:
                # SSE notification
                await sse_manager.broadcast_message("download_started", {
                    "id": download_id,
                    "status": "parsing",
                    "message": "배치 다운로드 시작"
                })

        # Notify batch start completion
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
    """Stop batch downloads"""
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
                # SSE notification
                await sse_manager.broadcast_message("download_stopped", {
                    "id": download_id,
                    "status": "stopped",
                    "message": "배치 다운로드 중지"
                })

        # Notify batch stop completion
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
    """Delete a download"""
    try:
        # Look up the download request
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다")

        # Stop running downloads first
        if req.status in [StatusEnum.parsing, StatusEnum.downloading, StatusEnum.waiting]:
            await download_core.stop_download_async(download_id, db)

        # Delete from the database
        db.delete(req)
        db.commit()

        # Notify deletion via SSE
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


@router.post("/downloads/bulk-delete")
async def bulk_delete_downloads(
    request: dict,
    db: Session = Depends(get_db),
):
    """Delete the selected downloads in one call. Used when an admin cleans up
    based on audit results.

    body: ``{"ids": [int, ...]}``. Running downloads are stopped before deletion.
    """
    ids = request.get("ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids 가 비어있습니다")
    # Convert to int + deduplicate
    try:
        ids = sorted({int(i) for i in ids})
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="ids 는 정수 리스트여야 합니다")

    rows = db.query(DownloadRequest).filter(DownloadRequest.id.in_(ids)).all()
    if not rows:
        return {"success": True, "deleted_count": 0, "ids": []}

    deleted_ids: List[int] = []
    active_statuses = {
        StatusEnum.parsing, StatusEnum.downloading, StatusEnum.waiting,
        StatusEnum.proxying,
    }
    for r in rows:
        if r.status in active_statuses:
            try:
                await download_core.stop_download_async(r.id, db)
            except Exception as e:
                print(f"[WARNING] bulk-delete: 중지 중 오류 (id={r.id}): {e}")
        db.delete(r)
        deleted_ids.append(r.id)
    db.commit()

    # Batch SSE notification — a single force_refresh to avoid the expensive
    # case of per-row updates.
    await sse_manager.broadcast_message("downloads_bulk_deleted", {
        "ids": deleted_ids,
        "count": len(deleted_ids),
    })
    await sse_manager.broadcast_message("force_refresh", {
        "message": f"{len(deleted_ids)}개 다운로드가 삭제되었습니다",
    })

    return {
        "success": True,
        "deleted_count": len(deleted_ids),
        "ids": deleted_ids,
    }


@router.post("/downloads/force-refresh")
async def force_refresh_downloads():
    """Request a forced frontend refresh"""
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
    """Toggle the download's proxy mode"""
    try:
        # Look up the download request
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if not req:
            raise HTTPException(status_code=404, detail="다운로드 요청을 찾을 수 없습니다")

        # Running downloads cannot be toggled
        if req.status in [StatusEnum.parsing, StatusEnum.downloading, StatusEnum.waiting]:
            raise HTTPException(status_code=400, detail="실행 중인 다운로드는 프록시 모드를 변경할 수 없습니다")

        # Toggle proxy mode
        req.use_proxy = not req.use_proxy
        db.commit()

        # Notify the status change via SSE
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
    """Download system health check"""
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
    """Preparse file info (extract filename and size)"""
    try:
        print(f"[LOG] 사전 파싱 시작: {req.url}")

        # Determine the URL type
        is_1fichier = "1fichier.com" in req.url

        if is_1fichier:
            # 1fichier parsing — a simple HTTP request to extract file info only
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }

            # Proxy configuration
            client_kwargs = {"headers": headers, "timeout": 10.0}
            if req.use_proxy:
                # TODO: add proxy configuration here if needed
                # client_kwargs["proxies"] = {"http": "proxy_url", "https": "proxy_url"}
                pass

            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.get(req.url)

                if response.status_code == 200:
                    # Extract file info
                    file_info = fichier_parser.extract_file_info(response.text)

                    if file_info and file_info.get('name'):
                        req.file_name = file_info['name']
                        print(f"[LOG] 파일명 추출: {req.file_name}")

                    if file_info and file_info.get('size'):
                        # Convert the size info to bytes
                        size_str = file_info['size']
                        try:
                            # "1.5 GB" -> convert to bytes
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

                    # Update the DB
                    db.commit()

                    # Notify file info update via SSE
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
            # General download — try to extract the filename from the URL
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

                # Notify file info update via SSE
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
    """Stop all downloads"""
    try:
        # Find all in-progress downloads (pending, downloading, parsing)
        active_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([StatusEnum.pending, StatusEnum.downloading, StatusEnum.parsing])
        ).all()

        stopped_count = 0
        for download in active_downloads:
            download.status = StatusEnum.stopped
            download.error = "사용자에 의해 일괄 정지됨"
            stopped_count += 1

            # Send stopped status via SSE
            await sse_manager.broadcast_message("status_update", {
                "id": download.id,
                "status": "stopped",
                "message": "일괄 정지됨"
            })

        if stopped_count > 0:
            db.commit()
            print(f"[LOG] {stopped_count}개 다운로드 일괄 정지 완료")

        # Notify that the bulk status update is complete (triggers a frontend refresh)
        # i18n support
        from core.config import get_config
        from core.i18n import get_translations
        config = get_config()
        user_language = config.get("language", "ko")
        translations = get_translations(user_language)

        message = translations.get("batch_downloads_stopped", "{count}개 다운로드가 정지되었습니다.").format(count=stopped_count)

        await sse_manager.broadcast_message("force_refresh", {
            "message": message,
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
    """Restart failed/stopped downloads"""
    try:
        # Find downloads in failed or stopped status
        all_failed = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([StatusEnum.failed, StatusEnum.stopped])
        ).all()

        # Exclude permanent-failure / login-required / cooldown items from
        # the batch restart. Cooldowns get picked up naturally on a later call
        # once they clear — they are not a permanent block.
        has_creds = _has_fichier_credentials()
        skipped_dead = 0
        skipped_auth = 0
        skipped_cooldown = 0
        failed_downloads = []
        for d in all_failed:
            reason = _should_skip_retry(d, has_creds)
            if reason == "dead":
                skipped_dead += 1
            elif reason == "auth_required":
                skipped_auth += 1
            elif reason == "cooldown":
                skipped_cooldown += 1
            else:
                failed_downloads.append(d)
        if skipped_dead or skipped_auth or skipped_cooldown:
            print(
                f"[LOG] 일괄 재시작 필터링: dead={skipped_dead}, "
                f"auth_required={skipped_auth}, cooldown={skipped_cooldown} 건 건너뜀"
            )

        restarted_count = 0
        # Process in batches to conserve DB connections (10 at a time)
        batch_size = 10
        for i in range(0, len(failed_downloads), batch_size):
            batch = failed_downloads[i:i + batch_size]
            for download in batch:
                # Change status to pending. Also reset classification/cooldown/attempt count.
                download.status = StatusEnum.pending
                download.error = None
                download.failure_kind = None
                download.next_retry_at = None
                download.attempt_count = 0
                download.attempts_json = None
                download.downloaded_size = 0  # reset downloaded size

            # Commit per batch
            db.commit()
            print(f"[LOG] {len(batch)}개 다운로드 상태 업데이트 완료")

            # Start the downloads in this batch
            for download in batch:
                success = await download_core.start_download_async(download, db)
                if success:
                    restarted_count += 1
                    print(f"[LOG] 다운로드 재시작 성공: {download.id}")
                else:
                    print(f"[WARNING] 다운로드 재시작 실패: {download.id}")

            # Brief pause between batches (spread out DB load)
            if i + batch_size < len(failed_downloads):
                await asyncio.sleep(0.1)

        if restarted_count > 0:
            print(f"[LOG] {restarted_count}개 다운로드 재시작 완료")

        return {
            "success": True,
            "message": f"{restarted_count}개 다운로드가 재시작되었습니다.",
            "restarted_count": restarted_count,
            "skipped_dead": skipped_dead,
            "skipped_auth_required": skipped_auth,
            "skipped_cooldown": skipped_cooldown,
        }

    except Exception as e:
        print(f"[ERROR] 일괄 재시작 실패: {e}")
        raise HTTPException(status_code=500, detail=f"일괄 재시작 실패: {str(e)}")


@router.post("/downloads/stop-all-local")
async def stop_all_local_downloads(db: Session = Depends(get_db)):
    """Stop all local downloads"""
    try:
        # Find in-progress local downloads (use_proxy=False)
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
            download.error = "사용자에 의해 로컬 다운로드 일괄 정지됨"
            stopped_count += 1

            print(f"[DEBUG] stop-all-local: 다운로드 ID {download.id} 상태 변경: {old_status} → {StatusEnum.stopped}")

            # Force-cancel the running task (the DB was already updated above, so cancel only the task)
            if download.id in download_core.download_tasks:
                task = download_core.download_tasks[download.id]
                task.cancel()
                del download_core.download_tasks[download.id]
                print(f"[DEBUG] 태스크 강제 취소: {download.id}")

            # Send stopped status via SSE
            await sse_manager.broadcast_message("status_update", {
                "id": download.id,
                "status": "stopped",
                "message": "로컬 다운로드 일괄 정지됨"
            })

        if stopped_count > 0:
            db.commit()
            print(f"[LOG] {stopped_count}개 로컬 다운로드 일괄 정지 완료")

        # Notify that the bulk status update is complete (triggers a frontend refresh)
        # i18n support
        from core.config import get_config
        from core.i18n import get_translations
        config = get_config()
        user_language = config.get("language", "ko")
        translations = get_translations(user_language)

        message = translations.get("batch_local_downloads_stopped", "{count}개 로컬 다운로드가 정지되었습니다.").format(count=stopped_count)

        await sse_manager.broadcast_message("force_refresh", {
            "message": message,
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
    """Restart failed/stopped local downloads"""
    try:
        # Find local downloads in failed or stopped status (use_proxy=False)
        all_failed = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([StatusEnum.failed, StatusEnum.stopped]),
            DownloadRequest.use_proxy == False
        ).all()

        # Exclude permanent-failure / login-required / cooldown items
        has_creds = _has_fichier_credentials()
        skipped_dead = 0
        skipped_auth = 0
        skipped_cooldown = 0
        failed_local_downloads = []
        for d in all_failed:
            reason = _should_skip_retry(d, has_creds)
            if reason == "dead":
                skipped_dead += 1
            elif reason == "auth_required":
                skipped_auth += 1
            elif reason == "cooldown":
                skipped_cooldown += 1
            else:
                failed_local_downloads.append(d)
        if skipped_dead or skipped_auth or skipped_cooldown:
            print(
                f"[LOG] 로컬 일괄 재시작 필터링: dead={skipped_dead}, "
                f"auth_required={skipped_auth}, cooldown={skipped_cooldown} 건 건너뜀"
            )

        # Change all downloads to pending status (in one pass)
        for download in failed_local_downloads:
            download.status = StatusEnum.pending
            # The column name is ``error`` — the transient attribute formerly
            # written as ``error_message`` never persisted to the DB (a bug),
            # so clearing it to None was meaningless too. Corrected to the
            # proper column.
            download.error = None
            download.failure_kind = None
            download.next_retry_at = None
            download.attempt_count = 0
            download.attempts_json = None
            download.downloaded_size = 0  # reset downloaded size

        # Commit all at once
        db.commit()
        print(f"[LOG] {len(failed_local_downloads)}개 로컬 다운로드 상태 업데이트 완료")

        # Start only the single oldest download among them
        restarted_count = 0
        if failed_local_downloads:
            oldest_download = min(failed_local_downloads, key=lambda d: d.requested_at)
            success = await download_core.start_download_async(oldest_download, db)
            if success:
                restarted_count = 1
                print(f"[LOG] 가장 오래된 로컬 다운로드 시작: {oldest_download.id}")
            else:
                print(f"[WARNING] 가장 오래된 로컬 다운로드 시작 실패: {oldest_download.id}")

            # Keep the rest in pending status (managed automatically by the semaphore)
            pending_count = len(failed_local_downloads) - 1
            if pending_count > 0:
                print(f"[LOG] {pending_count}개 로컬 다운로드가 대기 상태로 설정됨")

        if restarted_count > 0:
            print(f"[LOG] {restarted_count}개 로컬 다운로드 재시작 완료")

        # Notify that the bulk status update is complete (triggers a frontend refresh)
        # i18n support
        from core.config import get_config
        from core.i18n import get_translations
        config = get_config()
        user_language = config.get("language", "ko")
        translations = get_translations(user_language)

        message = translations.get("batch_local_downloads_set_to_pending", "{count}개 로컬 다운로드가 대기상태로 변경되었습니다.").format(count=len(failed_local_downloads))

        await sse_manager.broadcast_message("force_refresh", {
            "message": message,
            "timestamp": asyncio.get_event_loop().time()
        })

        # Automatically start the remaining pending downloads
        if len(failed_local_downloads) > 1:  # only when there are 2 or more
            print(f"[LOG] 나머지 {len(failed_local_downloads) - 1}개 대기중인 다운로드 자동 시작 트리거")
            await download_core.auto_start_pending_downloads()

        return {
            "success": True,
            "message": f"{restarted_count}개 로컬 다운로드가 재시작되었습니다.",
            "restarted_count": restarted_count,
            "skipped_dead": skipped_dead,
            "skipped_auth_required": skipped_auth,
            "skipped_cooldown": skipped_cooldown,
        }

    except Exception as e:
        print(f"[ERROR] 로컬 다운로드 일괄 재시작 실패: {e}")
        raise HTTPException(status_code=500, detail=f"로컬 다운로드 일괄 재시작 실패: {str(e)}")


@router.post("/downloads/stop-all-proxy")
async def stop_all_proxy_downloads(db: Session = Depends(get_db)):
    """Stop all proxy downloads"""
    try:
        # Find in-progress proxy downloads (use_proxy=True)
        active_proxy_downloads = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([StatusEnum.pending, StatusEnum.downloading, StatusEnum.parsing]),
            DownloadRequest.use_proxy == True
        ).all()

        stopped_count = 0
        for download in active_proxy_downloads:
            download.status = StatusEnum.stopped
            download.error = "사용자에 의해 프록시 다운로드 일괄 정지됨"
            stopped_count += 1

            # Send stopped status via SSE
            await sse_manager.broadcast_message("status_update", {
                "id": download.id,
                "status": "stopped",
                "message": "프록시 다운로드 일괄 정지됨"
            })

        if stopped_count > 0:
            db.commit()
            print(f"[LOG] {stopped_count}개 프록시 다운로드 일괄 정지 완료")

        # Notify that the bulk status update is complete (triggers a frontend refresh)
        # i18n support
        from core.config import get_config
        from core.i18n import get_translations
        config = get_config()
        user_language = config.get("language", "ko")
        translations = get_translations(user_language)

        message = translations.get("batch_proxy_downloads_stopped", "{count}개 프록시 다운로드가 정지되었습니다.").format(count=stopped_count)

        await sse_manager.broadcast_message("force_refresh", {
            "message": message,
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
    """Restart failed/stopped proxy downloads"""
    try:
        # Find proxy downloads in failed or stopped status (use_proxy=True)
        all_failed = db.query(DownloadRequest).filter(
            DownloadRequest.status.in_([StatusEnum.failed, StatusEnum.stopped]),
            DownloadRequest.use_proxy == True
        ).all()

        # Exclude permanent-failure / login-required items
        has_creds = _has_fichier_credentials()
        skipped_dead = 0
        skipped_auth = 0
        skipped_cooldown = 0
        failed_proxy_downloads = []
        for d in all_failed:
            reason = _should_skip_retry(d, has_creds)
            if reason == "dead":
                skipped_dead += 1
            elif reason == "auth_required":
                skipped_auth += 1
            elif reason == "cooldown":
                skipped_cooldown += 1
            else:
                failed_proxy_downloads.append(d)
        if skipped_dead or skipped_auth or skipped_cooldown:
            print(
                f"[LOG] 프록시 일괄 재시작 필터링: dead={skipped_dead}, "
                f"auth_required={skipped_auth}, cooldown={skipped_cooldown} 건 건너뜀"
            )

        restarted_count = 0
        # Process in batches to conserve DB connections (10 at a time)
        batch_size = 10
        for i in range(0, len(failed_proxy_downloads), batch_size):
            batch = failed_proxy_downloads[i:i + batch_size]
            for download in batch:
                # Change status to pending. Also reset classification/cooldown/attempt count.
                download.status = StatusEnum.pending
                download.error = None
                download.failure_kind = None
                download.next_retry_at = None
                download.attempt_count = 0
                download.attempts_json = None
                download.downloaded_size = 0  # reset downloaded size

            # Commit per batch
            db.commit()
            print(f"[LOG] {len(batch)}개 프록시 다운로드 상태 업데이트 완료")

            # Start the downloads in this batch
            for download in batch:
                success = await download_core.start_download_async(download, db)
                if success:
                    restarted_count += 1
                    print(f"[LOG] 프록시 다운로드 재시작 성공: {download.id}")
                else:
                    print(f"[WARNING] 프록시 다운로드 재시작 실패: {download.id}")

            # Brief pause between batches (spread out DB load)
            if i + batch_size < len(failed_proxy_downloads):
                await asyncio.sleep(0.1)

        if restarted_count > 0:
            print(f"[LOG] {restarted_count}개 프록시 다운로드 재시작 완료")

        return {
            "success": True,
            "message": f"{restarted_count}개 프록시 다운로드가 재시작되었습니다.",
            "restarted_count": restarted_count,
            "skipped_dead": skipped_dead,
            "skipped_auth_required": skipped_auth,
            "skipped_cooldown": skipped_cooldown,
        }

    except Exception as e:
        print(f"[ERROR] 프록시 다운로드 일괄 재시작 실패: {e}")
        raise HTTPException(status_code=500, detail=f"프록시 다운로드 일괄 재시작 실패: {str(e)}")
