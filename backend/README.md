# OC Proxy Downloader - Backend

FastAPI 기반의 1fichier 다운로드 백엔드 서버입니다.

## 🚀 빠른 시작

### 1. 환경 설정

#### Python 가상환경 생성
```bash
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

#### 의존성 설치
```bash
pip install -r requirements.txt
```

### 2. 서버 실행

#### 개발 모드
```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

#### 프로덕션 모드
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

서버 실행 후 http://localhost:8000 에서 API 확인 가능합니다.

# Project Technical Overview: Claude Context (claude.md)

## 1. Project Summary
This is a modern web application featuring a high-performance backend built with FastAPI and a reactive, component-based frontend using Svelte. The entire architecture is designed around asynchronous principles to ensure scalability and efficiency.

## 2. Backend Technology Stack
The backend is built on Python with a strong emphasis on `asyncio` for non-blocking I/O operations.

- **Framework**: **FastAPI** is the core web framework. All API endpoints and business logic should leverage its `async`/`await` capabilities.
- **ASGI Server**: The application is served by **uvicorn**, a lightning-fast ASGI server.
- **Data Validation**: **Pydantic** is used extensively for data modeling, validation, and settings management. This is a core component of FastAPI.
- **Database ORM**: **SQLAlchemy 2.0+** is used for all database interactions, specifically utilizing its `asyncio` extension for non-blocking database queries.
- **Authentication**: Security is handled via **passlib** with **bcrypt** for password hashing and **PyJWT** for token-based authentication (JWTs).
- **Asynchronous HTTP Client**: **httpx** is the standard for making external API calls in a non-blocking manner.
- **General Principle**: The entire backend is built on an `asyncio` foundation. Avoid synchronous, blocking calls at all costs to maintain performance.

## 3. Frontend Technology Stack
- **Framework**: **Svelte** is used for the frontend. It's a modern JavaScript framework that compiles components to highly efficient imperative code.

## 4. Key Dependencies List
For context, the key libraries in use are:
- `fastapi`: Core framework
- `uvicorn`: ASGI server
- `sqlalchemy`: ORM (async mode)
- `pydantic`: Data validation
- `svelte`: Frontend framework
- `httpx`: Async HTTP client
- `passlib`, `bcrypt`, `pyjwt`: Security and authentication

## 📁 프로젝트 구조

```
backend/
├── main.py                 # FastAPI 애플리케이션 진입점
├── requirements.txt        # Python 의존성
├── config/                 # 설정 및 데이터베이스 디렉토리
│   ├── config.json        # 애플리케이션 설정 (자동 생성)
│   └── downloads.db       # SQLite 데이터베이스 (자동 생성)
├── core/                   # 핵심 로직 모듈
│   ├── config.py          # 설정 관리
│   ├── db.py              # 데이터베이스 연결
│   ├── models.py          # SQLAlchemy 모델
│   ├── downloader.py      # 다운로드 API 엔드포인트
│   ├── download_core.py   # 다운로드 핵심 로직
│   ├── parser_service.py  # 1fichier 파싱 서비스
│   ├── proxy_manager.py   # 프록시 관리
│   └── shared.py          # 공유 객체 (다운로드 매니저 등)
└── downloads/             # 다운로드 파일 저장소
```

## ⚙️ 설정

### 환경 변수

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `CONFIG_PATH` | `./backend` | 설정 파일 및 DB 저장 경로 |
| `DOWNLOAD_PATH` | `./backend/downloads` | 다운로드 파일 저장 경로 |

### config.json 설정

```json
{
  "download_path": "./downloads",
  "theme": "light",
  "language": "ko"
}
```

## 🔧 API 엔드포인트

### 다운로드 관리
- `POST /api/download/` - 다운로드 요청 생성
- `GET /api/history/` - 다운로드 히스토리 조회
- `DELETE /api/download/{id}` - 다운로드 취소/삭제

### 설정 관리
- `GET /api/settings` - 현재 설정 조회
- `POST /api/settings` - 설정 업데이트

### 프록시 관리
- `GET /api/proxies` - 프록시 목록 조회
- `POST /api/proxies/test` - 프록시 테스트
- `GET /api/proxy-stats` - 프록시 통계

### WebSocket
- `WS /ws` - 실시간 다운로드 상태 업데이트

## 🎯 주요 기능

### 다운로드 제한
- **전체 동시 다운로드**: 최대 5개
- **1fichier 로컬 다운로드**: 최대 2개
- **대기열 시스템**: 제한 도달 시 자동 대기 및 순차 실행

### 1fichier 파싱
- JavaScript 기반 카운트다운 감지
- 프리미엄/제한 상태 자동 감지
- 자동 재시도 로직

### 프록시 지원
- 자동 프록시 순환
- 실시간 프록시 상태 모니터링
- 실패한 프록시 자동 제외

## 🐛 디버깅

### 로그 확인
```bash
# 실시간 로그 모니터링
tail -f debug.log

# 특정 기능 로그 필터링
grep "1fichier" debug.log
grep "프록시" debug.log
```

### 일반적인 문제 해결

#### 포트 충돌
```bash
# 포트 사용 중인 프로세스 확인
netstat -ano | findstr :8000

# 프로세스 종료 (Windows)
taskkill /F /PID <PID>
```

#### 데이터베이스 초기화
```bash
# DB 파일 삭제 후 재시작
rm config/downloads.db
python main.py
```

## 📝 개발 가이드

### 새로운 파일 호스팅 지원 추가

1. `core/parser.py`에 새 파서 함수 추가
2. `core/parser_service.py`에 URL 패턴 매칭 로직 추가
3. `core/download_core.py`에 다운로드 로직 통합

### API 엔드포인트 추가

1. `core/` 디렉토리에 새 모듈 생성
2. `main.py`에 라우터 등록
3. 필요시 `core/models.py`에 데이터 모델 추가

## 🔒 보안 고려사항

- 파일 다운로드 경로 검증
- SQL 인젝션 방지 (SQLAlchemy ORM 사용)
- 민감한 정보 로깅 방지
- 프록시 연결 시 SSL 검증

## 📦 의존성

주요 라이브러리:
- `fastapi` - 웹 프레임워크
- `uvicorn` - ASGI 서버
- `sqlalchemy` - ORM
- `requests` - HTTP 클라이언트
- `cloudscraper` - CloudFlare 우회

전체 의존성은 `requirements.txt` 참조.