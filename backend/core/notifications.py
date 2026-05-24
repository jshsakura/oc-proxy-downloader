"""
Notification-management module
- Status-update notifications
- SSE message sending
"""

from sqlalchemy.orm import Session
from .models import DownloadRequest
from .download_core import send_sse_message


def notify_status_update(db: Session, download_id: int):
    """Notify of a download status update"""
    try:
        req = db.query(DownloadRequest).filter(DownloadRequest.id == download_id).first()
        if req:
            # Calculate progress
            progress = 0.0
            if req.total_size and req.total_size > 0 and req.downloaded_size:
                progress = min(100.0, (req.downloaded_size / req.total_size) * 100)

            # Use the unified SSE-sending approach
            send_sse_message("status_update", {
                "id": req.id,
                "url": req.url,
                "file_name": req.file_name,
                "status": req.status.value,
                "error": req.error,
                "progress": progress,
                "downloaded_size": req.downloaded_size or 0,
                "total_size": req.total_size or 0,
                "download_speed": req.download_speed or 0,
                "eta": req.eta or "",
                "created_at": req.created_at.isoformat() if req.created_at else None,
                "completed_at": req.completed_at.isoformat() if req.completed_at else None
            })
    except Exception as e:
        print(f"[LOG] ❌ 상태 업데이트 알림 실패: {e}")