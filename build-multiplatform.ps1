# Multi-platform Docker build script for Windows
# Usage: .\build-multiplatform.ps1 [tag]

param(
    [string]$Tag = "oc-proxy-downloader:latest"
)

Write-Host "🔧 Setting up Docker Buildx..." -ForegroundColor Yellow

try {
    docker buildx create --name multiplatform --use --bootstrap 2>$null
} catch {
    docker buildx use multiplatform
}

Write-Host "🏗️  Building multi-platform image: $Tag" -ForegroundColor Green
Write-Host "   Platforms: linux/amd64, linux/arm64" -ForegroundColor Cyan

docker buildx build `
    --platform linux/amd64,linux/arm64 `
    --tag $Tag `
    --load `
    .

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Multi-platform build completed!" -ForegroundColor Green
    Write-Host "   Image: $Tag" -ForegroundColor White
    
    Write-Host "`n📋 Image details:" -ForegroundColor Blue
    docker images $Tag
    
    # Optional: Push to registry
    $push = Read-Host "`n📤 Push to Docker Hub? (y/n)"
    if ($push -eq "y" -or $push -eq "Y") {
        Write-Host "🚀 Pushing to Docker Hub..." -ForegroundColor Yellow
        docker buildx build `
            --platform linux/amd64,linux/arm64 `
            --tag $Tag `
            --push `
            .
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✅ Push completed!" -ForegroundColor Green
        } else {
            Write-Host "❌ Push failed!" -ForegroundColor Red
        }
    }
} else {
    Write-Host "❌ Build failed!" -ForegroundColor Red
    exit 1
}