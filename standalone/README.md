# OC Proxy Downloader - Windows Standalone

## 🎯 개요
단일 EXE 파일로 실행되는 Windows 독립 실행 버전입니다.

- **Python 설치 불필요**: 모든 의존성이 EXE에 포함
- **단일 파일 배포**: EXE 파일 하나만으로 완전한 애플리케이션
- **자동 브라우저 실행**: 실행 시 자동으로 웹 인터페이스 열림
- **휴대용**: USB에 넣고 다니면서 실행 가능

## 🚀 사용법

### 빠른 시작
```bash
cd standalone
.\test.bat          # 테스트 실행
.\build.bat         # EXE 빌드
```

### 수동 실행
```bash
# 테스트 (Python으로 직접 실행)
python main_standalone.py

# EXE 빌드
pyinstaller build.spec
```

## 📁 구조
```
standalone/
├── main_standalone.py    # 메인 애플리케이션
├── build.spec           # PyInstaller 설정
├── build.bat            # 자동 빌드 스크립트
├── test.bat             # 테스트 스크립트
└── release/             # 빌드 결과물
    ├── oc-proxy-downloader.exe
    ├── downloads/
    ├── config/
    └── README.txt
```

## 🎯 특징

### 올인원 패키징
- **FastAPI 백엔드**: 웹 API 서버
- **Svelte 프론트엔드**: 웹 인터페이스 (빌드된 정적 파일)
- **Python 런타임**: 모든 Python 의존성 포함
- **자동 브라우저**: 5초 후 자동으로 웹 인터페이스 열림

### 사용자 친화적
- **설치 불필요**: 다운로드 후 바로 실행
- **포터블**: 어떤 Windows PC에서나 실행
- **데이터 보존**: downloads/, config/ 폴더에 데이터 저장

## 🏗️ 빌드 과정

1. **프론트엔드 빌드**: `npm run build` (frontend/build/ 생성)
2. **의존성 설치**: PyInstaller 및 백엔드 패키지 설치
3. **EXE 생성**: PyInstaller로 단일 실행 파일 생성
4. **배포 폴더**: release/ 폴더에 실행 가능한 패키지 생성

## 🔧 개발자 정보

### 기술 스택
- **Backend**: FastAPI + Python 3.8+
- **Frontend**: Svelte + Vite
- **Packaging**: PyInstaller
- **WebDriver**: Selenium (Chrome)

### 환경 변수
실행 시 자동으로 설정되는 환경 변수들:
- `DOWNLOAD_PATH`: EXE와 같은 폴더의 downloads/
- `CONFIG_PATH`: EXE와 같은 폴더의 config/
- `LOG_LEVEL`: WARNING (조용한 실행)

## 🐛 문제 해결

### "EXE가 실행되지 않음"
1. Windows Defender에서 제외 처리
2. 바이러스 백신 소프트웨어 확인
3. 관리자 권한으로 실행 시도

### "웹 페이지가 열리지 않음"
1. Windows 방화벽에서 허용
2. 포트 8000이 사용 중인지 확인
3. 5-10초 정도 대기 후 수동으로 http://localhost:8000 접속

### "다운로드가 안됨"
1. Chrome/Edge 브라우저 설치 확인
2. 인터넷 연결 상태 확인
3. 프록시 설정 확인

## 📦 배포

### 최종 사용자용
- `release/oc-proxy-downloader.exe` - 메인 실행파일
- `release/downloads/` - 다운로드 저장소
- `release/config/` - 설정 파일 저장소
- `release/README.txt` - 사용자 가이드

### 배포 방법
1. `build.bat` 실행하여 EXE 생성
2. `release/` 폴더 전체를 압축하여 배포
3. 사용자는 압축 해제 후 EXE 실행

---
**단순하고 강력한 Windows 독립 실행 버전** 🚀