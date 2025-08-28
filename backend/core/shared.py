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
        self.local_downloads = set()  # 로컬 다운로드 ID 집합 (1fichier만)
        self.all_downloads = set()  # 전체 다운로드 ID 집합 (모든 도메인)
        self.MAX_LOCAL_DOWNLOADS = 2  # 최대 로컬 다운로드 수 (1fichier만)
        self.MAX_TOTAL_DOWNLOADS = 5  # 최대 전체 동시 다운로드 수
        
        # 스레드 안전성을 위한 락
        self._lock = threading.Lock()

    def can_start_download(self, url=None):
        """다운로드를 시작할 수 있는지 확인 (전체 제한 + 1fichier 개별 제한)"""
        with self._lock:
            # 전체 다운로드 수 체크
            if len(self.all_downloads) >= self.MAX_TOTAL_DOWNLOADS:
                return False
            
            # 1fichier인 경우 개별 제한도 체크
            if url and '1fichier.com' in url:
                if len(self.local_downloads) >= self.MAX_LOCAL_DOWNLOADS:
                    return False
            
            return True
    
    def can_start_local_download(self, url=None):
        """로컬 다운로드를 시작할 수 있는지 확인 (1fichier만 제한) - 하위 호환성"""
        return self.can_start_download(url)
    
    def start_download(self, download_id, func, *args, **kwargs):
        self.cancel_download(download_id)
        with self._lock:
            t = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
            t.start()
            self.active_downloads[download_id] = t
    
    def register_download(self, download_id, url=None):
        """다운로드 등록 (전체 + 1fichier 개별)"""
        with self._lock:
            # 모든 다운로드 등록
            self.all_downloads.add(download_id)
            
            # 1fichier인 경우 별도 등록
            if url and '1fichier.com' in url:
                self.local_downloads.add(download_id)
                print(f"[LOG] 1fichier 다운로드 등록: {download_id} (1fichier: {len(self.local_downloads)}/{self.MAX_LOCAL_DOWNLOADS}, 전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS})")
            else:
                print(f"[LOG] 다운로드 등록: {download_id} (전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS})")
    
    def register_local_download(self, download_id, url=None):
        """로컬 다운로드 등록 - 하위 호환성"""
        self.register_download(download_id, url)
    
    def unregister_download(self, download_id):
        """다운로드 해제 (전체 + 1fichier 개별)"""
        with self._lock:
            # 전체 다운로드에서 해제
            self.all_downloads.discard(download_id)
            
            # 1fichier 다운로드에서 해제
            was_fichier = download_id in self.local_downloads
            if was_fichier:
                self.local_downloads.discard(download_id)
                print(f"[LOG] 1fichier 다운로드 해제: {download_id} (1fichier: {len(self.local_downloads)}/{self.MAX_LOCAL_DOWNLOADS}, 전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS})")
            else:
                print(f"[LOG] 다운로드 해제: {download_id} (전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS})")
        
        # 락 외부에서 대기 중인 다운로드 체크 (데드락 방지)
        self.check_and_start_waiting_downloads()
    
    def unregister_local_download(self, download_id):
        """로컬 다운로드 해제 - 하위 호환성"""
        self.unregister_download(download_id)
    
    def check_and_start_waiting_downloads(self):
        """대기 중인 다운로드를 확인하고 시작 (전체 제한 + 1fichier 개별 제한 고려)"""
        db = None
        try:
            db = next(get_db())
            
            # 전체 다운로드 수가 5개 미만인 경우에만 시작
            if len(self.all_downloads) >= self.MAX_TOTAL_DOWNLOADS:
                print(f"[LOG] 전체 다운로드 제한 도달 ({self.MAX_TOTAL_DOWNLOADS}개). 대기 중...")
                return
            
            # 1. 먼저 1fichier가 아닌 대기 중인 다운로드 찾기
            if len(self.all_downloads) < self.MAX_TOTAL_DOWNLOADS:
                non_fichier_request = db.query(DownloadRequest).filter(
                    DownloadRequest.status == StatusEnum.pending,
                    DownloadRequest.use_proxy == False,
                    ~DownloadRequest.url.contains('1fichier.com')
                ).order_by(DownloadRequest.requested_at.asc()).first()
                
                if non_fichier_request:
                    print(f"[LOG] 대기 중인 비-1fichier 다운로드 발견: {non_fichier_request.id}")
                    self._start_waiting_download(non_fichier_request)
                    return
            
            # 2. 1fichier 다운로드 찾기 (1fichier 개별 제한도 체크)
            if (len(self.all_downloads) < self.MAX_TOTAL_DOWNLOADS and 
                len(self.local_downloads) < self.MAX_LOCAL_DOWNLOADS):
                
                fichier_request = db.query(DownloadRequest).filter(
                    DownloadRequest.status == StatusEnum.pending,
                    DownloadRequest.use_proxy == False,
                    DownloadRequest.url.contains('1fichier.com')
                ).order_by(DownloadRequest.requested_at.asc()).first()
                
                if fichier_request:
                    print(f"[LOG] 대기 중인 1fichier 다운로드 발견: {fichier_request.id}")
                    self._start_waiting_download(fichier_request)
                    return
                    
        except Exception as e:
            print(f"[LOG] 대기 중인 다운로드 시작 실패: {e}")
        finally:
            if db:
                try:
                    db.close()
                except:
                    pass
    
    def _start_waiting_download(self, waiting_request):
        """대기 중인 다운로드 시작"""
        from core.download_core import download_1fichier_file_new
        import threading
        
        thread = threading.Thread(
            target=download_1fichier_file_new,
            args=(waiting_request.id, "ko", False),
            daemon=True
        )
        thread.start()
        print(f"[LOG] 대기 중인 다운로드 시작: {waiting_request.id}")

    def cancel_download(self, download_id):
        # 다운로드 상태를 stopped로 변경하여 자연스럽게 종료되도록 함
        print(f"[LOG] 다운로드 매니저: {download_id} 취소 요청")
        
        # DB 상태 변경
        db = None
        try:
            db = next(get_db())
            req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
            if req and req.status in [StatusEnum.downloading, StatusEnum.proxying]:
                req.status = StatusEnum.stopped
                db.commit()
                print(f"[LOG] 다운로드 {download_id} 상태를 stopped로 변경")
        except Exception as e:
            print(f"[LOG] 다운로드 상태 변경 실패: {e}")
        finally:
            if db:
                try:
                    db.close()
                except:
                    pass
        
        # 관리 목록에서 제거
        with self._lock:
            self.active_downloads.pop(download_id, None)
        # 다운로드에서 해제
        self.unregister_download(download_id)

    def is_download_active(self, download_id):
        with self._lock:
            t = self.active_downloads.get(download_id)
            return t and t.is_alive()

    def terminate_all_downloads(self):
        print("[LOG] 모든 다운로드 스레드 관리 목록에서 제거 (스레드는 강제 종료 불가)")
        # 진행 중인 다운로드 ID들을 수집
        with self._lock:
            download_ids = list(self.active_downloads.keys())
            self.active_downloads.clear()
        
        # 각 다운로드의 상태를 stopped로 변경하여 자연스럽게 종료되도록 함
        if download_ids:
            db = None
            try:
                db = next(get_db())
                for download_id in download_ids:
                    req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
                    if req and req.status in [StatusEnum.downloading, StatusEnum.proxying]:
                        req.status = StatusEnum.stopped
                        print(f"[LOG] 다운로드 {download_id} 상태를 stopped로 변경하여 종료 유도")
                db.commit()
            except Exception as e:
                print(f"[LOG] 다운로드 상태 변경 실패: {e}")
            finally:
                if db:
                    try:
                        db.close()
                    except:
                        pass

# 전역 다운로드 매니저 인스턴스
download_manager = DownloadManager()