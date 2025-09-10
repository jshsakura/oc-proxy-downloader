# -*- coding: utf-8 -*-
import asyncio
import json
import time
from typing import Dict, List, Optional, AsyncGenerator
from fastapi import Request
from fastapi.responses import StreamingResponse
import weakref
import queue


class SSEConnection:
    def __init__(self, request: Request):
        self.request = request
        self.queue = asyncio.Queue()
        self.connected = True
        self.last_heartbeat = time.time()
        
    async def send_message(self, message_type: str, data: dict):
        """메시지를 큐에 추가"""
        if not self.connected:
            return
            
        message = {
            "type": message_type,
            "data": data,
            "timestamp": time.time()
        }
        
        try:
            await self.queue.put(message)
        except:
            self.connected = False
            
    def disconnect(self):
        """연결 해제"""
        self.connected = False
        
    async def get_stream(self) -> AsyncGenerator[str, None]:
        """SSE 스트림 생성"""
        try:
            # 연결 확인 메시지
            yield f"data: {json.dumps({'type': 'connection', 'status': 'connected'})}\n\n"
            
            while self.connected:
                try:
                    # 100ms 타임아웃으로 메시지 확인
                    message = await asyncio.wait_for(self.queue.get(), timeout=0.1)
                    
                    # 메시지 전송
                    yield f"data: {json.dumps(message)}\n\n"
                    
                except asyncio.TimeoutError:
                    # 30초마다 heartbeat 전송
                    if time.time() - self.last_heartbeat > 30:
                        heartbeat = {
                            "type": "heartbeat",
                            "queue_size": self.queue.qsize() if hasattr(self.queue, 'qsize') else 0
                        }
                        yield f"data: {json.dumps(heartbeat)}\n\n"
                        self.last_heartbeat = time.time()
                        
                except Exception as e:
                    print(f"[ERROR] SSE stream error: {e}")
                    break
                    
        except Exception as e:
            print(f"[ERROR] SSE connection error: {e}")
        finally:
            self.connected = False


class SSEManager:
    def __init__(self):
        self.connections: List[SSEConnection] = []
        self._cleanup_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        
    async def start(self):
        """SSE 매니저 시작"""
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._cleanup_connections())
            
    async def stop(self):
        """SSE 매니저 정지"""
        print(f"[LOG] Stopping SSEManager... ({len(self.connections)} active connections)")
        
        # 정리 태스크 취소
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._cleanup_task = None
            print("[LOG] SSE cleanup task stopped")
            
        # 모든 연결 해제
        async with self._lock:
            connection_count = len(self.connections)
            for conn in self.connections[:]:
                conn.disconnect()
            self.connections.clear()
            
        print(f"[LOG] SSEManager stopped ({connection_count} connections closed)")
    
    async def add_connection(self, request: Request) -> SSEConnection:
        """새 SSE 연결 추가"""
        connection = SSEConnection(request)
        
        async with self._lock:
            self.connections.append(connection)
            
        print(f"[LOG] New SSE connection. Total: {len(self.connections)}")
        return connection
        
    async def broadcast_message(self, message_type: str, data: dict, exclude_conn: Optional[SSEConnection] = None):
        """모든 연결에 메시지 브로드캐스트"""
        if not self.connections:
            return
            
        async with self._lock:
            active_connections = []
            
            for conn in self.connections:
                if conn == exclude_conn or not conn.connected:
                    continue
                    
                try:
                    await conn.send_message(message_type, data)
                    active_connections.append(conn)
                except:
                    conn.disconnect()
                    
            # 연결 목록 업데이트
            self.connections = active_connections
            
    async def _cleanup_connections(self):
        """비활성 연결 정리 (주기적 실행)"""
        while True:
            try:
                await asyncio.sleep(60)  # 1분마다 정리
                
                async with self._lock:
                    active_connections = []
                    
                    for conn in self.connections:
                        if conn.connected:
                            active_connections.append(conn)
                        else:
                            print(f"[LOG] Cleaning up disconnected SSE connection")
                            
                    if len(active_connections) != len(self.connections):
                        self.connections = active_connections
                        print(f"[LOG] Active SSE connections: {len(self.connections)}")
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ERROR] SSE cleanup error: {e}")


# 전역 SSE 매니저 인스턴스
sse_manager = SSEManager()