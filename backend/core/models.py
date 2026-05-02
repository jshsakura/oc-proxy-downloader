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


Base = declarative_base()


def _serialize_column_value(name, value):
    """SQLAlchemy 컬럼 값을 JSON 직렬화 가능한 형태로 변환.

    공통 규칙:
    - datetime → ISO8601 문자열 (None 보존)
    - StatusEnum → ``.value`` 문자열
    - status == 'paused' (구버전 DB) → 'stopped' 으로 마이그레이션
    - downloaded_size/total_size 가 None → 0 (UI 가 항상 숫자로 받게)
    - error 는 항상 문자열로 변환, encoding 오류는 placeholder 로
    """
    if isinstance(value, datetime.datetime):
        return value.isoformat() if value else None
    if isinstance(value, StatusEnum):
        return value.value
    if name == "status" and isinstance(value, str) and value == "paused":
        return "stopped"  # legacy migration
    if name in ("downloaded_size", "total_size") and value is None:
        return 0
    if name == "error" and value:
        try:
            return str(value)
        except (UnicodeDecodeError, UnicodeEncodeError) as e:
            print(f"[LOG] Encoding error for {name}: {e}")
            return "Encoding error"
    return value


class _AsDictMixin:
    """``as_dict()`` 를 제공하는 공용 mixin.

    DownloadRequest / UserProxy 등 두 모델에 동일한 60줄짜리 직렬화
    로직이 복사돼 있던 것을 한 곳으로 모음.
    """

    def as_dict(self):
        return {
            c.name: _serialize_column_value(c.name, getattr(self, c.name))
            for c in self.__table__.columns
        }


class DownloadRequest(_AsDictMixin, Base):
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
        # progress 는 DB 컬럼이 아닌 transient 필드 — 정지/재개 시 SSE
        # broadcast 에 포함시키려고 인스턴스에 임시로 set 한 뒤 다른 요청
        # 처리 흐름이 읽어간다.
        self.progress = 0


class UserProxy(_AsDictMixin, Base):
    __tablename__ = "user_proxies"

    id = Column(Integer, primary_key=True, index=True)
    address = Column(String, nullable=False)  # 프록시 주소 (URL 또는 IP:PORT)
    proxy_type = Column(String, default="list")  # "list" 또는 "single"
    is_active = Column(Boolean, default=True)  # 활성 상태
    added_at = Column(DateTime, default=datetime.datetime.now)
    last_used = Column(DateTime, nullable=True)
    description = Column(String, nullable=True)  # 사용자 설명


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
