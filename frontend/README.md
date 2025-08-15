# OC Proxy Downloader - Frontend

Svelte 기반의 1fichier 다운로드 관리 웹 인터페이스입니다.

## 🚀 빠른 시작

### 1. 환경 설정

#### Node.js 설치 확인
```bash
node --version  # v16+ 권장
npm --version
```

#### 의존성 설치
```bash
npm install
```

### 2. 개발 서버 실행

```bash
npm run dev
```

개발 서버가 http://localhost:5173 에서 실행됩니다.

### 3. 빌드

#### 프로덕션 빌드
```bash
npm run build
```

빌드된 파일은 `dist/` 디렉토리에 생성됩니다.

#### 빌드 결과 미리보기
```bash
npm run preview
```

## 📁 프로젝트 구조

```
frontend/
├── index.html              # 메인 HTML 템플릿
├── package.json            # npm 의존성 및 스크립트
├── vite.config.js          # Vite 빌드 설정
├── svelte.config.js        # Svelte 설정
├── src/
│   ├── main.js             # 애플리케이션 진입점
│   ├── App.svelte          # 메인 컴포넌트
│   ├── app.css             # 글로벌 스타일
│   ├── lib/                # 재사용 가능한 컴포넌트
│   │   ├── ConfirmModal.svelte     # 확인 대화상자
│   │   ├── DetailModal.svelte      # 다운로드 상세 정보
│   │   ├── LocalGauge.svelte       # 로컬 다운로드 게이지
│   │   ├── PasswordModal.svelte    # 비밀번호 입력
│   │   ├── ProxyGauge.svelte      # 프록시 상태 게이지
│   │   ├── SettingsModal.svelte    # 설정 모달
│   │   ├── ThemeToggle.svelte      # 다크/라이트 테마 토글
│   │   ├── i18n.js                 # 국제화 (한국어/영어)
│   │   ├── theme.js                # 테마 관리
│   │   └── toast.js                # 토스트 알림
│   ├── icons/              # SVG 아이콘 컴포넌트
│   └── assets/             # 정적 자원 (이미지 등)
└── dist/                   # 빌드 결과물 (생성됨)
```

## 🎨 주요 기능

### 다운로드 관리
- 1fichier URL 추가 및 다운로드 요청
- 실시간 다운로드 진행률 표시
- 다운로드 히스토리 관리
- 일시정지/재개/취소 기능

### 사용자 인터페이스
- 반응형 디자인 (모바일/데스크톱 지원)
- 다크/라이트 테마 지원
- 다국어 지원 (한국어/영어)
- 실시간 상태 업데이트 (WebSocket)

### 프록시 관리
- 프록시 목록 표시 및 관리
- 실시간 프록시 상태 모니터링
- 프록시 성능 통계

### 설정 관리
- 다운로드 경로 설정
- 테마 및 언어 설정
- 실시간 설정 동기화

## 🔧 개발 설정

### 백엔드 연결 설정

기본적으로 `http://localhost:8000`에서 실행되는 백엔드 서버에 연결됩니다.

다른 백엔드 주소를 사용하려면 `src/main.js`에서 API 베이스 URL을 수정하세요:

```javascript
const API_BASE_URL = 'http://your-backend-server:8000';
```

### 환경별 설정

#### 개발 환경
- Hot Module Replacement (HMR) 지원
- 소스맵 생성
- 개발자 도구 지원

#### 프로덕션 환경
- 코드 최적화 및 압축
- CSS 추출 및 최적화
- 번들 크기 최소화

## 🎯 컴포넌트 가이드

### 모달 컴포넌트

#### SettingsModal.svelte
```svelte
<script>
  import SettingsModal from './lib/SettingsModal.svelte';
  
  let showSettings = false;
</script>

<SettingsModal bind:show={showSettings} />
```

#### DetailModal.svelte
```svelte
<script>
  import DetailModal from './lib/DetailModal.svelte';
  
  let selectedDownload = null;
</script>

<DetailModal bind:download={selectedDownload} />
```

### 테마 시스템

```javascript
import { theme } from './lib/theme.js';

// 테마 변경
theme.set('dark');

// 현재 테마 구독
theme.subscribe(currentTheme => {
  console.log('Current theme:', currentTheme);
});
```

### 국제화 (i18n)

```javascript
import { t, currentLang } from './lib/i18n.js';

// 언어 변경
currentLang.set('en');

// 번역 텍스트 사용
$t('download.add_url')  // "다운로드 URL 추가"
```

## 🔨 빌드 최적화

### Vite 설정 (vite.config.js)

```javascript
export default {
  build: {
    target: 'es2015',
    outDir: 'dist',
    assetsDir: 'assets',
    minify: 'esbuild',
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['svelte']
        }
      }
    }
  }
}
```

### 성능 최적화 팁

1. **코드 스플리팅**: 라우트별로 컴포넌트 분리
2. **이미지 최적화**: WebP 포맷 사용
3. **번들 분석**: `npm run build --analyze`
4. **Lazy Loading**: 큰 컴포넌트는 동적 import 사용

## 🐛 디버깅

### 개발자 도구

```bash
# 개발 모드에서 디버깅 정보 활성화
npm run dev -- --debug

# 번들 분석
npm run build -- --analyze
```

### 일반적인 문제 해결

#### 백엔드 연결 실패
```javascript
// src/main.js에서 CORS 설정 확인
const response = await fetch('/api/settings', {
  headers: {
    'Accept': 'application/json',
    'Content-Type': 'application/json'
  }
});
```

#### 빌드 오류
```bash
# node_modules 재설치
rm -rf node_modules package-lock.json
npm install

# 캐시 클리어
npm run build -- --force
```

## 📦 의존성

### 주요 라이브러리
- `svelte` - 컴포넌트 프레임워크
- `vite` - 빌드 도구 및 개발 서버
- `@vitejs/plugin-svelte` - Svelte Vite 플러그인

### 개발 의존성
- `eslint` - 코드 린팅
- `prettier` - 코드 포매팅
- `svelte-check` - 타입 체킹

전체 의존성은 `package.json` 참조.

## 🚀 배포

### 정적 호스팅 (권장)
```bash
npm run build
# dist/ 폴더를 웹 서버에 업로드
```

### Docker와 함께 배포
프로젝트 루트의 `Dockerfile`이 프론트엔드 빌드를 포함합니다.

### CDN 배포
빌드된 파일을 CDN에 업로드하여 전세계 빠른 로딩 제공.