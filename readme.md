# 🚀 OC Proxy Downloader

![Project Banner](https://raw.githubusercontent.com/jshsakura/oc-proxy-downloader/main/docs/banner.png)

**프록시 기반 1fichier 다운로드 관리 시스템**

FastAPI + Svelte로 구성된 현대적인 웹 애플리케이션으로, 프록시를 통한 안정적인 파일 다운로드를 지원합니다.

## ✨ 주요 기능

- 🚀 **1fichier 최적화**: 자동 대기시간 감지 및 쿨다운 관리 (최대 24시간 대기)
- 🔄 **스마트 프록시**: 자동 순환, 실패 감지, 로컬/프록시 혼합 다운로드
- 📊 **실시간 모니터링**: SSE 기반 실시간 상태 업데이트 및 진행률 표시
- 🎯 **동시 다운로드 제한**: 시스템 안정성을 위한 세마포어 기반 제한
- 📱 **텔레그램 알림**: 다운로드 완료/실패 알림 지원
- 🌙 **테마 지원**: 다크/라이트/드라큘라 테마
- 🌐 **다국어**: 한국어/영어 완전 지원
- 📱 **반응형 UI**: 모바일/데스크톱 최적화
- 🛡️ **선택적 인증**: JWT 기반 보안 (선택사항)

---

<div align="center">
  <img src="https://github.com/jshsakura/oc-proxy-downloader/blob/main/docs/preview/preview1.png?raw=true" alt="OC Proxy Downloader" style="max-width: 700px; border-radius: 12px; margin-bottom: 1rem;" />
  <br/>
  <a href="https://www.opencourse.kr/1fichier-oc-proxy-downloader/">📚 자세한 설치 가이드</a>
</div>

---

## 🛠️ 기술 스택

### Backend
- **FastAPI**: 고성능 비동기 웹 프레임워크
- **SQLAlchemy**: ORM 및 데이터베이스 관리
- **PostgreSQL**: 메인 데이터베이스
- **aiohttp**: 비동기 HTTP 클라이언트 (다운로드/프록시)
- **SSE**: Server-Sent Events로 실시간 통신

### Frontend
- **Svelte**: 컴파일 기반 반응형 프레임워크
- **Vite**: 빠른 개발 서버 및 빌드 도구
- **SSE**: 실시간 상태 업데이트 수신

### Infrastructure
- **Docker**: 컨테이너화 배포
- **Docker Compose**: 개발/운영 환경 관리

## 🚀 설치 방법

### 🐳 Docker Compose 설치 (권장)

```bash
# 1. 프로젝트 다운로드
curl -O https://raw.githubusercontent.com/jshsakura/oc-proxy-downloader/main/docker-compose.yml

# 2. 디렉토리 생성
mkdir -p downloads backend/config

# 3. 실행
docker-compose up -d
```

### 🪟 Windows 실행 파일

Windows 사용자를 위한 독립 실행 파일을 제공합니다:

1. **[Releases](https://github.com/jshsakura/oc-proxy-downloader/releases)** 페이지에서 최신 Windows 버전 다운로드
2. `oc-proxy-downloader-windows.exe` 실행
3. **http://localhost:8000** 접속하여 사용

> **참고**: Windows 버전은 모든 기능을 포함한 독립 실행 파일입니다. Docker 설치가 불필요합니다.

### 🔧 Docker Compose 설정 예시

#### 일반 Linux 환경

```yaml
# docker-compose.yml
version: "3.8"
services:
  oc-proxy-downloader:
    image: jshsakura/oc-proxy-downloader:latest
    container_name: oc-proxy-downloader
    environment:
      - TZ=Asia/Seoul
      - PUID=1000
      - PGID=1000
      # 보안 (선택사항)
      # - AUTH_USERNAME=admin
      # - AUTH_PASSWORD=secure123
      # - JWT_SECRET_KEY=your-random-secret-key
    volumes:
      - ./downloads:/downloads
      - ./backend/config:/config
    ports:
      - "8000:8000"
    restart: unless-stopped
```

#### 시놀로지 NAS 환경

```yaml
# docker-compose.yml (Synology)
version: "3.8"
services:
  oc-proxy-downloader:
    image: jshsakura/oc-proxy-downloader:latest
    container_name: oc-proxy-downloader
    environment:
      - TZ=Asia/Seoul
      - PUID=1026    # 시놀로지 사용자 ID (id 명령어로 확인)
      - PGID=100     # 시놀로지 users 그룹 ID
      # 보안 (선택사항)
      # - AUTH_USERNAME=admin
      # - AUTH_PASSWORD=secure123
      # - JWT_SECRET_KEY=your-random-secret-key
    volumes:
      - /volume1/docker/oc-proxy/downloads:/downloads
      - /volume1/docker/oc-proxy/config:/config
    ports:
      - "8000:8000"
    restart: unless-stopped
```

> **시놀로지 사용자 참고**: SSH로 접속 후 `id` 명령어로 본인의 PUID 확인 필요

## ⚙️ 환경 변수

### 기본 설정
| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `TZ` | `UTC` | 시스템 타임존 설정 |
| `PUID` | `1000` | 파일 소유자 ID (권한 관리) |
| `PGID` | `1000` | 파일 그룹 ID (권한 관리) |

### 보안 설정 (선택사항)
| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `AUTH_USERNAME` | - | 웹 로그인 ID (미설정 시 인증 없음) |
| `AUTH_PASSWORD` | - | 웹 로그인 비밀번호 |
| `JWT_SECRET_KEY` | 기본값 | JWT 토큰 암호화 키 (운영 환경에서 필수 변경) |

> **⚠️ 보안 주의**: 운영 환경에서는 반드시 `JWT_SECRET_KEY`를 안전한 랜덤 문자열로 설정하세요.

### 고급 설정 (선택사항)
| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `MAX_TOTAL_DOWNLOADS` | `5` | 전체 최대 동시 다운로드 |
| `MAX_LOCAL_DOWNLOADS` | `1` | 1fichier 로컬 최대 동시 다운로드 |

## 📁 디렉토리 구조

```
oc-proxy-downloader/
├── downloads/           # 다운로드된 파일 저장소
├── backend/config/      # 설정 파일 및 데이터베이스
│   ├── app.db          # SQLite 데이터베이스
│   ├── config.json     # 앱 설정 파일
│   └── proxies.txt     # 프록시 목록
└── docker-compose.yml  # Docker Compose 설정
```

## 🚀 사용법

1. **http://localhost:8000** 접속
2. **설정** → **프록시 관리**에서 프록시 추가
3. **1fichier URL** 입력 후 다운로드 시작
4. **실시간 진행률** 및 **프록시 상태** 모니터링

## 🔧 개발 환경

```bash
# 저장소 클론
git clone https://github.com/jshsakura/oc-proxy-downloader.git
cd oc-proxy-downloader

# 개발 환경 실행
docker-compose -f docker-compose.dev.yml up -d --build

# 로그 확인
docker-compose logs -f
```

### 백엔드 개발
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### 프론트엔드 개발
```bash
cd frontend
npm install
npm run dev
```

## 📊 모니터링

```bash
# 컨테이너 상태 확인
docker ps

# 리소스 사용량 확인
docker stats oc-proxy-downloader

# 실시간 로그
docker-compose logs -f

# 헬스체크 확인
curl http://localhost:8000/api/settings
```

## 🆘 문제 해결

### 컨테이너 시작 실패
```bash
# 로그 확인
docker-compose logs oc-proxy-downloader

# 권한 문제 (Linux/macOS)
sudo chown -R 1000:1000 downloads backend/config
```

### 포트 충돌
```bash
# 다른 포트 사용 (예: 8080)
docker-compose up -d -p 8080:8000
```

### 캐시 문제
```bash
# 캐시 없이 재빌드
docker-compose build --no-cache
docker-compose up -d
```

## 📞 지원

- 📋 **이슈 보고**: [GitHub Issues](https://github.com/jshsakura/oc-proxy-downloader/issues)
- 💬 **토론**: [GitHub Discussions](https://github.com/jshsakura/oc-proxy-downloader/discussions)
- 📖 **상세 가이드**: [설치 가이드](https://www.opencourse.kr/1fichier-oc-proxy-downloader/)

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

---

**⭐ 이 프로젝트가 도움이 되셨다면 Star를 눌러주세요!**