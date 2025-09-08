"""
공유 객체들을 위한 모듈
다른 모듈에서 main.py를 import하지 않도록 필요한 객체들을 분리
"""

import queue
import threading
import time
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
        self.MAX_LOCAL_DOWNLOADS = 1  # 최대 로컬 다운로드 수 (1fichier만)
        self.MAX_TOTAL_DOWNLOADS = 5  # 최대 전체 동시 다운로드 수
        
        # 1fichier 다운로드 쿨다운 관리
        self.last_1fichier_completion_time = 0  # 마지막 1fichier 다운로드 완료 시간
        self.FICHIER_COOLDOWN_SECONDS = 90  # 1fichier 다운로드 간 대기 시간 (초) - 1fichier 서버 부하 방지
        
        # 전역 정지 플래그 시스템 (안전한 즉시 정지)
        self.stop_events = {}  # {download_id: threading.Event}
        
        # 스레드 안전성을 위한 락
        self._lock = threading.Lock()

    def can_start_download(self, url=None):
        """다운로드를 시작할 수 있는지 확인 (전체 제한 + 1fichier 개별 제한 + 쿨다운)"""
        with self._lock:
            # 전체 다운로드 수 체크
            print(f"[LOG] can_start_download 체크 - 전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS}, 로컬: {len(self.local_downloads)}/{self.MAX_LOCAL_DOWNLOADS}")
            if len(self.all_downloads) >= self.MAX_TOTAL_DOWNLOADS:
                print(f"[LOG] 전체 다운로드 제한으로 시작 불가 ({self.MAX_TOTAL_DOWNLOADS}개)")
                return False
            
            # 1fichier인 경우 개별 제한도 체크
            if url and '1fichier.com' in url:
                if len(self.local_downloads) >= self.MAX_LOCAL_DOWNLOADS:
                    print(f"[LOG] 1fichier 로컬 다운로드 제한으로 시작 불가 ({self.MAX_LOCAL_DOWNLOADS}개)")
                    return False
                
                # 1fichier 로컬 다운로드 대기 중인 것이 있는지 체크 (proxying 상태, 로컬만)
                db = None
                try:
                    db = next(get_db())
                    waiting_local_fichier = db.query(DownloadRequest).filter(
                        DownloadRequest.status == StatusEnum.proxying,
                        DownloadRequest.url.contains('1fichier.com'),
                        DownloadRequest.use_proxy == False  # 로컬 다운로드만 체크
                    ).first()
                    if waiting_local_fichier:
                        print(f"[LOG] 1fichier 로컬 대기 중인 다운로드 있음: ID {waiting_local_fichier.id}")
                        return False
                except Exception as e:
                    print(f"[LOG] 1fichier 대기 상태 체크 실패: {e}")
                finally:
                    if db:
                        try:
                            db.close()
                        except:
                            pass
                
                # 1fichier 쿨다운 시간 체크
                current_time = time.time()
                if self.last_1fichier_completion_time > 0:
                    time_since_completion = current_time - self.last_1fichier_completion_time
                    if time_since_completion < self.FICHIER_COOLDOWN_SECONDS:
                        remaining_time = self.FICHIER_COOLDOWN_SECONDS - time_since_completion
                        print(f"[LOG] 1fichier 쿨다운 중. 남은 시간: {remaining_time:.1f}초")
                        return False
            
            return True
    
    def get_1fichier_cooldown_remaining(self):
        """1fichier 쿨다운 남은 시간 반환 (초)"""
        with self._lock:
            if self.last_1fichier_completion_time == 0:
                return 0
            
            current_time = time.time()
            time_since_completion = current_time - self.last_1fichier_completion_time
            
            if time_since_completion >= self.FICHIER_COOLDOWN_SECONDS:
                return 0
            
            return self.FICHIER_COOLDOWN_SECONDS - time_since_completion
    
    def can_start_local_download(self, url=None):
        """로컬 다운로드를 시작할 수 있는지 확인 (1fichier만 제한) - 하위 호환성"""
        return self.can_start_download(url)
    
    def start_download(self, download_id, func, *args, **kwargs):
        self.cancel_download(download_id)
        with self._lock:
            t = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
            t.start()
            self.active_downloads[download_id] = t
    
    def register_download(self, download_id, url=None, use_proxy=False):
        """다운로드 등록 (전체 + 1fichier 개별)"""
        with self._lock:
            # 모든 다운로드 등록
            self.all_downloads.add(download_id)
            
            # 정지 플래그 초기화
            self.stop_events[download_id] = threading.Event()
            
            # 1fichier이고 로컬 다운로드인 경우만 별도 등록
            if url and '1fichier.com' in url and not use_proxy:
                self.local_downloads.add(download_id)
                print(f"[LOG] 1fichier 로컬 다운로드 등록: {download_id} (1fichier: {len(self.local_downloads)}/{self.MAX_LOCAL_DOWNLOADS}, 전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS})")
            else:
                proxy_type = "프록시" if use_proxy else "일반"
                print(f"[LOG] {proxy_type} 다운로드 등록: {download_id} (전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS})")
    
    def register_local_download(self, download_id, url=None):
        """로컬 다운로드 등록 - 하위 호환성"""
        self.register_download(download_id, url)
    
    def unregister_download(self, download_id, is_completed=False, auto_start_next=True):
        """다운로드 해제 (전체 + 1fichier 개별)"""
        was_fichier = False
        with self._lock:
            # 전체 다운로드에서 해제
            self.all_downloads.discard(download_id)
            
            # 정지 플래그 정리
            if download_id in self.stop_events:
                del self.stop_events[download_id]
            
            # 1fichier 다운로드에서 해제
            was_fichier = download_id in self.local_downloads
            if was_fichier:
                self.local_downloads.discard(download_id)
                print(f"[LOG] 1fichier 다운로드 해제: {download_id} (1fichier: {len(self.local_downloads)}/{self.MAX_LOCAL_DOWNLOADS}, 전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS})")
                
                # 1fichier 다운로드가 성공적으로 완료된 경우 쿨다운 시작
                if is_completed:
                    self.last_1fichier_completion_time = time.time()
                    print(f"[LOG] 1fichier 다운로드 완료. 쿨다운 {self.FICHIER_COOLDOWN_SECONDS}초 시작")
            else:
                print(f"[LOG] 다운로드 해제: {download_id} (전체: {len(self.all_downloads)}/{self.MAX_TOTAL_DOWNLOADS})")
        
        # 락 외부에서 대기 중인 다운로드 체크 (데드락 방지)
        # 1fichier 로컬 다운로드 완료 후에는 쿨다운 시간만큼 지연
        if was_fichier and is_completed:
            # 쿨다운 시간 후에 대기 중인 다운로드 체크
            def delayed_check():
                try:
                    time.sleep(self.FICHIER_COOLDOWN_SECONDS)
                    print(f"[LOG] 1fichier 쿨다운 완료. 대기 중인 다운로드 체크")
                    self.check_and_start_waiting_downloads()
                except Exception as e:
                    print(f"[LOG] 지연된 다운로드 체크 중 오류: {e}")
            
            threading.Thread(target=delayed_check, daemon=True).start()
        else:
            # 즉시 대기 중인 다운로드 체크 (auto_start_next가 True인 경우만)
            print(f"[LOG] 다운로드 해제 후 자동 시작 체크: auto_start_next={auto_start_next}")
            if auto_start_next:
                print(f"[LOG] 대기 중인 다운로드 자동 시작 체크 호출")
                self.check_and_start_waiting_downloads()
            else:
                print(f"[LOG] auto_start_next=False이므로 자동 시작 건너뜀")
    
    def unregister_local_download(self, download_id):
        """로컬 다운로드 해제 - 하위 호환성"""
        self.unregister_download(download_id)
    
    def stop_download_immediately(self, download_id):
        """특정 다운로드를 즉시 정지 (안전한 방법)"""
        with self._lock:
            if download_id in self.stop_events:
                self.stop_events[download_id].set()
                print(f"[LOG] ★★★ 다운로드 {download_id} 즉시 정지 플래그 설정 완료 ★★★")
                return True
            else:
                print(f"[LOG] ⚠️ 다운로드 {download_id} 정지 플래그를 찾을 수 없음 - 등록되지 않은 다운로드")
                return False
    
    def is_download_stopped(self, download_id):
        """특정 다운로드가 정지되었는지 확인"""
        with self._lock:
            if download_id in self.stop_events:
                is_stopped = self.stop_events[download_id].is_set()
                if is_stopped:
                    print(f"[LOG] ★★★ 다운로드 {download_id} 정지 플래그 감지됨 ★★★")
                return is_stopped
            return False
    
    def check_and_start_waiting_downloads(self):
        """대기 중인 다운로드를 확인하고 시작 (전체 제한 + 1fichier 개별 제한 고려)"""
        db = None
        try:
            db = next(get_db())
            
            # DB에서 실제 downloading 상태인 다운로드 수 확인 (더 정확함)
            from .models import DownloadRequest, StatusEnum
            active_downloads_count = db.query(DownloadRequest).filter(
                DownloadRequest.status == StatusEnum.downloading
            ).count()
            
            active_1fichier_count = db.query(DownloadRequest).filter(
                DownloadRequest.status == StatusEnum.downloading,
                DownloadRequest.use_proxy == False,
                DownloadRequest.url.contains('1fichier.com')
            ).count()
            
            print(f"[LOG] 대기 중인 다운로드 체크 시작 (실제 활성: {active_downloads_count}/{self.MAX_TOTAL_DOWNLOADS}, 1fichier: {active_1fichier_count}/{self.MAX_LOCAL_DOWNLOADS})")
            
            # 전체 다운로드 수가 5개 이상이면 시작하지 않음
            if active_downloads_count >= self.MAX_TOTAL_DOWNLOADS:
                print(f"[LOG] 전체 다운로드 제한 도달 ({self.MAX_TOTAL_DOWNLOADS}개). 대기 중...")
                return
            
            # 현재 실행 중인 다운로드 ID 목록 가져오기 (중복 시작 방지)
            with self._lock:
                active_ids = list(self.active_downloads.keys())
            
            # 1. 프록시 다운로드 우선 처리 (제한 없음)
            if active_downloads_count < self.MAX_TOTAL_DOWNLOADS:
                proxy_request = db.query(DownloadRequest).filter(
                    DownloadRequest.status == StatusEnum.pending,
                    DownloadRequest.use_proxy == True,
                    # 이미 실행 중인 다운로드는 제외
                    ~DownloadRequest.id.in_(active_ids) if active_ids else True
                ).order_by(DownloadRequest.requested_at.asc()).first()  # 먼저 요청된 순서대로 (FIFO)
                
                if proxy_request:
                    print(f"[LOG] 대기 중인 프록시 다운로드 발견: {proxy_request.id} (실행중 제외: {active_ids})")
                    self._start_waiting_download(proxy_request)
                    return

            # 2. 1fichier가 아닌 로컬 다운로드 찾기
            if active_downloads_count < self.MAX_TOTAL_DOWNLOADS:
                non_fichier_request = db.query(DownloadRequest).filter(
                    DownloadRequest.status == StatusEnum.pending,
                    DownloadRequest.use_proxy == False,
                    ~DownloadRequest.url.contains('1fichier.com'),
                    # 이미 실행 중인 다운로드는 제외
                    ~DownloadRequest.id.in_(active_ids) if active_ids else True
                ).order_by(DownloadRequest.requested_at.asc()).first()  # 먼저 요청된 순서대로 (FIFO)
                
                if non_fichier_request:
                    print(f"[LOG] 대기 중인 비-1fichier 다운로드 발견: {non_fichier_request.id} (실행중 제외: {active_ids})")
                    self._start_waiting_download(non_fichier_request)
                    return
            
            # 3. 1fichier 로컬 다운로드 찾기 (1fichier 개별 제한 + 쿨다운 체크)
            if (active_downloads_count < self.MAX_TOTAL_DOWNLOADS and 
                active_1fichier_count < self.MAX_LOCAL_DOWNLOADS and
                self.can_start_download("https://1fichier.com/dummy")):  # 쿨다운 포함 체크
                
                # 현재 실행 중인 다운로드 ID 목록 가져오기
                with self._lock:
                    active_ids = list(self.active_downloads.keys())
                
                fichier_request = db.query(DownloadRequest).filter(
                    DownloadRequest.status == StatusEnum.pending,
                    DownloadRequest.use_proxy == False,
                    DownloadRequest.url.contains('1fichier.com'),
                    # 이미 실행 중인 다운로드는 제외
                    ~DownloadRequest.id.in_(active_ids) if active_ids else True
                ).order_by(DownloadRequest.requested_at.asc()).first()  # 먼저 요청된 순서대로 (FIFO)
                
                if fichier_request:
                    print(f"[LOG] 대기 중인 1fichier 다운로드 발견: {fichier_request.id} (실행중 제외: {active_ids})")
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
        """대기 중인 다운로드 시작 - 1fichier와 일반 다운로드 분기"""
        import threading
        
        # 이미 실행 중인지 체크 (중복 시작 방지)
        with self._lock:
            if waiting_request.id in self.active_downloads:
                print(f"[LOG] 다운로드 {waiting_request.id}는 이미 실행 중 - 중복 시작 방지")
                return
        
        # DB에서 최신 프록시 설정 다시 조회 (실시간 업데이트 반영)
        try:
            db = next(get_db())
            fresh_request = db.query(DownloadRequest).filter(DownloadRequest.id == waiting_request.id).first()
            use_proxy = fresh_request.use_proxy if fresh_request else getattr(waiting_request, 'use_proxy', False)
            print(f"[LOG] 다운로드 {waiting_request.id} 최신 프록시 설정: {use_proxy}")
        except:
            use_proxy = getattr(waiting_request, 'use_proxy', False)
            print(f"[LOG] 다운로드 {waiting_request.id} 기본 프록시 설정 사용: {use_proxy}")
        
        # URL 타입에 따라 적절한 다운로드 함수 선택
        if "1fichier.com" in waiting_request.url.lower():
            # 1fichier 다운로드
            from core.download_core import download_1fichier_file_new
            target_function = download_1fichier_file_new
            print(f"[LOG] 1fichier 다운로드 시작: {waiting_request.id}")
        else:
            # 일반 다운로드
            from core.download_core import download_general_file
            target_function = download_general_file
            print(f"[LOG] 일반 다운로드 시작: {waiting_request.id}")
        
        thread = threading.Thread(
            target=target_function,
            args=(waiting_request.id, "ko", use_proxy),
            daemon=True
        )
        thread.start()
        
        # active_downloads에 추가 (중복 시작 방지용)
        with self._lock:
            self.active_downloads[waiting_request.id] = thread
            
        print(f"[LOG] 대기 중인 다운로드 시작: {waiting_request.id} (프록시: {use_proxy})")

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
                print(f"[LOG] 다운로드 {download_id} 상태를 stopped로 변경 (이어받기 지원)")
                
                # WebSocket 상태 업데이트 브로드캐스트
                import json
                status_queue.put(json.dumps({
                    "type": "status_update",
                    "data": {
                        "id": download_id,
                        "status": "stopped"
                    }
                }))
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
                import json
                for download_id in download_ids:
                    req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
                    if req and req.status in [StatusEnum.downloading, StatusEnum.proxying]:
                        req.status = StatusEnum.stopped
                        print(f"[LOG] 다운로드 {download_id} 상태를 stopped로 변경 (이어받기 지원)")
                        
                        # WebSocket 상태 업데이트 브로드캐스트
                        status_queue.put(json.dumps({
                            "type": "status_update",
                            "data": {
                                "id": download_id,
                                "status": "stopped"
                            }
                        }))
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