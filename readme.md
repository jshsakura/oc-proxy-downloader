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

### 1. 이미지 빌드

```bash
docker build -t <YOUR_DOCKERHUB_ID>/oc-proxy-downloader:latest .
```

### 2. 도커허브 푸시

```bash
docker login
docker push <YOUR_DOCKERHUB_ID>/oc-proxy-downloader:latest
```

### 3. docker-compose로 실행 (권장)

```yaml
version: "3.8"
services:
  app:
    image: <YOUR_DOCKERHUB_ID>/oc-proxy-downloader:latest
    container_name: oc-proxy-downloader
    environment:
      - TZ=Asia/Seoul
      - PUID=1000
      - PGID=1000
    volumes:
      - ./backend/downloads:/app/backend/downloads
    ports:
      - "8000:8000"
    restart: unless-stopped
```

- **볼륨 매핑**: 호스트의 `./backend/downloads` 폴더를 컨테이너의 `/app/backend/downloads`와 동기화합니다.
- **FastAPI는 기본적으로 `/app/backend/downloads` 경로를 다운로드 폴더로 사용**합니다.
- **PUID/PGID**: 컨테이너 내 파일/폴더 권한을 호스트와 맞추기 위한 유저/그룹 ID
- **TZ**: 타임존

### 4. 단일 docker run 예시

```bash
docker run -d \
  --name oc-proxy-downloader \
  -e TZ=Asia/Seoul \
  -e PUID=$(id -u) \
  -e PGID=$(id -g) \
  -v $(pwd)/backend/downloads:/app/backend/downloads \
  -p 8000:8000 \
  <YOUR_DOCKERHUB_ID>/oc-proxy-downloader:latest
```

### 5. FastAPI 다운로드 경로

`backend/core/config.py`의 `get_download_path()`는 `/app/backend/downloads`를 기본값으로 사용합니다.

---

기타 문의/이슈는 깃허브 이슈로 남겨주세요!
