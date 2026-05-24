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
        """Add a message to the queue"""
        if not self.connected:
            return
            
        message = {
            "type": message_type,
            "data": data,
            "timestamp": time.time()
        }
        
        try:
            await self.queue.put(message)
        except Exception:
            self.connected = False
            
    def disconnect(self):
        """Disconnect"""
        self.connected = False

    async def get_stream(self) -> AsyncGenerator[str, None]:
        """Generate the SSE stream - safe handling"""
        try:
            # Connection confirmation message
            yield f"data: {json.dumps({'type': 'connection', 'status': 'connected'})}\n\n"

            while self.connected:
                try:
                    # Shorter timeout for a faster response
                    message = await asyncio.wait_for(self.queue.get(), timeout=0.5)

                    # Send the message
                    yield f"data: {json.dumps(message)}\n\n"

                except asyncio.TimeoutError:
                    # Send a heartbeat every 60 seconds
                    if time.time() - self.last_heartbeat > 60:
                        try:
                            heartbeat = {
                                "type": "heartbeat",
                                "timestamp": time.time()
                            }
                            yield f"data: {json.dumps(heartbeat)}\n\n"
                            self.last_heartbeat = time.time()
                        except Exception:
                            break

                except asyncio.CancelledError:
                    print("[LOG] SSE stream cancelled gracefully")
                    break
                except Exception as e:
                    print(f"[ERROR] SSE stream error: {e}")
                    break

        except asyncio.CancelledError:
            print("[LOG] SSE connection cancelled")
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
        """Start the SSE manager"""
        if not self._cleanup_task:
            self._cleanup_task = asyncio.create_task(self._cleanup_connections())

    async def stop(self):
        """Stop the SSE manager"""
        print(f"[LOG] Stopping SSEManager... ({len(self.connections)} active connections)")

        # Cancel the cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._cleanup_task = None
            print("[LOG] SSE cleanup task stopped")
            
        # Disconnect all connections
        async with self._lock:
            connection_count = len(self.connections)
            for conn in self.connections[:]:
                conn.disconnect()
            self.connections.clear()
            
        print(f"[LOG] SSEManager stopped ({connection_count} connections closed)")
    
    async def add_connection(self, request: Request) -> SSEConnection:
        """Add a new SSE connection"""
        connection = SSEConnection(request)
        
        async with self._lock:
            self.connections.append(connection)
            
        print(f"[LOG] New SSE connection. Total: {len(self.connections)}")
        return connection
        
    async def broadcast_message(self, message_type: str, data: dict, exclude_conn: Optional[SSEConnection] = None):
        """Broadcast a message to all connections"""
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
                except Exception:
                    conn.disconnect()
                    
            # Update the connection list
            self.connections = active_connections

    async def _cleanup_connections(self):
        """Clean up inactive connections (runs periodically)"""
        while True:
            try:
                await asyncio.sleep(60)  # clean up every minute

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


# Global SSE manager instance
sse_manager = SSEManager()