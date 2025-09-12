# -*- coding: utf-8 -*-
"""
대기시간 추적 스토어
- 스레드 안전한 대기시간 관리
- 다운로드 대기 상태 추적
"""

import threading
import time


class WaitTimeStore:
    """스레드 안전한 대기시간 스토어"""
    
    def __init__(self):
        self._wait_tasks = {}  # {download_id: {"start_time": timestamp, "total_wait": seconds, "url": url}}
        self._lock = threading.Lock()
    
    def start_wait(self, download_id, total_wait_seconds, url):
        """대기 시작 등록"""
        with self._lock:
            self._wait_tasks[download_id] = {
                "start_time": time.time(),
                "total_wait": total_wait_seconds,
                "url": url
            }
            print(f"[STORE] 대기 추적 시작: ID {download_id}, 총 {total_wait_seconds}초")
    
    def finish_wait(self, download_id):
        """대기 완료 - 추적에서 제거"""
        with self._lock:
            if download_id in self._wait_tasks:
                del self._wait_tasks[download_id]
                print(f"[STORE] 대기 추적 완료: ID {download_id}")
                return True
            return False
    
    def get_remaining_time(self, download_id):
        """남은 대기시간 계산 (초)"""
        with self._lock:
            if download_id not in self._wait_tasks:
                return None
            
            wait_info = self._wait_tasks[download_id]
            elapsed_time = time.time() - wait_info["start_time"]
            remaining_time = max(0, wait_info["total_wait"] - elapsed_time)
            
            if remaining_time <= 0:
                # 대기 시간이 끝났으면 추적에서 제거
                del self._wait_tasks[download_id]
                return None
            
            return {
                "remaining_time": int(remaining_time),
                "total_wait_time": wait_info["total_wait"],
                "url": wait_info["url"]
            }
    
    def get_all_active_waits(self):
        """모든 진행 중인 대기 작업 반환"""
        with self._lock:
            result = {}
            expired_ids = []
            
            for download_id in list(self._wait_tasks.keys()):
                wait_info = self.get_remaining_time(download_id)
                if wait_info:
                    result[download_id] = wait_info
                else:
                    expired_ids.append(download_id)
            
            # 만료된 작업들 제거
            for expired_id in expired_ids:
                self._wait_tasks.pop(expired_id, None)
            
            return result


# 전역 대기시간 스토어 인스턴스
wait_store = WaitTimeStore()