@echo off
chcp 65001 >nul 2>&1
echo 🚀 OC Proxy Downloader Standalone EXE Build
echo ===========================================

echo 📦 Step 1: Frontend build check...
if not exist "..\frontend\build" (
    echo ❌ Frontend not built. Building now...
    cd ..\frontend
    if not exist "node_modules" (
        echo 📥 Installing frontend dependencies...
        call npm install
        if errorlevel 1 (
            echo ❌ Frontend npm install failed
            pause
            exit /b 1
        )
    )
    call npm run build
    if errorlevel 1 (
        echo ❌ Frontend build failed
        pause
        exit /b 1
    )
    cd ..\standalone
    echo ✅ Frontend build completed
) else (
    echo ✅ Frontend already built
)

echo 📦 Step 2: Activating virtual environment...
if not exist "..\venv\Scripts\activate.bat" (
    echo ❌ Virtual environment not found. Please run: python -m venv venv
    pause
    exit /b 1
)
call ..\venv\Scripts\activate.bat
echo ✅ Virtual environment activated

echo 📦 Step 3: Installing PyInstaller...
python -m pip install pyinstaller
if errorlevel 1 (
    echo ❌ PyInstaller installation failed
    pause
    exit /b 1
)

echo 📦 Step 4: Installing backend dependencies...
python -m pip install -r ..\backend\requirements.txt
if errorlevel 1 (
    echo ❌ Backend dependencies installation failed
    pause
    exit /b 1
)

echo 🏗️ Step 5: Building EXE with PyInstaller...
python -m PyInstaller build.spec
if errorlevel 1 (
    echo ❌ EXE build failed
    pause
    exit /b 1
)

echo 📁 Step 6: Creating distribution folder...
if exist "release" rmdir /s /q "release"
mkdir release
mkdir release\config

copy "dist\oc-proxy-downloader.exe" "release\"
echo # OC Proxy Downloader - Standalone > release\README.txt
echo. >> release\README.txt
echo 실행: oc-proxy-downloader.exe >> release\README.txt
echo 웹 인터페이스: http://localhost:8759 >> release\README.txt
echo. >> release\README.txt
echo 다운로드 폴더: 사용자 다운로드 폴더 (C:\Users\사용자명\Downloads) >> release\README.txt
echo config/ - 설정 저장 폴더 >> release\README.txt
echo. >> release\README.txt
echo 주의: 첫 실행 시 Windows Defender에서 차단할 수 있습니다. >> release\README.txt
echo      "추가 정보" ^> "실행" 을 클릭하여 실행하세요. >> release\README.txt
echo. >> release\README.txt
echo 포트: 8759 (웹 버전과 충돌 방지) >> release\README.txt
echo 버전: Standalone EXE v1.0 >> release\README.txt

echo ✅ Standalone EXE build completed!
echo 📦 결과물: release\oc-proxy-downloader.exe
echo 💾 크기: 
dir release\oc-proxy-downloader.exe
echo.
echo 🚀 테스트: cd release && oc-proxy-downloader.exe
pause