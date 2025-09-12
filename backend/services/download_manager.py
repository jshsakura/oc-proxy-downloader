# -*- coding: utf-8 -*-
"""
간단한 다운로드 매니저
- 동시 다운로드 수 제한
- 활성 다운로드 추적
"""


import os

class DownloadManager:
    """간단한 다운로드 매니저"""
    def __init__(self):
        self.active_downloads = set()  # 진행중인 다운로드 ID들
        # ENV에서 설정 읽기, 기본값 5
        self.max_concurrent = int(os.getenv('MAX_CONCURRENT_DOWNLOADS', 5))
        
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
        """다운로드 시작 - 재시도 시 기존 등록 정리"""
        # 이미 등록된 경우 먼저 정리 (재시도 지원)
        if request_id in self.active_downloads:
            print(f"[LOG] 기존 다운로드 {request_id} 정리 후 재시작")
            self.active_downloads.discard(request_id)
        
        self.active_downloads.add(request_id)
        print(f"[LOG] 다운로드 시작: {request_id} (활성: {len(self.active_downloads)})")
        
    def finish(self, request_id: int, url: str, success: bool = True):
        """다운로드 완료"""
        self.active_downloads.discard(request_id)
        print(f"[LOG] 다운로드 완료: {request_id} (활성: {len(self.active_downloads)})")
        
    def cleanup(self, request_id: int):
        """강제로 다운로드 정리 (pause/stop 시 사용)"""
        if request_id in self.active_downloads:
            self.active_downloads.discard(request_id)
            print(f"[LOG] 다운로드 강제 정리: {request_id} (활성: {len(self.active_downloads)})")
            return True
        return False

# 전역 다운로드 매니저
download_manager = DownloadManager()