# -*- coding: utf-8 -*-
"""
간단한 다운로드 매니저
- 동시 다운로드 수 제한
- 활성 다운로드 추적
"""


class DownloadManager:
    """간단한 다운로드 매니저"""
    def __init__(self):
        self.active_downloads = set()  # 진행중인 다운로드 ID들
        self.max_concurrent = 5  # 동시 다운로드 제한 (늘림)
        
    def can_start(self, request_id: int, url: str) -> bool:
        """다운로드를 시작할 수 있는지 확인"""
        # 이미 실행 중이면 안됨
        if request_id in self.active_downloads:
            return False
            
        # 동시 다운로드 제한 확인만
        if len(self.active_downloads) >= self.max_concurrent:
            print(f"[LOG] 동시 다운로드 제한: {len(self.active_downloads)}/{self.max_concurrent}")
            return False
                
        return True
        
    def start(self, request_id: int, url: str):
        """다운로드 시작"""
        self.active_downloads.add(request_id)
        print(f"[LOG] 다운로드 시작: {request_id} (활성: {len(self.active_downloads)})")
        
    def finish(self, request_id: int, url: str, success: bool = True):
        """다운로드 완료"""
        self.active_downloads.discard(request_id)
        print(f"[LOG] 다운로드 완료: {request_id} (활성: {len(self.active_downloads)})")

# 전역 다운로드 매니저
download_manager = DownloadManager()