# OC Proxy Downloader 프론트엔드

Svelte 5·Vite 기반 다운로드 대시보드입니다. Docker 이미지는 이 프론트엔드를 빌드해 FastAPI가 정적 파일로 제공합니다. 다운로드 상태는 SSE로 갱신합니다.

## 개발

```bash
cd frontend
npm ci
npm run dev       # http://localhost:3000
npm test
npm run build     # dist/
```

Vite 개발 서버는 `/api` 요청을 `http://localhost:8000`으로 전달합니다. 백엔드는 저장소 루트에서 `docker compose up -d`로 실행하거나 `python backend/main.py`로 따로 실행할 수 있습니다.

## 주요 구성

- `src/App.svelte`: 앱 시작점
- `src/lib/Dashboard.svelte`: 다운로드 화면
- `src/lib/AgDownloadGrid.svelte`: 진행·완료 목록
- `src/lib/DetailModal.svelte`: 다운로드 상세 정보
- `src/lib/SettingsModal.svelte`: 동시 다운로드 수, 프록시, 호스트 설정
- `src/lib/i18n.js`와 `backend/locales/*.json`: 언어별 표시 문자열

지원 호스트의 실제 판정은 백엔드 `HOSTER_REGISTRY`와 1fichier·MEGA 전용 경로가 담당합니다. AkiraBox·VikingFile·Rootz는 Docker 브라우저에서 링크를 발급하고, DataVaults 자동 다운로드는 지원하지 않습니다. 파일명·용량이 먼저 표시돼도 다운로드 차례에 호스트가 최종 주소 발급을 거부할 수 있습니다.

상태 갱신은 SSE를 사용합니다. 새 표시 문구를 추가할 때는 원시 오류 코드나 `find_browser_parse` 같은 내부 키가 사용자 화면에 노출되지 않도록 모든 로케일의 문구와 실패 상태 표시를 확인하세요.
