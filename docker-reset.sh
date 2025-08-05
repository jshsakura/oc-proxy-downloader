#!/bin/bash

echo "🧹 Docker 완전 정리 및 재빌드"

# 1. 컨테이너 중지 및 제거
echo "1. 컨테이너 중지 및 제거..."
docker-compose down --remove-orphans

# 2. 이미지 제거
echo "2. 기존 이미지 제거..."
docker rmi oc-proxy-downloader:latest 2>/dev/null || true
docker rmi $(docker images | grep oc-proxy-downloader | awk '{print $3}') 2>/dev/null || true

# 3. 빌드 캐시 정리
echo "3. Docker 빌드 캐시 정리..."
docker builder prune -f

# 4. 시스템 정리 (선택적)
read -p "모든 Docker 캐시를 정리하시겠습니까? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker system prune -a -f
fi

# 5. 완전 재빌드
echo "4. 완전 재빌드 시작..."
docker-compose build --no-cache

# 6. 실행
echo "5. 컨테이너 실행..."
docker-compose up -d

echo "✅ 완료! 로그 확인:"
docker-compose logs -f