"""
공유 객체들을 위한 모듈
다른 모듈에서 main.py를 import하지 않도록 필요한 객체들을 분리
"""

import queue
import threading
from sqlalchemy.orm import Session
from core.db import get_db
from core.models import DownloadRequest, StatusEnum

# WebSocket 메시지 큐
status_queue = queue.Queue()

class DownloadManager:
    def __init__(self):
        self.active_downloads = {}  # {download_id: Thread}

    def start_download(self, download_id, func, *args, **kwargs):
        self.cancel_download(download_id)
        t = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
        t.start()
        self.active_downloads[download_id] = t

    def cancel_download(self, download_id):
        # 다운로드 상태를 stopped로 변경하여 자연스럽게 종료되도록 함
        print(f"[LOG] 다운로드 매니저: {download_id} 취소 요청")
        
        # DB 상태 변경
        db = next(get_db())
        try:
            req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
            if req and req.status in [StatusEnum.downloading, StatusEnum.proxying]:
                req.status = StatusEnum.stopped
                db.commit()
                print(f"[LOG] 다운로드 {download_id} 상태를 stopped로 변경")
        except Exception as e:
            print(f"[LOG] 다운로드 상태 변경 실패: {e}")
        finally:
            db.close()
        
        # 관리 목록에서 제거
        self.active_downloads.pop(download_id, None)

    def is_download_active(self, download_id):
        t = self.active_downloads.get(download_id)
        return t and t.is_alive()

    def terminate_all_downloads(self):
        print("[LOG] 모든 다운로드 스레드 관리 목록에서 제거 (스레드는 강제 종료 불가)")
        # 진행 중인 다운로드 ID들을 수집
        download_ids = list(self.active_downloads.keys())
        self.active_downloads.clear()
        
        # 각 다운로드의 상태를 paused로 변경하여 자연스럽게 종료되도록 함
        if download_ids:
            db = next(get_db())
            try:
                for download_id in download_ids:
                    req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
                    if req and req.status in [StatusEnum.downloading, StatusEnum.proxying]:
                        req.status = StatusEnum.stopped
                        print(f"[LOG] 다운로드 {download_id} 상태를 paused로 변경하여 종료 유도")
                db.commit()
            except Exception as e:
                print(f"[LOG] 다운로드 상태 변경 실패: {e}")
            finally:
                db.close()

# 전역 다운로드 매니저 인스턴스
download_manager = DownloadManager()