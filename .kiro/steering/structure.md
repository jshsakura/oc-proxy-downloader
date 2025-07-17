# 프로젝트 구조

## 루트 레벨
```
├── backend/           # FastAPI 백엔드 애플리케이션
├── frontend/          # Svelte 프론트엔드 애플리케이션
├── docs/             # 문서 및 미리보기 이미지
├── venv/             # Python 가상환경
├── docker-compose.yml # Docker 오케스트레이션
├── Dockerfile        # 멀티 스테이지 Docker 빌드
├── run_dev.py        # 개발 서버 런처
└── readme.md         # 프로젝트 문서
```

## 백엔드 구조 (`backend/`)
```
backend/
├── core/             # 핵심 애플리케이션 모듈
│   ├── config.py     # 설정 관리
│   ├── models.py     # SQLAlchemy 데이터베이스 모델
│   ├── db.py         # 데이터베이스 연결 및 세션
│   ├── common.py     # 공유 유틸리티 (프록시 관리)
│   └── i18n.py       # 국제화 지원
├── locales/          # 번역 파일 (JSON)
├── downloads/        # 기본 다운로드 디렉토리
├── main.py           # FastAPI 애플리케이션 진입점
├── config.json       # 애플리케이션 설정
├── requirements.txt  # Python 의존성
└── downloads.db      # SQLite 데이터베이스 파일
```

## 프론트엔드 구조 (`frontend/`)
```
frontend/
├── src/              # Svelte 소스 코드
├── public/           # 정적 자산
├── dist/             # 프로덕션 빌드 출력
├── node_modules/     # npm 의존성
├── package.json      # npm 설정
├── vite.config.js    # Vite 빌드 설정
├── svelte.config.js  # Svelte 컴파일러 설정
└── index.html        # HTML 진입점
```

## 주요 아키텍처 패턴

### 백엔드 패턴
- **API 라우터 패턴**: FastAPI의 APIRouter를 사용하여 모든 엔드포인트에 `/api` 접두사 적용
- **의존성 주입**: `Depends(get_db)`를 통한 데이터베이스 세션 주입
- **백그라운드 작업**: multiprocessing을 통한 별도 프로세스에서 다운로드 작업 실행
- **WebSocket 통신**: `/ws/status` 엔드포인트를 통한 실시간 상태 업데이트
- **정적 파일 서빙**: SPA 폴백과 함께 루트 경로에서 프론트엔드 dist 파일 제공

### 데이터베이스 스키마
- **단일 테이블**: URL, 상태, 파일 정보, 진행률 추적을 위한 컬럼이 있는 `download_requests`
- **상태 전환**: pending → proxying → downloading → done/failed/paused
- **진행률 추적**: 진행률 계산을 위한 `downloaded_size`와 `total_size`

### 설정 관리
- **JSON 설정**: 영구 설정을 위한 `backend/config.json`
- **환경 변수**: Docker용 `DOWNLOAD_PATH`, `PUID`, `PGID`, `TZ`
- **경로 해석**: 다운로드 디렉토리 자동 생성

### 파일 구성 규칙
- 백엔드 로직은 `backend/core/` 모듈에 보관
- 데이터베이스 모델은 `core/models.py`에
- 설정 유틸리티는 `core/config.py`에
- 공유 유틸리티는 `core/common.py`에
- 번역 파일은 `backend/locales/`에
- 프론트엔드 컴포넌트는 `frontend/src/`에
- 정적 자산은 `frontend/public/`에

### 1fichier 파싱 시스템
- **유연한 파싱**: 사이트 구조 변경에 대응하는 다중 선택자 방식
- **폴백 메커니즘**: 여러 XPath 및 CSS 선택자를 순차적으로 시도
- **에러 핸들링**: 파싱 실패 시 상세한 로그 및 재시도 로직