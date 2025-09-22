from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
from pathlib import Path

# 환경별 config 디렉토리 설정 (config.py와 동일)
# 1. OC_CONFIG_DIR 환경변수 (스탠드얼론 실행 시 설정됨)
# 2. CONFIG_PATH 환경변수 (도커 환경에서 설정됨)
# 3. 기본값: backend/config (로컬 개발)
if os.environ.get("OC_CONFIG_DIR"):
    CONFIG_DIR = Path(os.environ["OC_CONFIG_DIR"])
elif os.environ.get("CONFIG_PATH"):
    CONFIG_DIR = Path(os.environ["CONFIG_PATH"])
else:
    CONFIG_DIR = Path(os.path.dirname(__file__)) / '..' / 'config'

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