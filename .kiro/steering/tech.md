# 기술 스택

## 백엔드
- **프레임워크**: FastAPI (Python 3.11+)
- **데이터베이스**: SQLite with SQLAlchemy ORM
- **웹 스크래핑**: cloudscraper, lxml, requests
- **실시간 통신**: WebSocket을 통한 상태 업데이트
- **프로세스 관리**: 다운로드 작업을 위한 multiprocessing
- **서버**: uvicorn ASGI 서버

## 프론트엔드
- **프레임워크**: Svelte 5 with Vite
- **빌드 도구**: 개발 및 프로덕션 빌드를 위한 Vite
- **패키지 매니저**: npm

## 배포
- **컨테이너화**: 멀티 스테이지 빌드를 사용한 Docker
- **오케스트레이션**: 로컬 개발을 위한 docker-compose
- **베이스 이미지**: node:20 (프론트엔드 빌드), python:3.11-slim (런타임)

## 개발 환경
- **Python 가상환경**: 의존성 격리를 위한 venv
- **개발 서버**: 프론트엔드/백엔드 동시 실행을 위한 커스텀 `run_dev.py` 스크립트

## 주요 명령어

### 개발 환경 설정
```bash
# 백엔드 설정
python -m venv venv
.\venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux
pip install -r backend/requirements.txt

# 프론트엔드 설정
cd frontend
npm install

# 개발 서버 실행
python run_dev.py  # 백엔드(포트 8000)와 프론트엔드(포트 3000) 동시 시작
```

### Docker 명령어
```bash
# 이미지 빌드
docker build -t oc-proxy-downloader:latest .

# docker-compose로 실행
docker-compose up -d

# 단일 컨테이너 실행
docker run -d --name oc-proxy-downloader -p 8000:8000 -v ./backend/downloads:/app/backend/downloads oc-proxy-downloader:latest
```

### 백엔드 명령어
```bash
# 백엔드만 시작
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 데이터베이스 작업은 SQLAlchemy를 통해 자동 처리
```

### 프론트엔드 명령어
```bash
# 개발 서버
cd frontend
npm run dev

# 프로덕션 빌드
npm run build

# 프로덕션 빌드 미리보기
npm run preview
```