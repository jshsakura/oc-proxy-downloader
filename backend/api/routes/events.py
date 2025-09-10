# -*- coding: utf-8 -*-
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import json

from services.sse_manager import sse_manager

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events")
async def stream_events(request: Request):
    """SSE 이벤트 스트림"""
    try:
        # 새 SSE 연결 생성
        connection = await sse_manager.add_connection(request)
        
        # 스트림 응답 반환
        return StreamingResponse(
            connection.get_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Cache-Control",
            }
        )
        
    except Exception as e:
        print(f"[ERROR] SSE stream failed: {e}")
        return StreamingResponse(
            iter([f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"]),
            media_type="text/event-stream"
        )


@router.post("/test-sse")
async def test_sse():
    """SSE 테스트"""
    try:
        # 테스트 메시지 브로드캐스트
        await sse_manager.broadcast_message("test_message", {
            "message": "SSE 연결 테스트 성공!",
            "timestamp": "현재시간"
        })
        
        return {"success": True, "message": "SSE 테스트 메시지를 전송했습니다."}
        
    except Exception as e:
        print(f"[ERROR] SSE test failed: {e}")
        return {"success": False, "error": str(e)}