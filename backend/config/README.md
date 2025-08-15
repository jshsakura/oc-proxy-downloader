# Backend Configuration Directory

이 폴더는 백엔드 설정 파일과 데이터베이스를 저장하는 통합 디렉토리입니다.

## 포함 파일들

- `config.json` - 애플리케이션 설정 파일
- `downloads.db` - SQLite 데이터베이스 파일

## Docker 환경

Docker Compose에서 이 폴더는 컨테이너의 `/config` 경로에 마운트됩니다:

```yaml
volumes:
  - ./backend/config:/config
```

## 환경 변수

- `CONFIG_PATH=/config` - 설정 및 DB 파일 경로
- `DOWNLOAD_PATH=/app/backend/downloads` - 다운로드 파일 저장 경로

## 주의사항

- 이 폴더의 파일들은 `.gitignore`에 포함되어 있어 Git에 커밋되지 않습니다
- 설정 파일이 없으면 기본값으로 자동 생성됩니다