from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Enum
from sqlalchemy.ext.declarative import declarative_base
import datetime
import enum

class StatusEnum(str, enum.Enum):
    pending = "pending"
    parsing = "parsing"
    waiting = "waiting"
    proxying = "proxying"
    downloading = "downloading"
    stopped = "stopped"
    done = "done"
    failed = "failed"
    cooldown = "cooldown"

Base = declarative_base()

class DownloadRequest(Base):
    __tablename__ = "download_requests"
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False)
    original_url = Column(String, nullable=True)  # 원본 URL (파싱 전)
    file_name = Column(String)
    file_size = Column(String, nullable=True)  # 파일 크기 (예: "6.98 GB")
    status = Column(Enum(StatusEnum), default=StatusEnum.pending)
    requested_at = Column(DateTime, default=datetime.datetime.now)
    started_at = Column(DateTime, nullable=True)  # 실제 다운로드 시작 시간
    finished_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    downloaded_size = Column(Integer, default=0)
    total_size = Column(Integer, default=0)
    save_path = Column(String, nullable=True)
    password = Column(String, nullable=True)
    use_proxy = Column(Boolean, default=True)  # 프록시 사용 여부

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 임시 속성들 (DB에 저장되지 않음)
        self._wait_until = None  # 대기 완료 시간
        self.progress = 0  # 현재 진행률

    @property
    def wait_until(self):
        """대기 완료 시간을 반환합니다. DB에서 로드된 객체의 경우 기본값을 반환합니다."""
        return getattr(self, '_wait_until', None)

    @wait_until.setter
    def wait_until(self, value):
        """대기 완료 시간을 설정합니다."""
        self._wait_until = value

    def as_dict(self):
        data = {}
        for c in self.__table__.columns:
            value = getattr(self, c.name)
            if isinstance(value, datetime.datetime):
                data[c.name] = value.isoformat() if value else None
            elif isinstance(value, StatusEnum):
                data[c.name] = value.value
            elif c.name == 'status' and isinstance(value, str) and value == 'paused':
                # Handle legacy 'paused' status for backward compatibility
                data[c.name] = 'stopped'
            elif c.name in ['downloaded_size', 'total_size'] and value is None:
                data[c.name] = 0 # Ensure these are always numbers
            elif c.name == 'error' and value:
                # Clean error messages (simplified for performance)
                try:
                    data[c.name] = str(value)
                except (UnicodeDecodeError, UnicodeEncodeError) as e:
                    print(f"[LOG] Encoding error for {c.name}: {e}")
                    data[c.name] = "Encoding error"
            else:
                data[c.name] = value
        return data


class UserProxy(Base):
    __tablename__ = "user_proxies"
    
    id = Column(Integer, primary_key=True, index=True)
    address = Column(String, nullable=False)  # 프록시 주소 (URL 또는 IP:PORT)
    proxy_type = Column(String, default="list")  # "list" 또는 "single"
    is_active = Column(Boolean, default=True)  # 활성 상태
    added_at = Column(DateTime, default=datetime.datetime.now)
    last_used = Column(DateTime, nullable=True)
    description = Column(String, nullable=True)  # 사용자 설명

    def as_dict(self):
        data = {}
        for c in self.__table__.columns:
            value = getattr(self, c.name)
            if isinstance(value, datetime.datetime):
                data[c.name] = value.isoformat() if value else None
            elif isinstance(value, StatusEnum):
                data[c.name] = value.value
            elif c.name == 'status' and isinstance(value, str) and value == 'paused':
                # Handle legacy 'paused' status for backward compatibility
                data[c.name] = 'stopped'
            elif c.name in ['downloaded_size', 'total_size'] and value is None:
                data[c.name] = 0 # Ensure these are always numbers
            elif c.name == 'error' and value:
                # Clean error messages (simplified for performance)
                try:
                    data[c.name] = str(value)
                except (UnicodeDecodeError, UnicodeEncodeError) as e:
                    print(f"[LOG] Encoding error for {c.name}: {e}")
                    data[c.name] = "Encoding error"
            else:
                data[c.name] = value
        return data

# 프록시 상태 관리 테이블
class ProxyStatus(Base):
    __tablename__ = "proxy_status"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    last_status = Column(String, nullable=True)  # 'success' or 'fail'
    last_failed_at = Column(DateTime, nullable=True)
    success = Column(Boolean, nullable=True)  # 호환성을 위해 추가