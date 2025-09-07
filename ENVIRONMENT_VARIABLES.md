# OC Proxy Downloader 환경 변수 설정 가이드

## 🔧 주요 환경 변수

### 기본 시스템 설정

| 환경 변수명 | 기본값 | 예시값 | 필수 | 설명 |
|------------|--------|--------|------|------|
| `TZ` | `UTC` | `Asia/Seoul` | ✅ | 시스템 타임존 설정. 로그 시간과 다운로드 시간 표시에 영향 |
| `PUID` | `1000` | `1026` | ✅ | 컨테이너 내부에서 사용할 사용자 ID. 파일 권한 관리용 |
| `PGID` | `1000` | `100` | ✅ | 컨테이너 내부에서 사용할 그룹 ID. 파일 권한 관리용 |
| `DOWNLOAD_PATH` | `/downloads` | `/downloads` | ✅ | 컨테이너 내부의 다운로드 저장 경로 |
| `CONFIG_PATH` | `/config` | `/config` | ✅ | 설정 파일과 데이터베이스 저장 경로 |

### 보안 및 인증 설정

| 환경 변수명 | 기본값 | 예시값 | 필수 | 설명 |
|------------|--------|--------|------|------|
| `AUTH_USERNAME` | - | `admin` | ❌ | 웹 인터페이스 로그인 사용자명. 미설정 시 인증 비활성화 |
| `AUTH_PASSWORD` | - | `your-secure-password` | ❌ | 웹 인터페이스 로그인 비밀번호. 강력한 비밀번호 권장 |
| `JWT_SECRET_KEY` | `auto-generated` | `your-random-secret-key` | ❌ | JWT 토큰 암호화 키. 미설정 시 자동 생성 |
| `JWT_EXPIRATION_HOURS` | `24` | `24` | ❌ | JWT 토큰 만료 시간(시간). 로그인 유지 시간 |

### 성능 및 제한 설정

| 환경 변수명 | 기본값 | 예시값 | 필수 | 설명 |
|------------|--------|--------|------|------|
| `MAX_TOTAL_DOWNLOADS` | `5` | `3` | ❌ | 전체 최대 동시 다운로드 수. 시스템 성능에 맞게 조정 |
| `MAX_LOCAL_DOWNLOADS` | `2` | `1` | ❌ | 1fichier 로컬 다운로드 최대 동시 수. 쿨다운 회피용 |
| `MAX_WEBSOCKET_CONNECTIONS` | `10` | `20` | ❌ | WebSocket 최대 연결 수. 비정상 접근 차단용 |
| `PARENT_CHECK_INTERVAL` | `5` | `10` | ❌ | 부모 프로세스 체크 간격(초). CPU 최적화용 |

### 로그 및 디버그 설정

| 환경 변수명 | 기본값 | 예시값 | 필수 | 설명 |
|------------|--------|--------|------|------|
| `LOG_LEVEL` | `WARNING` | `INFO` | ❌ | 로그 출력 레벨. `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### 1fichier 관련 설정

| 환경 변수명 | 기본값 | 예시값 | 필수 | 설명 |
|------------|--------|--------|------|------|
| `FICHIER_COOLDOWN` | `300` | `600` | ❌ | 1fichier 쿨다운 시간(초). 기본 5분, 필요시 조정 |

## 📝 설정 예시

### Synology NAS 환경

```yaml
environment:
  - TZ=Asia/Seoul
  - PUID=1026                    # Synology 사용자 ID
  - PGID=100                     # users 그룹 ID
  - AUTH_USERNAME=admin
  - AUTH_PASSWORD=secure-pass123
  - MAX_TOTAL_DOWNLOADS=3        # NAS 성능 고려
  - LOG_LEVEL=WARNING
```

### 고성능 서버 환경

```yaml
environment:
  - TZ=Asia/Seoul
  - MAX_TOTAL_DOWNLOADS=10       # 높은 동시 다운로드
  - MAX_LOCAL_DOWNLOADS=3
  - MAX_WEBSOCKET_CONNECTIONS=50
  - LOG_LEVEL=INFO
```

### 개발/테스트 환경

```yaml
environment:
  - TZ=Asia/Seoul
  - LOG_LEVEL=DEBUG              # 상세 로그
  - MAX_TOTAL_DOWNLOADS=2        # 테스트용 낮은 제한
  - JWT_EXPIRATION_HOURS=1       # 짧은 토큰 만료 시간
```

## 🛡️ 보안 권장사항

1. **인증 설정**: 외부 접근이 가능한 환경에서는 `AUTH_USERNAME`과 `AUTH_PASSWORD` 필수 설정
2. **강력한 비밀번호**: 최소 12자 이상, 대소문자/숫자/특수문자 포함
3. **JWT 시크릿**: 32자 이상의 랜덤한 문자열 사용
4. **포트 제한**: 필요한 경우에만 외부 포트 노출

## 🔍 문제 해결

### 권한 문제
- `PUID`와 `PGID`를 호스트 시스템의 사용자/그룹 ID와 일치시키세요.

### 성능 문제
- `MAX_TOTAL_DOWNLOADS`를 시스템 성능에 맞게 낮춰보세요.
- `LOG_LEVEL`을 `ERROR`로 설정하여 로그 부하를 줄이세요.

### 연결 문제
- `MAX_WEBSOCKET_CONNECTIONS`를 늘려 연결 제한을 완화하세요.
- 방화벽에서 설정한 포트가 열려있는지 확인하세요.