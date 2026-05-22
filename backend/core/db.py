from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path

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
    connect_args={"check_same_thread": False},
    pool_size=10,  # increase the base pool size
    max_overflow=20,  # allow overflow
    pool_timeout=60,  # increase the connection wait time
    pool_recycle=3600,  # recycle connections every hour
    pool_pre_ping=True,  # pre-check connection validity
    echo=False  # disable SQL logging
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 