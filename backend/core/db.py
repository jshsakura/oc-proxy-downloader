from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path

# Docker 환경에서는 /config 사용, 개발 환경에서는 backend/config 사용
CONFIG_DIR = Path(os.environ.get("CONFIG_PATH", os.path.join(os.path.dirname(__file__), '..', 'config')))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CONFIG_DIR / 'downloads.db'
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    pool_size=10,  # 기본 풀 크기 증가
    max_overflow=20,  # 오버플로우 허용
    pool_timeout=60,  # 연결 대기 시간 증가
    pool_recycle=3600,  # 1시간마다 연결 재활용
    pool_pre_ping=True,  # 연결 유효성 사전 검사
    echo=False  # SQL 로깅 비활성화
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 