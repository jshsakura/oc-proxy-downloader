# OC Proxy Downloader 백엔드

FastAPI·SQLite·aiohttp 기반 다운로드 서버입니다. 상태 갱신은 SSE를 사용합니다. 운영 환경은 저장소 루트의 Docker Compose와 Docker 이미지를 기준으로 합니다. 브라우저가 필요한 호스트는 이미지에 포함된 Chromium·Xvfb가 있어야 합니다.

## 실행과 데이터

```bash
docker compose up -d
docker compose ps
curl http://localhost:8000/api/auth/status
```

- `/config/config.json`: 다운로드 경로, 동시 실행 한도, 라우팅, FlareSolverr 주소 등
- `/config/downloads.db`: 다운로드 요청과 프록시 상태를 저장하는 SQLite DB
- `/downloads`: 내려받은 파일
- `CONFIG_PATH`, `DOWNLOAD_PATH`: Docker의 설정·파일 경로. 로컬 실행 시 기본 경로는 `backend/config`, 저장소의 `downloads`입니다.

설정 기본값은 `core/config.py`의 `DEFAULT_CONFIG`가 기준입니다. `max_concurrent_downloads=8`, `max_per_host_downloads=3`, `parse_concurrency=3`이며 웹 설정에서도 바꿀 수 있습니다. 1fichier 무료 전송은 회선당 1개, DataNodes·MultiUp은 호스트당 1개로 제한합니다. 호스트별 한도는 `core/download_core.py`의 `SITE_DOWNLOAD_LIMITS`를 참고하세요.

## 다운로드 경로

1. `POST /api/download/`가 요청을 저장합니다. 여러 링크를 넣어도 전송 슬롯을 기다리는 항목은 대기열에 남습니다.
2. `core/hoster_parsers.py`의 `HOSTER_REGISTRY`가 URL을 호스트별 파서에 연결합니다. 실제 구현은 `core/hoster_sites.py`에 있습니다. 1fichier와 MEGA는 별도 경로를 사용합니다.
3. 브라우저가 필요한 호스트는 `core/browser_solver.py`와 `core/executors.py`의 전용 풀을 사용합니다. 같은 호스트의 브라우저 파싱은 한 번에 하나씩 처리합니다.
4. 직접 다운로드 주소가 발급되면 `core/download_core.py`가 파일을 전송하고 진행률을 SSE로 알립니다.

AkiraBox, VikingFile, Rootz는 다운로드 차례가 왔을 때 주소를 발급합니다. AkiraBox와 VikingFile은 브라우저가 연 페이지에서 파일명·크기를 함께 읽고, Rootz는 파일 정보 API와 프록시 다운로드 경로의 HEAD 응답으로 실제 파일 서버 주소를 확인합니다. 이 세 호스트는 발급 실패 시 프록시를 여러 번 바꿔가며 파싱하거나 파일 전송 실패 뒤 자동으로 재파싱하지 않습니다. URL의 별칭 도메인도 같은 호스트 한도를 공유합니다.

DataVaults는 무료 다운로드 단계에 reCAPTCHA v2가 있어 자동 다운로드 지원 목록에 없습니다. Rapidgator 무료 다운로드도 파서가 거부합니다. 호스트 지원 표는 [한국어 README](../README_KR.md)를 참고하세요.

## 인증과 연계

웹 로그인은 `AUTH_USERNAME`·`AUTH_PASSWORD`로 설정합니다. 서버 간 API 호출에는 설정 화면에서 생성·교체하는 토큰 또는 `API_TOKEN` 환경 변수를 사용하고 `X-API-Key` 헤더로 보냅니다. 공개 상태 확인은 `GET /api/auth/status`입니다.

주요 API: `POST /api/download/`, `GET /api/downloads/working`, `GET /api/downloads/completed`, `POST /api/retry/{id}`, `POST /api/downloads/stop/{id}`, `GET /api/settings`. 현재 라우트 목록은 `api/routes/`와 `/docs`를 확인하세요.

## 개발과 검증

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest pytest-asyncio
PYTHONPATH=. pytest -q tests/test_hoster_parsers.py tests/test_browser_solver.py tests/test_smart_download_concurrency.py
```

새 호스트를 추가할 때는 `core/hoster_sites.py`에 실제 주소 발급 코드를 넣고, `core/hoster_parsers.py`에 등록합니다. 브라우저가 필요한 경우 `BROWSER_FLOW_HOSTS`와 `BROWSER_REQUIRED_HOSTS`도 확인하세요. 파일명만 추출할 수 있는 호스트를 다운로드 가능하다고 표시하지 마세요.
