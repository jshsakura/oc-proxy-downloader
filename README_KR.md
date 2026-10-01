# 🚀 OC Proxy Downloader

![Project Banner](https://raw.githubusercontent.com/jshsakura/oc-proxy-downloader/main/docs/banner.png)

**1fichier · MEGA · 파일 호스팅 사이트 다운로드 관리자 — 프록시 기반, Docker 컨테이너 / Windows 앱으로 실행**

FastAPI + Svelte 웹 앱으로, 파일 호스팅 링크를 해석해 다운로드 대기열에 넣고 상태를 보여줍니다.

## ✨ 주요 기능

- 🚀 **1fichier 최적화**: 자동 대기시간 감지 및 쿨다운 관리 (최대 24시간 대기), 한도 복구 시각 카운트다운 표시
- 🔐 **MEGA 지원**: 공개 링크 다운로드 + 클라이언트 측 AES 복호화 (파일명/크기/진행률)
- 🧩 **호스트별 링크 해석**: DataNodes, MegaUp, MediaFire, Pixeldrain, Bunkr, AkiraBox, VikingFile, Rootz 등 (제약은 아래 표 참고)
- 🔄 **스마트 프록시**: 자동 순환, 실패 감지, 로컬/프록시 혼합 다운로드
- 📊 **실시간 모니터링**: SSE 기반 실시간 상태 업데이트 및 진행률 표시
- 🎯 **동시 다운로드 제한**: 전체 기본 8개·호스트별 검증 한도, 1fichier 무료 회선당 1개
- 📱 **텔레그램 알림**: 다운로드 완료/실패 알림 지원
- 🌙 **테마 지원**: 11개 테마(라이트·다크·드라큘라·노드·솔라라이즈드·모노카이·오션·로즈·네온·포레스트·선셋)와 시스템 설정 따라가기
- 🏷️ **실패를 할 일 기준으로 표시**: 파일 없음, 사람 확인 필요, 대기 필요, 호스트 거부로 나뉘어 보입니다 (아래 참고)
- 🌐 **다국어**: 18개 언어 지원 (한국어·영어·일본어·중국어 간체/번체·스페인어·프랑스어·독일어·러시아어·포르투갈어(BR)·이탈리아어·베트남어·인도네시아어·태국어·터키어·폴란드어·아랍어(RTL)·네덜란드어). 언어 파일(`backend/locales/*.json`)만 추가하면 자동 인식
- 📱 **반응형 UI**: 모바일/데스크톱 최적화
- 🛡️ **선택적 인증**: JWT 기반 보안 (선택사항)

## 🐳 실행 환경 (Docker 전제)

**이 프로젝트는 Docker 환경을 전제로 만들어졌습니다.** 일부 호스터는 사이트에 박힌
Cloudflare Turnstile 캡차를 통과해야 하는데, 여기엔 **실제 브라우저**가 필요합니다.
헤드리스로는 토큰이 발급되지 않아 가상 디스플레이(Xvfb) 위에서 Chromium을 띄워야 하고,
그 둘은 **Docker 이미지에만 포함**되어 있습니다.

`docker compose` 로 실행하면 **FlareSolverr까지 같이 뜹니다.** 별도 설치나 주소 설정이
필요 없고, 앱이 서비스 이름(`http://flaresolverr:8191`)으로 자동 연결합니다.

```bash
docker compose up -d      # 앱 + FlareSolverr 동시 기동
```

> TrueNAS/Synology 앱처럼 컨테이너를 **따로** 설치하는 경우에는 서비스 이름 DNS가 통하지
> 않습니다. **설정 → FlareSolverr URL** 에 `http://<호스트 IP>:<공개 포트>` 형식으로
> 직접 넣어주세요.

Windows 실행 파일은 **단일 파일 유지를 위해 브라우저를 번들하지 않습니다.** 아래 표에서
❌ 인 호스터는 Windows 버전에서 지원되지 않으며, 링크를 추가하면 즉시 안내 메시지가 뜹니다.

## 🌩️ 호스트별 지원

호스트별 파싱·실패·재시도 범위는 [호스트 케이스 표](docs/HOSTER_CASES.md)에 정리했다.

| 호스트 | 필요한 것 | Windows 앱 |
|--------|-----------|------------|
| 1fichier, MEGA | 없음 | ✅ 됨 |
| Pixeldrain | 없음 (공개 API) | ✅ 됨 |
| GoFile | 사이트의 무료 웹 세션; 등록·API 키 불필요 | 자체 브라우저가 필요한 현재 경로는 Docker 전용 |
| MediaFire | Cloudflare 챌린지 때 FlareSolverr | 🟡 챌린지 안 뜨면 됨 |
| MegaUp | FlareSolverr (항상) | ❌ 외부 FlareSolverr 필요 |
| Bunkr | Cloudflare 챌린지 때 FlareSolverr | 🟡 암호화 CDN 링크는 해석 못 할 수 있음 |
| **DataNodes** | **브라우저 (Turnstile 캡차)** | ❌ **Docker 전용** |
| Send.now / Send.cm | 실제 다운로드 폼과 정상 브라우저 세션 | 현재 경로는 Docker 전용 |
| **AkiraBox** (`akirabox.com`, `akirabox.to`) | **브라우저에서 유효기간 있는 다운로드 주소 발급** | ❌ **Docker 전용** |
| **VikingFile** (`vikingfile.com`, `vik1ngfile.site`) | **브라우저와 Turnstile 캡차** | ❌ **Docker 전용** |
| **Rootz** (`rootz.so`) | **브라우저에서 파일 정보와 다운로드 주소 확인** | ❌ **Docker 전용** |
| DataVaults | 실제 무료 폼을 단계별로 한 번씩 처리 | 검증을 요구하는 파일은 사람 확인에서 중단; 호스트 전체 차단 없음 |
| FileCrypt / Linkcuy | 공개 링크 추출 또는 사이트 브라우저 절차 | FileCrypt PoW 최대 900초 단회; 실미러 추출/파일 완료는 별도 검증 |
| MomeryBox / TeraBox | 공개 이동 주소 확인 | 로그인 요구 시 자동 반복 없이 중단 |

브라우저가 필요한 링크 해석은 **사이트별로 한 번에 하나씩** 처리됩니다. 차례를 기다리는
동안에는 실패 재시도 횟수가 소모되지 않습니다. AkiraBox·VikingFile·Rootz는 다운로드
차례가 왔을 때 주소를 한 번 발급하며, 주소 발급에 실패해도 자동으로 여러 프록시를 돌며
반복 파싱하지 않습니다. 현 회선에서 서로 다른 파일의 실제 동시 완료를 확인한 GoFile·VikingFile은 최대 3개,
1fichier·Rootz·AkiraBox·MegaUp 등 나머지와 미검증 호스트는 보수적으로 1개입니다.
전체 기본 한도는 8개이며 설정의 호스트당 3개는 상한입니다. 별칭 도메인은 같은 한도를 공유합니다.
메타데이터부터 전송 종료까지 호스트 슬롯을 유지합니다. 429는 최소 30분과 서버 대기시간을 반영하고,
명시적인 한 파일 제한은 한도를 1개로 저장합니다. 파싱·캡차·차단은 자동 반복하지 않으며,
일시적인 전송 장애도 즉시 재요청하지 않고 최소 30분 이후 한 번만 자동 재시도합니다.
확인된 제한과 대기시간은 저장되어 서버 재시작이나 개별 다운로드 재시도로 초기화되지 않습니다.

> Turnstile과 무료 다운로드 제한은 호스트와 접속 회선에 따라 달라집니다. 링크 해석에
> 성공해도 파일 서버가 실제 전송을 거부할 수 있습니다.

AkiraBox는 `*.akirabox.xyz`와 `*.akirabox.com` 아래 지역 노드 등 여러 저장 노드에서 파일을
내줍니다. 일부 파일은 서명된 주소를 발급해도 해당 노드가 `The link is not available at
this time.`으로 거부합니다. 이 경우 다운로드는 멈추고 파일 서버 문제로 표시하며,
Cloudflare 차단으로 오인하거나 자동 재시도하지 않습니다. 다른 노드의 파일은 정상 제공될
수 있으므로 다른 미러 또는 파일 복구를 확인하세요.

### 실패 표시

실패한 줄은 사용자가 할 수 있는 일을 기준으로 이름이 붙고, 앱이 원인을 설명하지 못하는
실패만 빨간색으로 남습니다. 자세한 사유와 다음 행동은 상세 창에서 볼 수 있습니다.

| 표시 | 의미 | 할 일 |
|------|------|-------|
| **파일 없음** (갈색) | 호스트가 파일이 없다고 응답했거나 링크가 죽음 | 다른 미러를 사용하세요. 링크는 자동으로 지우지 않고 남깁니다 |
| **사람 확인 필요** (주황) | 캡차·로그인·사람 확인이 필요함 | 사이트에서 확인을 마치거나 다른 미러를 사용하세요 |
| **대기 필요** (라임) | 무료 슬롯 혼잡, 요청 제한, 일일 한도 | 나중에 다시 받으세요. 1fichier 슬롯이 혼잡하면 그 대기열의 나머지가 멈춥니다 |
| **호스트 거부** (청록) | 호스트나 저장 서버가 전송을 거부함 | 다른 미러를 사용하거나 호스트가 복구된 뒤 다시 받으세요 |
| **실패** (빨강) | 앱이 원인을 분류하지 못함 | 로그를 확인하세요 |

호스트가 혼잡해서 멈춘 대기열은 실패가 아니라 **정지됨**으로 표시되며, 줄에서 다시 시작할 수
있습니다.

![실패 상세](https://github.com/jshsakura/oc-proxy-downloader/blob/main/docs/preview/preview2.png?raw=true)

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
- **SQLite**: 다운로드 이력 및 설정 데이터베이스
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
docker compose up -d
```

### 🪟 Windows 실행 파일

Windows 사용자를 위한 독립 실행 파일을 제공합니다:

1. **[Releases](https://github.com/jshsakura/oc-proxy-downloader/releases)** 페이지에서 최신 Windows 버전 다운로드
2. `oc-proxy-downloader-windows.exe` 실행
3. **http://localhost:8000** 접속하여 사용

> **참고**: Windows 버전은 Docker 없이 실행되지만 Chromium·Xvfb가 없어 위 표의 Docker 전용 호스트는 사용할 수 없습니다.

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
| `TZ` | `Asia/Seoul` (Docker 이미지) | 시스템 타임존 설정 |
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
| `API_TOKEN` | 자동 생성 가능 | 서버 간 `/api/*` 호출용 토큰 (`X-API-Key`) |
| `FLARESOLVERR_URL` | `http://flaresolverr:8191` (Compose) | FlareSolverr 주소 |

동시 다운로드 수는 환경 변수 대신 `/config/config.json`의 `max_concurrent_downloads`(기본 8),
`max_per_host_downloads`(기본 3) 또는 웹 설정에서 조정합니다.

## 📁 디렉토리 구조

```
oc-proxy-downloader/
├── downloads/           # 다운로드된 파일 저장소
├── backend/config/      # 설정 파일 및 데이터베이스
│   ├── downloads.db    # SQLite 데이터베이스
│   └── config.json     # 앱 설정 파일
└── docker-compose.yml  # Docker Compose 설정
```

## 🚀 사용법

1. **http://localhost:8000** 접속
2. 프록시가 필요한 경우 **설정** → **프록시 관리**에서 추가
3. 지원 호스트의 URL을 입력하고 다운로드 시작
4. **실시간 진행률** 및 **프록시 상태** 모니터링

## 🔧 개발 환경

```bash
# 저장소 클론
git clone https://github.com/jshsakura/oc-proxy-downloader.git
cd oc-proxy-downloader

# 개발 환경 실행
docker compose up -d --build

# 로그 확인
docker compose logs -f
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
docker compose logs -f

# 헬스체크 확인
curl http://localhost:8000/api/auth/status
```

## 🆘 문제 해결

### 컨테이너 시작 실패
```bash
# 로그 확인
docker compose logs oc-proxy-downloader

# 권한 문제 (Linux/macOS)
sudo chown -R 1000:1000 downloads backend/config
```

### 포트 충돌
```bash
# Compose 파일의 ports를 "8080:8000"으로 수정한 뒤 재기동
docker compose up -d
```

### 캐시 문제
```bash
# 캐시 없이 재빌드
docker compose build --no-cache
docker compose up -d
```

## 📞 지원

- 📋 **이슈 보고**: [GitHub Issues](https://github.com/jshsakura/oc-proxy-downloader/issues)
- 💬 **토론**: [GitHub Discussions](https://github.com/jshsakura/oc-proxy-downloader/discussions)
- 📖 **상세 가이드**: [설치 가이드](https://www.opencourse.kr/1fichier-oc-proxy-downloader/)

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다.

---

**⭐ 이 프로젝트가 도움이 되셨다면 Star를 눌러주세요!**

컨테이너에서 단일 파일 링크를 얻으면 원본 URL을 보존하고 실제 파일 호스트의 슬롯으로 넘깁니다.
여러 파일/파트/미러는 자동 일괄 실행하지 않고 개별 링크 선택을 요구합니다. HTML·JSON 오류 페이지,
없는 파일·빈 파일·크기 불일치는 완료 처리하지 않습니다. 단발 삭제 표식·404·비활성 API 응답은
삭제 확정 근거가 아니며 수집 링크를 숨기거나 삭제하지 않습니다.
