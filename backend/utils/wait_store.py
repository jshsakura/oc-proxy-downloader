# -*- coding: utf-8 -*-
"""
Wait-time tracking store
- Thread-safe wait-time management
- Tracks download wait states
"""

import threading
import time


class WaitTimeStore:
    """Thread-safe wait-time store"""
    
    def __init__(self):
        self._wait_tasks = {}  # {download_id: {"start_time": timestamp, "total_wait": seconds, "url": url}}
        self._lock = threading.Lock()
    
    def start_wait(self, download_id, total_wait_seconds, url):
        """Register the start of a wait"""
        with self._lock:
            self._wait_tasks[download_id] = {
                "start_time": time.time(),
                "total_wait": total_wait_seconds,
                "url": url
            }
            print(f"[STORE] 대기 추적 시작: ID {download_id}, 총 {total_wait_seconds}초")
    
    def finish_wait(self, download_id):
        """Finish a wait - remove it from tracking"""
        with self._lock:
            if download_id in self._wait_tasks:
                del self._wait_tasks[download_id]
                print(f"[STORE] 대기 추적 완료: ID {download_id}")
                return True
            return False
    
    def get_remaining_time(self, download_id):
        """Calculate the remaining wait time (seconds)"""
        with self._lock:
            if download_id not in self._wait_tasks:
                return None
            
            wait_info = self._wait_tasks[download_id]
            elapsed_time = time.time() - wait_info["start_time"]
            remaining_time = max(0, wait_info["total_wait"] - elapsed_time)
            
            if remaining_time <= 0:
                # Wait time is over, so remove it from tracking
                del self._wait_tasks[download_id]
                return None
            
            return {
                "remaining_time": int(remaining_time),
                "total_wait_time": wait_info["total_wait"],
                "url": wait_info["url"]
            }
    
    def get_all_active_waits(self):
        """Return all in-progress wait tasks"""
        with self._lock:
            result = {}
            expired_ids = []
            
            for download_id in list(self._wait_tasks.keys()):
                wait_info = self.get_remaining_time(download_id)
                if wait_info:
                    result[download_id] = wait_info
                else:
                    expired_ids.append(download_id)
            
            # Remove expired tasks
            for expired_id in expired_ids:
                self._wait_tasks.pop(expired_id, None)
            
            return result


# Global wait-time store instance
wait_store = WaitTimeStore()