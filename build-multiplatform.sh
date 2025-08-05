#!/bin/bash

# Multi-platform Docker build script
# Usage: ./build-multiplatform.sh [tag]

set -e

# Default image tag
TAG=${1:-"oc-proxy-downloader:latest"}

echo "🔧 Setting up Docker Buildx..."
docker buildx create --name multiplatform --use --bootstrap 2>/dev/null || docker buildx use multiplatform

echo "🏗️  Building multi-platform image: $TAG"
echo "   Platforms: linux/amd64, linux/arm64"

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag "$TAG" \
  --load \
  .

echo "✅ Multi-platform build completed!"
echo "   Image: $TAG"

# Show image details
echo ""
echo "📋 Image details:"
docker images "$TAG"

# Optional: Push to registry
read -p "📤 Push to Docker Hub? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🚀 Pushing to Docker Hub..."
    docker buildx build \
      --platform linux/amd64,linux/arm64 \
      --tag "$TAG" \
      --push \
      .
    echo "✅ Push completed!"
fi