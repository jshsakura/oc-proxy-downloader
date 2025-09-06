# 1단계: Svelte 프론트엔드 빌드
FROM --platform=$BUILDPLATFORM node:20-alpine AS frontend-build
WORKDIR /app/frontend

# 의존성 파일들만 먼저 복사하여 캐싱 최적화
COPY frontend/package*.json ./
RUN npm ci --ignore-scripts

# 소스 코드는 나중에 복사하여 의존성 변경이 없으면 재사용 가능
COPY frontend/ ./
RUN npm run build

# 2단계: Python FastAPI 백엔드 + 정적 파일
FROM python:3.11-slim AS backend

# Build arguments for multi-platform
ARG TARGETPLATFORM
ARG BUILDPLATFORM
ARG VERSION=dev

WORKDIR /app

# 시스템 패키지 설치 최적화 (단일 레이어)
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Python 의존성 먼저 설치 (캐싱 최적화)
COPY backend/requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install -r requirements.txt && \
    pip install beautifulsoup4

# 백엔드 소스는 의존성 설치 후 복사 (소스 변경 시에만 재빌드)
COPY backend/ ./backend/

# 프론트엔드 빌드 결과 복사
COPY --from=frontend-build /app/frontend/dist ./backend/static

# 필요한 디렉토리 생성
RUN mkdir -p /downloads /config

# 환경변수 기본값
ENV DOWNLOAD_PATH=/downloads \
    CONFIG_PATH=/config \
    PUID=1000 \
    PGID=1000 \
    TZ=Asia/Seoul \
    PYTHONPATH=/app \
    APP_VERSION=${VERSION}
    # 인증 관련 환경변수 (선택사항)
    # AUTH_USERNAME=admin \
    # AUTH_PASSWORD=your-secure-password \
    # JWT_SECRET_KEY=your-secret-key \
    # JWT_EXPIRATION_HOURS=24

EXPOSE 8000

# 시작 스크립트 생성
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# 사용자 그룹 생성\n\
if ! getent group appuser > /dev/null 2>&1; then\n\
    addgroup --gid $PGID appuser\n\
fi\n\
\n\
# 사용자 생성\n\
if ! getent passwd appuser > /dev/null 2>&1; then\n\
    adduser --disabled-password --gecos "" --uid $PUID --gid $PGID appuser\n\
fi\n\
\n\
# 디렉토리 권한 설정\n\
mkdir -p $DOWNLOAD_PATH $CONFIG_PATH\n\
chown -R $PUID:$PGID $DOWNLOAD_PATH $CONFIG_PATH\n\
chown -R $PUID:$PGID /app/backend\n\
\n\
# 타임존 설정\n\
export TZ=$TZ\n\
\n\
# 애플리케이션 실행\n\
cd /app && su appuser -c "python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"\n\
' > /start.sh && chmod +x /start.sh

CMD ["/start.sh"] 