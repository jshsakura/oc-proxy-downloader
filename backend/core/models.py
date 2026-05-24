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
    """Convert a SQLAlchemy column value into a JSON-serializable form.

    Common rules:
    - datetime → ISO8601 string (None preserved)
    - StatusEnum → ``.value`` string
    - status == 'paused' (older DB) → migrated to 'stopped'
    - downloaded_size/total_size of None → 0 (so the UI always receives a number)
    - error is always converted to a string; encoding errors become a placeholder
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
    """Shared mixin providing ``as_dict()``.

    Consolidates into one place the identical 60-line serialization logic that
    had been copied across the two models DownloadRequest / UserProxy.
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
    original_url = Column(String, nullable=True)  # original URL (before parsing)
    file_name = Column(String)
    file_size = Column(String, nullable=True)  # file size (e.g. "6.98 GB")
    status = Column(Enum(StatusEnum), default=StatusEnum.pending)
    requested_at = Column(DateTime, default=datetime.datetime.now)
    started_at = Column(DateTime, nullable=True)  # actual download start time
    finished_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    downloaded_size = Column(Integer, default=0)
    total_size = Column(Integer, default=0)
    save_path = Column(String, nullable=True)
    password = Column(String, nullable=True)
    use_proxy = Column(Boolean, default=True)  # whether to use a proxy

    # Persist the failure classification / retry policy (same values as error_messages.KIND_*)
    # These columns prevent the problems of text re-classification (whose meaning
    # shifts whenever the classification rules change) and of pinning dead from a
    # single observation.
    failure_kind = Column(String, nullable=True, index=True)
    attempt_count = Column(Integer, default=0)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    last_probed_at = Column(DateTime, nullable=True)
    # Ring buffer of the most recent N=5 attempts (JSON array, each element {ts, stage, kind, raw, proxy})
    attempts_json = Column(Text, nullable=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # progress is a transient field, not a DB column — it is temporarily set
        # on the instance so it can be included in the SSE broadcast on
        # stop/resume, then read by another request-handling flow.
        self.progress = 0


class UserProxy(_AsDictMixin, Base):
    __tablename__ = "user_proxies"

    id = Column(Integer, primary_key=True, index=True)
    address = Column(String, nullable=False)  # proxy address (URL or IP:PORT)
    proxy_type = Column(String, default="list")  # "list" or "single"
    is_active = Column(Boolean, default=True)  # active state
    added_at = Column(DateTime, default=datetime.datetime.now)
    last_used = Column(DateTime, nullable=True)
    description = Column(String, nullable=True)  # user description


# Proxy status management table
class ProxyStatus(Base):
    __tablename__ = "proxy_status"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ip = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    last_status = Column(String, nullable=True)  # 'success' or 'fail'
    last_failed_at = Column(DateTime, nullable=True)
    success = Column(Boolean, nullable=True)  # added for compatibility
