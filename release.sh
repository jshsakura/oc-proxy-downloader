#!/bin/bash

# 자동 릴리스 스크립트
# Usage: ./release.sh [major|minor|patch] or ./release.sh v1.2.3

set -e

# 현재 최신 태그 가져오기
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.0.0")
echo "현재 최신 태그: $LATEST_TAG"

if [[ $# -eq 0 ]]; then
    echo "사용법:"
    echo "  ./release.sh patch   # v1.0.0 -> v1.0.1"
    echo "  ./release.sh minor   # v1.0.0 -> v1.1.0"
    echo "  ./release.sh major   # v1.0.0 -> v2.0.0"
    echo "  ./release.sh v1.2.3  # 직접 지정"
    exit 1
fi

# 버전 파싱 (v1.2.3 -> 1 2 3)
VERSION_REGEX="^v([0-9]+)\.([0-9]+)\.([0-9]+)$"
if [[ $LATEST_TAG =~ $VERSION_REGEX ]]; then
    MAJOR=${BASH_REMATCH[1]}
    MINOR=${BASH_REMATCH[2]}
    PATCH=${BASH_REMATCH[3]}
else
    echo "기본 버전 v0.0.0 사용"
    MAJOR=0
    MINOR=0
    PATCH=0
fi

# 새 버전 계산
case $1 in
    "major")
        NEW_VERSION="v$((MAJOR + 1)).0.0"
        ;;
    "minor")
        NEW_VERSION="v${MAJOR}.$((MINOR + 1)).0"
        ;;
    "patch")
        NEW_VERSION="v${MAJOR}.${MINOR}.$((PATCH + 1))"
        ;;
    v*)
        NEW_VERSION="$1"
        ;;
    *)
        echo "❌ 잘못된 인수: $1"
        exit 1
        ;;
esac

echo "새 버전: $NEW_VERSION"

# 확인
read -p "🚀 $NEW_VERSION 으로 릴리스하시겠습니까? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "취소됨"
    exit 1
fi

# 태그 생성 및 푸시
echo "📝 태그 생성 중..."
git tag -a "$NEW_VERSION" -m "Release $NEW_VERSION"

echo "🚀 GitHub에 푸시 중..."
git push origin "$NEW_VERSION"

echo "✅ 릴리스 완료!"
echo "   GitHub Actions에서 Docker 이미지가 빌드됩니다."
echo "   태그: $NEW_VERSION"
echo "   Docker 이미지: WIN11/oc-proxy-downloader:${NEW_VERSION#v}"
echo "   GitHub Actions: https://github.com/$(git config --get remote.origin.url | sed 's/.*github.com[:/]\([^.]*\).*/\1/')/actions"