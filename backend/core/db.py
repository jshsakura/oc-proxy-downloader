from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path

# Docker 환경에서는 /config 사용, 개발 환경에서는 기존 위치 사용
CONFIG_DIR = Path(os.environ.get("CONFIG_PATH", os.path.join(os.path.dirname(__file__), '..')))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CONFIG_DIR / 'downloads.db'
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 