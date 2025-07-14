# 1단계: Svelte 프론트엔드 빌드
FROM node:20 AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# 2단계: Python FastAPI 백엔드 + 정적 파일
FROM python:3.11-slim AS backend
WORKDIR /app

# 필수 패키지 설치
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY backend/ ./backend/
COPY backend/locales/ ./backend/locales/
COPY backend/config.json ./backend/config.json
COPY backend/core/ ./backend/core/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# 환경변수 기본값
ENV DOWNLOAD_PATH=/app/backend/downloads \
  PUID=1000 \
  PGID=1000 \
  TZ=Asia/Seoul

EXPOSE 8000

CMD addgroup --gid $PGID appuser && \
  adduser --disabled-password --gecos '' --uid $PUID --gid $PGID appuser && \
  export TZ=$TZ && \
  mkdir -p $DOWNLOAD_PATH && \
  chown -R $PUID:$PGID $DOWNLOAD_PATH && \
  su appuser -c "uvicorn backend.main:app --host 0.0.0.0 --port 8000" 