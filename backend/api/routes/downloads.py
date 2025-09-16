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

from core.db import get_db
from core.models import DownloadRequest, StatusEnum
from core.download_core import download_core
from services.sse_manager import sse_manager

router = APIRouter(prefix="/api", tags=["downloads"])


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
                "download_id": download_id
            }
        else:
            raise HTTPException(status_code=500, detail="다운로드 시작에 실패했습니다")

    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] 다운로드 시작 API 오류: {e}")
        raise HTTPException(status_code=500, detail=f"서버 오류: {str(e)}")


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
            # SSE로 즉시 상태 알림
            await sse_manager.broadcast_message("download_stopped", {
                "id": download_id,
                "status": "stopped",
                "message": "다운로드가 중지되었습니다"
            })

            return {
                "success": True,
                "message": "다운로드가 중지되었습니다",
                "download_id": download_id
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
    """배치 다운로드 시작 (비동기)"""
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
    """배치 다운로드 중지 (비동기)"""
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