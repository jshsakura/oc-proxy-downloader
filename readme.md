<div align="center">
  <img src="https://github.com/jshsakura/oc-proxy-downloader/blob/main/docs/preview/preview1.png?raw=true" alt="OC Proxy Downloader 미리보기" style="max-width: 700px; border-radius: 12px; box-shadow: 0 4px 24px rgba(0,0,0,0.12); margin-bottom: 1rem;" />
  <br/>
  <b>OC Proxy Downloader 미리보기</b>
</div>

---

### 가상 환경 생성

python -m venv venv

### 가상 환경 활성화 (Windows)

.\venv\Scripts\activate

### 가상 환경 활성화 (macOS/Linux)

source venv/bin/activate

pip freeze > requirements.txt

pip install "fastapi[all]"
pip install requests

npx https://github.com/google-gemini/gemini-cli

---

## 🐳 Docker로 배포 및 실행하기

### 1. docker-compose로 실행 (권장)

프로젝트 루트에 제공된 `docker-compose.yml` 파일을 사용하여 실행:

```bash
# 이미지 빌드 및 실행
docker-compose up -d --build

# 로그 확인
docker-compose logs -f

# 중지
docker-compose down
```

### 2. 이미지 빌드만 하기

**단일 플랫폼 빌드:**
```bash
docker build -t oc-proxy-downloader:latest .
```

**Multi-platform 빌드 (x86 + ARM):**
```bash
# Linux/macOS
./build-multiplatform.sh [tag]

# Windows
.\build-multiplatform.ps1 [tag]
```

**수동 multi-platform 빌드:**
```bash
# Buildx 설정
docker buildx create --name multiplatform --use --bootstrap

# Multi-platform 빌드
docker buildx build --platform linux/amd64,linux/arm64 -t oc-proxy-downloader:latest --load .
```

### 3. 도커허브 배포 (선택사항)

```bash
# 태그 변경
docker tag oc-proxy-downloader:latest <YOUR_DOCKERHUB_ID>/oc-proxy-downloader:latest

# 푸시
docker login
docker push <YOUR_DOCKERHUB_ID>/oc-proxy-downloader:latest
```

### 4. 커스텀 docker-compose 설정

기본 `docker-compose.yml`을 복사하여 필요에 맞게 수정:

```yaml
version: '3.8'
services:
  oc-proxy-downloader:
    build: .  # 로컬 빌드
    # image: <YOUR_DOCKERHUB_ID>/oc-proxy-downloader:latest  # 이미지 사용시
    container_name: oc-proxy-downloader
    environment:
      - TZ=Asia/Seoul
      - PUID=1000
      - PGID=1000
    volumes:
      - ./downloads:/app/backend/downloads  # 다운로드 저장 경로
      - ./backend/config.json:/app/backend/config.json  # 설정 파일 (선택)
      - ./backend/database.db:/app/backend/database.db  # DB 파일 (선택)
    ports:
      - "8000:8000"
    restart: unless-stopped
```

### 5. 단일 docker run 예시

```bash
# 로컬 빌드된 이미지 사용
docker run -d \
  --name oc-proxy-downloader \
  -e TZ=Asia/Seoul \
  -e PUID=1000 \
  -e PGID=1000 \
  -v $(pwd)/downloads:/app/backend/downloads \
  -p 8000:8000 \
  oc-proxy-downloader:latest
```

### 6. 환경 변수 설명

- **TZ**: 타임존 설정 (기본: Asia/Seoul)
- **PUID/PGID**: 파일 권한을 위한 사용자/그룹 ID (기본: 1000)
- **DOWNLOAD_PATH**: 다운로드 저장 경로 (기본: /app/backend/downloads)

### 7. 볼륨 매핑 설명

- `./downloads:/app/backend/downloads` - 다운로드 파일 저장
- `./backend/config.json:/app/backend/config.json` - 설정 파일 (선택사항)
- `./backend/database.db:/app/backend/database.db` - SQLite DB 파일 (선택사항)

### 8. 지원 플랫폼

- **linux/amd64** (x86_64) - Intel/AMD 64-bit
- **linux/arm64** (aarch64) - ARM 64-bit (Apple Silicon, Raspberry Pi 4+ 등)

GitHub Actions를 통해 자동으로 multi-platform 이미지가 빌드되어 Docker Hub에 배포됩니다.

---

## 🛠️ 개발 환경에서 실행하기

### 1. 백엔드 실행
```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --log-level debug
```

### 2. 프론트엔드 실행
```bash
cd frontend
npm run dev
```

---

기타 문의/이슈는 깃허브 이슈로 남겨주세요!
