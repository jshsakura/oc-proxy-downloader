# Docker 완전 정리 및 재빌드 (Windows PowerShell)

Write-Host "🧹 Docker 완전 정리 및 재빌드" -ForegroundColor Yellow

# 1. 컨테이너 중지 및 제거
Write-Host "1. 컨테이너 중지 및 제거..." -ForegroundColor Green
docker-compose down --remove-orphans

# 2. 이미지 제거
Write-Host "2. 기존 이미지 제거..." -ForegroundColor Green
try {
    docker rmi oc-proxy-downloader:latest 2>$null
} catch {}

$images = docker images | Select-String "oc-proxy-downloader" | ForEach-Object { ($_ -split '\s+')[2] }
if ($images) {
    docker rmi $images 2>$null
}

# 3. 빌드 캐시 정리
Write-Host "3. Docker 빌드 캐시 정리..." -ForegroundColor Green
docker builder prune -f

# 4. 시스템 정리 (선택적)
$cleanup = Read-Host "모든 Docker 캐시를 정리하시겠습니까? (y/n)"
if ($cleanup -eq "y" -or $cleanup -eq "Y") {
    docker system prune -a -f
}

# 5. 완전 재빌드
Write-Host "4. 완전 재빌드 시작..." -ForegroundColor Green
docker-compose build --no-cache

# 6. 실행
Write-Host "5. 컨테이너 실행..." -ForegroundColor Green
docker-compose up -d

Write-Host "✅ 완료! 로그 확인:" -ForegroundColor Green
docker-compose logs -f