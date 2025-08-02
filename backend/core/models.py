from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Enum
from sqlalchemy.ext.declarative import declarative_base
import datetime
import enum

class StatusEnum(str, enum.Enum):
    pending = "pending"
    proxying = "proxying"
    downloading = "downloading"
    paused = "paused"
    done = "done"
    failed = "failed"

Base = declarative_base()

class DownloadRequest(Base):
    __tablename__ = "download_requests"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False)
    file_name = Column(String)
    status = Column(Enum(StatusEnum), default=StatusEnum.pending)
    requested_at = Column(DateTime, default=datetime.datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    downloaded_size = Column(Integer, default=0)
    total_size = Column(Integer, default=0)
    save_path = Column(String, nullable=True)
    password = Column(String, nullable=True)
    direct_link = Column(String, nullable=True)
    use_proxy = Column(Boolean, default=True)  # 프록시 사용 여부

    def as_dict(self):
        data = {}
        for c in self.__table__.columns:
            value = getattr(self, c.name)
            if isinstance(value, datetime.datetime):
                data[c.name] = value.isoformat() if value else None
            elif isinstance(value, StatusEnum):
                data[c.name] = value.value
            elif c.name in ['downloaded_size', 'total_size'] and value is None:
                data[c.name] = 0 # Ensure these are always numbers
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