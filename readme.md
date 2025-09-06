![OC-Proxy]([https://raw.githubusercontent.com/your-username/your-repo/main/images/logo.png](https://raw.githubusercontent.com/jshsakura/oc-proxy-downloader/main/logo.png))

<div align="center">
  <img src="https://github.com/jshsakura/oc-proxy-downloader/blob/main/docs/preview/preview1.png?raw=true" alt="OC Proxy Downloader 미리보기" style="max-width: 700px; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.12); margin-bottom: 1rem;" />
  <img src="https://github.com/jshsakura/oc-proxy-downloader/blob/main/docs/preview/preview2.png?raw=true" alt="OC Proxy Downloader 미리보기" style="max-width: 700px; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.12); margin-bottom: 1rem;" />
  <br/>
  <b>OC Proxy Downloader</b>
  <p>1fichier 파일 다운로드를 위한 프록시 지원 웹 애플리케이션</p>
</div>

---

# OC Proxy Downloader

프록시를 활용한 1fichier 파일 다운로드 관리 시스템입니다. FastAPI 백엔드와 Svelte 프론트엔드로 구성되어 있으며, Docker를 통해 쉽게 배포할 수 있습니다.

## ✨ 주요 기능

- 🚀 **1fichier 다운로드**: JavaScript 카운트다운 자동 감지 및 처리
- 🔄 **프록시 순환**: 자동 프록시 관리 및 실패 시 순환
- 📊 **실시간 모니터링**: WebSocket 기반 실시간 상태 업데이트
- 🎯 **다운로드 제한**: 시스템 안정성을 위한 동시 다운로드 제한
- 🌙 **다크 테마**: 다크/라이트 테마 지원
- 🌐 **다국어**: 한국어/영어 지원
- 📱 **반응형**: 모바일/데스크톱 지원

---

## 🐳 Docker 배포 가이드

### 📦 Docker Hub에서 사전 빌드된 이미지 사용 (권장)

가장 빠르고 쉬운 방법입니다.

#### docker-compose.yml 사용

```bash
# docker-compose.yml 다운로드
curl -O https://raw.githubusercontent.com/jshsakura/oc-proxy-downloader/main/docker-compose.yml

# 이미지 pull 및 실행
docker-compose up -d
```

#### 단일 Docker 명령어

```bash
# 필요한 디렉토리 생성
mkdir -p downloads backend/config

# 컨테이너 실행
docker run -d \
  --name oc-proxy-downloader \
  -p 8000:8000 \
  -v ./downloads:/downloads \
  -v ./backend/config:/config \
  -e TZ=Asia/Seoul \
  -e PUID=1000 \
  -e PGID=1000 \
  --restart unless-stopped \
  your-dockerhub-id/oc-proxy-downloader:latest
```

### 🔧 환경 변수 설정

#### 기본 설정

| 변수명          | 기본값       | 설명                           | 필수 |
| --------------- | ------------ | ------------------------------ | ---- |
| `TZ`            | `UTC`        | 타임존 설정 (예: `Asia/Seoul`) | ❌   |
| `PUID`          | `1000`       | 사용자 ID (파일 권한용)        | ❌   |
| `PGID`          | `1000`       | 그룹 ID (파일 권한용)          | ❌   |
| `DOWNLOAD_PATH` | `/downloads` | 컨테이너 내 다운로드 경로      | ❌   |
| `CONFIG_PATH`   | `/config`    | 컨테이너 내 설정 경로          | ❌   |

#### 인증 설정 (선택사항)

| 변수명                | 기본값 | 설명                                    | 필수 |
| -------------------- | ------ | -------------------------------------- | ---- |
| `AUTH_USERNAME`      | -      | 로그인 사용자명 (미설정 시 인증 비활성화) | ❌   |
| `AUTH_PASSWORD`      | -      | 로그인 비밀번호                          | ❌   |
| `JWT_SECRET_KEY`     | -      | JWT 토큰 암호화 키 (자동 생성)            | ❌   |
| `JWT_EXPIRATION_HOURS` | `24` | JWT 토큰 만료 시간(시간)                 | ❌   |

> **참고**: `AUTH_USERNAME`과 `AUTH_PASSWORD`를 설정하지 않으면 인증 없이 접근할 수 있습니다. 
> 보안이 필요한 환경에서는 반드시 설정하세요. 로그인 실패 5회 시 50- IP가 차단됩니다.

#### 시스템 최적화 설정

| 변수명                     | 기본값    | 설명                                   | 필수 |
| -------------------------- | --------- | -------------------------------------- | ---- |
| `LOG_LEVEL`                | `WARNING` | 로그 출력 레벨                         | ❌   |
| `PARENT_CHECK_INTERVAL`    | `5`       | 부모 프로세스 체크 간격(초) - CPU 최적화 | ❌   |
| `MAX_WEBSOCKET_CONNECTIONS`| `10`      | WebSocket 최대 연결 수 (비정상 접근 차단용) | ❌   |
| `MAX_TOTAL_DOWNLOADS`      | `5`       | 최대 동시 다운로드 수                   | ❌   |

#### 📊 로그 레벨 설명

| 레벨      | 출력 내용                    | 사용 시기              |
| --------- | ---------------------------- | ---------------------- |
| `DEBUG`   | 모든 로그 (상세한 디버그 정보) | 개발, 문제 진단       |
| `INFO`    | 일반 정보 이상               | 테스트 환경           |
| `WARNING` | 경고 이상만 (기본값)         | **운영 환경 권장**    |
| `ERROR`   | 오류만                       | 최소 로그가 필요한 경우 |

#### 💡 WebSocket 연결 제한이 필요한 이유

일반적으로 사용자당 **브라우저 탭 1~2개**만 연결되지만:
- **비정상적 접근 차단**: 봇이나 악의적 스크립트 방지
- **메모리 보호**: 무제한 연결로 인한 시스템 부하 방지
- **기본 10개 제한**: 정상 사용에는 충분하며, 필요시 조정 가능

### 📁 볼륨 매핑 가이드

#### 필수 볼륨

```yaml
volumes:
  # 다운로드 파일 저장소 (필수)
  - ./downloads:/downloads

  # 설정 및 데이터베이스 (권장)
  - ./backend/config:/config
```

#### 권한 설정 (Linux/macOS)

```bash
# 디렉토리 생성 및 권한 설정
mkdir -p downloads backend/config
chown -R 1000:1000 downloads backend/config
chmod -R 755 downloads backend/config
```

#### Windows에서의 권한 설정

```powershell
# PowerShell에서 디렉토리 생성
New-Item -ItemType Directory -Path "downloads" -Force
New-Item -ItemType Directory -Path "backend\config" -Force
```

### 🏗️ 커스텀 Docker Compose 설정

#### 기본 설정 (docker-compose.yml)

```yaml
version: "3.8"
services:
  oc-proxy-downloader:
    image: your-dockerhub-id/oc-proxy-downloader:latest
    container_name: oc-proxy-downloader
    environment:
      - TZ=Asia/Seoul
      - PUID=1000
      - PGID=1000
      - DOWNLOAD_PATH=/downloads
      - CONFIG_PATH=/config
      # 시스템 최적화 설정
      - LOG_LEVEL=WARNING                     # 로그 레벨: DEBUG, INFO, WARNING, ERROR (기본: WARNING)
      - PARENT_CHECK_INTERVAL=5               # 부모 프로세스 체크 간격(초) - CPU 최적화
      - MAX_WEBSOCKET_CONNECTIONS=10          # WebSocket 최대 연결 수 (비정상 접근 차단용)
      - MAX_TOTAL_DOWNLOADS=5                 # 최대 동시 다운로드 수
    volumes:
      - ./downloads:/downloads
      - ./backend/config:/config
    ports:
      - "8000:8000"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/settings"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

#### 고급 설정 (docker-compose.override.yml)

```yaml
version: "3.8"
services:
  oc-proxy-downloader:
    environment:
      # 사용자 정의 환경 변수
      - CUSTOM_CONFIG=value
    volumes:
      # 추가 볼륨 매핑
      - ./logs:/logs
      - ./custom-config.json:/config/config.json
    networks:
      - proxy-network
    labels:
      # Traefik 라벨 (리버스 프록시용)
      - "traefik.enable=true"
      - "traefik.http.routers.downloader.rule=Host(`downloader.example.com`)"

networks:
  proxy-network:
    external: true
```

### 🔧 로컬에서 직접 빌드하여 실행

소스코드를 수정했거나 최신 개발 버전을 사용하려는 경우:

#### 1. 저장소 클론

```bash
git clone https://github.com/jshsakura/oc-proxy-downloader.git
cd oc-proxy-downloader
```

#### 2. Docker Compose로 빌드 및 실행

```bash
# 빌드 및 실행
docker-compose up -d --build

# 로그 확인
docker-compose logs -f

# 중지
docker-compose down
```

#### 3. 수동 Docker 빌드

```bash
# 이미지 빌드
docker build -t oc-proxy-downloader:local .

# 컨테이너 실행
docker run -d \
  --name oc-proxy-downloader \
  -p 8000:8000 \
  -v ./downloads:/downloads \
  -v ./backend/config:/config \
  oc-proxy-downloader:local
```

### 🌍 멀티플랫폼 빌드 (개발자용)

AMD64, ARM64 등 다양한 아키텍처 지원:

#### Linux/macOS

```bash
chmod +x build-multiplatform.sh
./build-multiplatform.sh
```

#### Windows

```powershell
.\build-multiplatform.ps1
```

### 🔧 문제 해결

#### 컨테이너가 시작되지 않는 경우

```bash
# 로그 확인
docker-compose logs oc-proxy-downloader

# 컨테이너 상태 확인
docker ps -a
```

#### 포트 충돌

```bash
# 다른 포트 사용
docker-compose up -d -p 8080:8000
```

#### 볼륨 권한 문제

```bash
# 권한 수정 (Linux/macOS)
sudo chown -R $USER:$USER downloads backend/config

# SELinux 환경에서
sudo setsebool -P container_manage_cgroup on
```

#### 캐시 문제로 인한 빌드 실패

```bash
# 캐시 없이 재빌드
docker-compose build --no-cache

# 시스템 정리
docker system prune -af
```

### 📊 모니터링 및 관리

#### 컨테이너 상태 확인

```bash
# 실행 중인 컨테이너 확인
docker ps

# 리소스 사용량 확인
docker stats oc-proxy-downloader

# 헬스체크 확인
docker inspect oc-proxy-downloader | grep Health -A 10

# WebSocket 연결 통계 확인
curl http://localhost:8000/api/websocket/stats
```

#### 로그 관리

```bash
# 실시간 로그
docker-compose logs -f

# 로그 크기 제한
docker-compose logs --tail=100

# 특정 시간 이후 로그
docker-compose logs --since="2023-01-01T10:00:00"
```

---

## 💾 Windows Standalone 버전

Windows 사용자를 위한 단일 실행 파일 버전:

```bash
cd standalone
.\build.bat     # EXE 빌드
.\test.bat      # 테스트 실행
```

자세한 내용은 [Standalone README](./standalone/README.md)를 참조하세요.

---

## 🛠️ 개발 환경에서 실행하기

Docker 없이 로컬 환경에서 개발하는 경우:

### 📋 요구사항

- Python 3.8+
- Node.js 16+
- npm 또는 yarn

### 🔧 백엔드 설정

```bash
cd backend
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
python main.py
```

### 🎨 프론트엔드 설정

```bash
cd frontend
npm install
npm run dev
```

자세한 설정은 각각의 README를 참조하세요:

- [백엔드 README](./backend/README.md)
- [프론트엔드 README](./frontend/README.md)

---

## 📞 지원 및 문의

- 📋 **이슈 보고**: [GitHub Issues](https://github.com/jshsakura/oc-proxy-downloader/issues)
- 💬 **토론**: [GitHub Discussions](https://github.com/jshsakura/oc-proxy-downloader/discussions)
- 📖 **문서**: 각 폴더의 README 파일 참조

## 📄 라이선스

이 프로젝트는 MIT 라이선스 하에 배포됩니다. 자세한 내용은 [LICENSE](LICENSE) 파일을 참조하세요.

## 🤝 기여하기

기여를 환영합니다! Pull Request를 보내기 전에:

1. 이슈를 먼저 확인해주세요
2. 코드 스타일을 유지해주세요
3. 테스트를 실행해주세요

---

**⭐ 이 프로젝트가 도움이 되셨다면 Star를 눌러주세요!**
