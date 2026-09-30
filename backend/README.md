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

설정 기본값은 `core/config.py`의 `DEFAULT_CONFIG`가 기준입니다. `max_concurrent_downloads=8`, `max_per_host_downloads=3`, `parse_concurrency=3`이며 웹 설정에서도 바꿀 수 있습니다. 호스트당 설정은 상한입니다. 1fichier 무료 전송은 직접·프록시 각각 회선당 1개, 무료 1fichier·Rapidgator는 1개로 고정하고, 실제 동시 전체 전송을 확인한 GoFile·VikingFile은 최대 3개입니다. MegaUp·DataNodes·Rootz 등 나머지는 보수적으로 1개로 제한합니다. 호스트별 한도와 별칭은 `core/host_policy.py`의 `SITE_DOWNLOAD_LIMITS`와 `HOST_ALIASES`를 참고하세요. 특수 호스터는 파싱과 파일 전송에 같은 직접 회선을 사용합니다. Send.cm·TusFiles·Send.now는 같은 대기열을 공유합니다.

메타데이터 조회도 호스트 슬롯을 얻은 뒤 실행합니다. 같은 사이트의 파싱은 하나씩 처리하되 병렬 전송이 가능한 호스트의 파일 다운로드는 설정된 한도까지 진행합니다. 파서 시간 초과·취소 후에도 실제 스레드가 끝날 때까지 다음 파싱을 막습니다. HTTP 429는 `Retry-After`를 반영해 같은 호스트 대기열을 함께 지연합니다. 서버가 한 번에 한 파일만 허용한다고 명시하면 해당 호스트의 한도를 1개로 낮춥니다. 확인된 제한과 대기시간은 SQLite의 `host_admission_state`에 저장하고 대기열을 시작하기 전에 복원하므로 수동 재시도·서버 재시작·개별 이력 삭제로 사라지지 않습니다. 설정 저장은 기존 슬롯을 갱신하며, 이미 진행 중인 작업이 끝난 뒤 낮아진 한도로 새 작업을 받습니다.

## 다운로드 경로

1. `POST /api/download/`가 요청을 저장합니다. 여러 링크를 넣어도 전송 슬롯을 기다리는 항목은 대기열에 남습니다.
2. `core/hoster_parsers.py`의 `HOSTER_REGISTRY`가 URL을 호스트별 파서에 연결합니다. 실제 구현은 `core/hoster_sites.py`에 있습니다. 1fichier와 MEGA는 별도 경로를 사용합니다.
3. 브라우저가 필요한 호스트는 `core/browser_solver.py`와 `core/executors.py`의 전용 풀을 사용합니다. 같은 호스트의 브라우저 파싱은 한 번에 하나씩 처리합니다.
4. 직접 다운로드 주소가 발급되면 `core/download_core.py`가 파일을 전송하고 진행률을 SSE로 알립니다.

AkiraBox, VikingFile, Rootz는 다운로드 차례가 왔을 때 주소를 발급합니다. AkiraBox와 VikingFile은 브라우저가 연 페이지에서 파일명·크기를 함께 읽고, Rootz는 파일 정보 API와 프록시 다운로드 경로의 HEAD 응답으로 실제 파일 서버 주소를 확인합니다. 이 세 호스트는 발급 실패 시 프록시를 여러 번 바꿔가며 파싱하거나 파일 전송 실패 뒤 자동으로 재파싱하지 않습니다. URL의 별칭 도메인도 같은 호스트 한도를 공유합니다.

DataVaults는 실제 무료 폼을 한 번씩 처리하며, reCAPTCHA를 요구하는 파일은 자동 반복 없이 중단합니다. 호스트 전체를 차단하지 않습니다. Rapidgator 무료 다운로드도 파서가 거부합니다. 호스트 지원 표는 [한국어 README](../README_KR.md)를 참고하세요.

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

FileCrypt만 브라우저 내부 900초/외부 실행 960초를 사용합니다. 호스트·executor·브라우저 대기열은
실행시간에서 제외하며, 취소/시간초과 뒤에도 실제 스레드 종료 전 다음 파싱을 허용하지 않습니다.
컨테이너는 단일 공개 파일 주소만 자동 인계하고 다중 파일은 선택을 요구합니다.

호스터 파싱 실패도 이미 읽은 파일명·크기를 보존합니다. `HosterParseError.file_info`는 성공 결과와 같은 메타데이터 형식이며, `size_bytes`가 있으면 반올림한 표시 크기 대신 정확한 바이트 수를 저장합니다. 실패 상태와 삭제 확정은 별개이며, 이름 복원을 위해 외부 URL을 다시 요청하지 않습니다.

`POST /api/download/`의 선택 필드 `filename` 또는 `file_name`으로 수집한 표시 이름을 전달할 수 있습니다. 다운로드 주소를 발급받기 전부터 목록에 표시하며, 필드가 없으면 URL에서 식별자를 유도합니다. 표시 이름만으로 파일 전송 성공을 판단하지 않습니다.
