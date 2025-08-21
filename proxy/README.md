# 프록시 설정 관리

이 폴더에서 프록시 서버 목록을 관리합니다.

## 파일 구조

### 메인 설정 파일
- `proxy_sources.txt` - 프록시 소스 파일들의 URL 목록 (2단계 구조)
- `direct_proxy_lists.txt` - 직접 프록시 목록 파일들의 URL

### 백업/수동 관리 파일  
- `http_proxies.txt` - HTTP/HTTPS 프록시 목록 (수동 입력용)
- `socks5_proxies.txt` - SOCKS5 프록시 목록 (수동 입력용)
- `socks4_proxies.txt` - SOCKS4 프록시 목록 (수동 입력용)

## 프록시 소스 구조

### 2단계 구조 (proxy_sources.txt)
1. `proxy_sources.txt`에 GitHub 파일 URL들을 입력
2. 각 URL의 파일에는 다른 프록시 파일들의 URL 목록이 있음  
3. 최종적으로 그 파일들에서 실제 IP:PORT를 가져옴

예시:
```
# proxy_sources.txt
https://raw.githubusercontent.com/user/repo/main/socks5_proxy_list.txt

# 위 파일의 내용:
https://raw.githubusercontent.com/other/repo/main/socks5.txt
https://raw.githubusercontent.com/another/repo/main/proxies.txt

# 최종 파일들의 내용:
192.168.1.100:8080
10.0.0.1:3128
```

### 직접 구조 (direct_proxy_lists.txt)
직접 IP:PORT가 들어있는 파일들의 URL

```
# direct_proxy_lists.txt  
https://raw.githubusercontent.com/user/repo/main/direct_proxies.txt

# 위 파일의 내용:
192.168.1.100:8080
10.0.0.1:3128
```

## 프록시 형식

### HTTP/HTTPS 프록시
```
ip:port
username:password@ip:port
```

### SOCKS 프록시
```
ip:port
username:password@ip:port  (SOCKS5만 지원)
```

## 사용법

1. **GitHub 기반 관리 (권장)**:
   - `proxy_sources.txt`에 소스 파일 URL들 추가
   - `direct_proxy_lists.txt`에 직접 프록시 파일 URL들 추가

2. **수동 관리**:
   - 각 타입별 파일에 프록시 주소를 직접 입력

3. **형식 규칙**:
   - `#`으로 시작하는 줄은 주석
   - 빈 줄은 무시됨
   - 한 줄에 하나의 URL 또는 프록시 주소

## 주의사항

- 프록시 서버의 가용성을 주기적으로 확인하세요
- 신뢰할 수 있는 프록시만 사용하세요
- GitHub 파일이 업데이트되면 자동으로 새로운 프록시 목록이 적용됩니다