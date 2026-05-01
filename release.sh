#!/bin/bash

# 자동 릴리스 스크립트 — 순수 SemVer (예: 2.0.22) 태그를 만들고 푸시한다.
# v 접두사 없는 태그가 워크플로우의 권장 형식.
# Usage: ./release.sh [major|minor|patch] or ./release.sh 1.2.3

set -e

# 현재 최신 태그 가져오기 (v 접두사 있는 과거 태그도 같이 후보로 포함)
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "0.0.0")
echo "현재 최신 태그: $LATEST_TAG"

if [[ $# -eq 0 ]]; then
    echo "사용법:"
    echo "  ./release.sh patch   # 1.0.0 -> 1.0.1"
    echo "  ./release.sh minor   # 1.0.0 -> 1.1.0"
    echo "  ./release.sh major   # 1.0.0 -> 2.0.0"
    echo "  ./release.sh 1.2.3   # 직접 지정"
    exit 1
fi

# 버전 파싱: v 접두사 있어도 허용
VERSION_REGEX="^v?([0-9]+)\.([0-9]+)\.([0-9]+)$"
if [[ $LATEST_TAG =~ $VERSION_REGEX ]]; then
    MAJOR=${BASH_REMATCH[1]}
    MINOR=${BASH_REMATCH[2]}
    PATCH=${BASH_REMATCH[3]}
else
    echo "기본 버전 0.0.0 사용"
    MAJOR=0
    MINOR=0
    PATCH=0
fi

# 새 버전 계산 (v 접두사 없이)
case $1 in
    "major")
        NEW_VERSION="$((MAJOR + 1)).0.0"
        ;;
    "minor")
        NEW_VERSION="${MAJOR}.$((MINOR + 1)).0"
        ;;
    "patch")
        NEW_VERSION="${MAJOR}.${MINOR}.$((PATCH + 1))"
        ;;
    [0-9]*|v[0-9]*)
        # 사용자가 v 를 붙여 줘도 자동으로 떼어 정규화
        NEW_VERSION="${1#v}"
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
echo "   GitHub Actions 에서 Windows EXE + Docker 이미지가 빌드됩니다."
echo "   태그: $NEW_VERSION"
echo "   Docker 이미지: jshsakura/oc-proxy-downloader:${NEW_VERSION}"
echo "   GitHub Actions: https://github.com/$(git config --get remote.origin.url | sed 's/.*github.com[:/]\([^.]*\).*/\1/')/actions"