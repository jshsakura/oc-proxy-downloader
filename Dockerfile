# 1단계: Svelte 프론트엔드 빌드 (빌드 속도 최적화)
FROM --platform=$BUILDPLATFORM node:20-alpine AS frontend-build
WORKDIR /app/frontend

# 종속성 캐시 최적화
COPY frontend/package*.json ./
RUN --mount=type=cache,target=/root/.npm \
    --mount=type=cache,target=/app/frontend/node_modules \
    npm ci --ignore-scripts --prefer-offline

# 소스 코드 복사 및 빌드
COPY frontend/ ./
RUN --mount=type=cache,target=/app/frontend/node_modules \
    --mount=type=cache,target=/app/frontend/.svelte-kit \
    npm run build

# 2단계: Python FastAPI 백엔드 + 정적 파일 (빌드 속도 최적화)
FROM python:3.11-slim AS backend

# Build arguments for multi-platform
ARG TARGETPLATFORM
ARG BUILDPLATFORM
ARG VERSION=dev

WORKDIR /app

# 시스템 패키지 설치 (권한 관리용) - 캐시 최적화
RUN --mount=type=cache,target=/var/cache/apt \
    --mount=type=cache,target=/var/lib/apt \
    apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Python 의존성 설치 - pip 캐시 최적화
COPY backend/requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 백엔드 소스 복사 (레이어 최적화)
COPY backend/ ./backend/

# 프론트엔드 빌드 결과 복사 (Vite는 build 폴더에 출력)
COPY --from=frontend-build /app/frontend/build ./backend/static

# 필요한 디렉토리 생성 및 권한 설정
RUN mkdir -p /downloads /config /app/logs && \
    groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser && \
    chown -R 1000:1000 /downloads /config /app

# 환경변수 기본값
ENV DOWNLOAD_PATH=/downloads \
    CONFIG_PATH=/config \
    PUID=1000 \
    PGID=1000 \
    TZ=Asia/Seoul \
    PYTHONPATH=/app \
    APP_VERSION=${VERSION}

EXPOSE 8000

# 경량화된 시작 스크립트 생성
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# 런타임 권한 설정 (최소화)\n\
mkdir -p $DOWNLOAD_PATH $CONFIG_PATH\n\
chown -R $PUID:$PGID $DOWNLOAD_PATH $CONFIG_PATH\n\
\n\
# 환경 변수 설정\n\
export TZ=$TZ\n\
export PYTHONPATH=/app\n\
\n\
# 애플리케이션 실행\n\
cd /app\n\
if [ "$PUID" -eq 0 ]; then\n\
    # Root로 실행\n\
    python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000\n\
else\n\
    # appuser로 실행\n\
    su appuser -c "python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"\n\
fi\n\
' > /start.sh && chmod +x /start.sh

# 빌드 시점 최적화: 불필요한 파일 정리
RUN apt-get autoremove -y && \
    apt-get autoclean && \
    rm -rf /tmp/* /var/tmp/* && \
    find /app -name "*.pyc" -delete && \
    find /app -name "__pycache__" -type d -exec rm -rf {} + || true

CMD ["/start.sh"] 