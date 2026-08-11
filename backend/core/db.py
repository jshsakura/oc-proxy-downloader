from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path

# A running download commits progress constantly. Under the default rollback
# journal every one of those commits locks the whole file, so an unrelated
# INSERT (a newly added download) queues behind them for seconds. WAL lets
# readers run during a write and keeps the writer lock short; busy_timeout is
# the ceiling for how long a statement waits for that lock instead of failing
# with "database is locked".
SQLITE_BUSY_TIMEOUT_SEC = 30

# Environment-specific config directory setup (same as config.py)
# 1. OC_CONFIG_DIR environment variable (set when running standalone)
# 2. CONFIG_PATH environment variable (set in Docker environment)
# 3. Default: backend/config (local development)
if os.environ.get("OC_CONFIG_DIR"):
    CONFIG_DIR = Path(os.environ["OC_CONFIG_DIR"])
    print(f"[DEBUG] DB Standalone CONFIG_DIR: {CONFIG_DIR}")
elif os.environ.get("CONFIG_PATH"):
    CONFIG_DIR = Path(os.environ["CONFIG_PATH"])
    print(f"[DEBUG] DB Docker CONFIG_DIR: {CONFIG_DIR}")
else:
    CONFIG_DIR = Path(os.path.dirname(__file__)) / '..' / 'config'
    print(f"[DEBUG] DB Local CONFIG_DIR: {CONFIG_DIR}")

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CONFIG_DIR / 'downloads.db'
print(f"[DEBUG] DB_PATH: {DB_PATH}")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": SQLITE_BUSY_TIMEOUT_SEC,
    },
    # No pool ceiling. Every download task opens a session and holds it for the
    # whole download — including while it sits on a semaphore waiting for a
    # slot — so the number of live sessions tracks the number of *queued* items,
    # not the number actually transferring. A 65-item backlog therefore wanted
    # 65 connections against a pool of 10+20, and the 31st blocked for 60s and
    # then failed: "QueuePool limit of size 10 overflow 20 reached". The API
    # went down with it, because it needs a connection too.
    #
    # A pool earns its keep when connecting is expensive. For SQLite a
    # connection is a file handle, and pooling one buys nothing worth an outage.
    poolclass=NullPool,
    echo=False,  # disable SQL logging
)


@event.listens_for(engine, "connect")
def _apply_sqlite_pragmas(dbapi_connection, connection_record):
    """Put every pooled connection into WAL mode with a real busy timeout.

    journal_mode is persisted in the database file, but the PRAGMA is cheap and
    re-issuing it per connection keeps the setting correct even after the file
    is replaced (restore from backup, fresh volume).
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_SEC * 1000}")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 