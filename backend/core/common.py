import math
import os
import random
import requests
import cloudscraper

def convert_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return '0 B'
    size_name = ('B', 'KB', 'MB', 'GB', 'TB')
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return '%s %s' % (s, size_name[i])

def get_all_proxies():
    """
    GitHub raw URL에서 실시간으로 프록시 목록을 가져오는 함수
    2단계 구조 지원: 소스 파일들 → 프록시 URL 목록 → 실제 IP:PORT
    """
    import pathlib
    
    # GitHub raw URL들 (실시간 반영)
    github_config_urls = [
        'https://raw.githubusercontent.com/jshsakura/oc-proxy-downloader/main/proxy/proxy_sources.txt',
        'https://raw.githubusercontent.com/jshsakura/oc-proxy-downloader/main/proxy/direct_proxy_lists.txt'
    ]
    
    # 백업으로 로컬 파일도 시도
    current_dir = pathlib.Path(__file__).parent.parent.parent
    proxy_dir = current_dir / "proxy"
    
    proxy_source_files = []
    direct_proxy_files = []
    scraper = cloudscraper.create_scraper()
    
    # 1. GitHub에서 proxy_sources.txt 읽기 시도
    try:
        proxy_sources_url = 'https://raw.githubusercontent.com/jshsakura/oc-proxy-downloader/main/proxy/proxy_sources.txt'
        resp = scraper.get(proxy_sources_url, timeout=10)
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    proxy_source_files.append(line)
            print(f"[LOG] GitHub에서 proxy_sources.txt 로드 성공: {len(proxy_source_files)}개")
        else:
            raise Exception(f"HTTP {resp.status_code}")
    except Exception as e:
        print(f"[LOG] GitHub proxy_sources.txt 로드 실패, 로컬 파일 시도: {e}")
        # 백업: 로컬 파일 읽기
        proxy_sources_file = proxy_dir / "proxy_sources.txt"
        if proxy_sources_file.exists():
            try:
                with open(proxy_sources_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            proxy_source_files.append(line)
                print(f"[LOG] 로컬 proxy_sources.txt 로드 성공: {len(proxy_source_files)}개")
            except Exception as e2:
                print(f"[LOG] 로컬 proxy_sources.txt 읽기 실패: {e2}")
    
    # 2. GitHub에서 direct_proxy_lists.txt 읽기 시도
    try:
        direct_proxy_url = 'https://raw.githubusercontent.com/jshsakura/oc-proxy-downloader/main/proxy/direct_proxy_lists.txt'
        resp = scraper.get(direct_proxy_url, timeout=10)
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    direct_proxy_files.append(line)
            print(f"[LOG] GitHub에서 direct_proxy_lists.txt 로드 성공: {len(direct_proxy_files)}개")
        else:
            raise Exception(f"HTTP {resp.status_code}")
    except Exception as e:
        print(f"[LOG] GitHub direct_proxy_lists.txt 로드 실패, 로컬 파일 시도: {e}")
        # 백업: 로컬 파일 읽기
        direct_proxy_file = proxy_dir / "direct_proxy_lists.txt"
        if direct_proxy_file.exists():
            try:
                with open(direct_proxy_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            direct_proxy_files.append(line)
                print(f"[LOG] 로컬 direct_proxy_lists.txt 로드 성공: {len(direct_proxy_files)}개")
            except Exception as e2:
                print(f"[LOG] 로컬 direct_proxy_lists.txt 읽기 실패: {e2}")
    
    # 백업: 아무것도 없으면 기존 하드코딩된 URL 사용
    if not proxy_source_files and not direct_proxy_files:
        print("[LOG] 모든 설정 파일 로드 실패, 기본 하드코딩된 URL 사용")
        proxy_source_files = [
            'https://raw.githubusercontent.com/jshsakura/1fichier-dl/main/socks5_proxy_list.txt',
            'https://raw.githubusercontent.com/jshsakura/1fichier-dl/main/https_proxy_list.txt'
        ]
    
    proxies = []
    scraper = cloudscraper.create_scraper()
    proxy_list_urls = []
    
    # 1차: 프록시 소스 파일에서 프록시 리스트 URL 추출
    for file_url in proxy_source_files:
        try:
            resp = scraper.get(file_url, timeout=10)
            for line in resp.text.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    proxy_list_urls.append(line)
        except Exception as e:
            print(f"[LOG] 프록시 소스 파일 {file_url} 에서 URL 추출 실패: {e}")
            continue
    
    # 직접 프록시 파일들도 추가
    proxy_list_urls.extend(direct_proxy_files)
    
    # 2차: 각 프록시 리스트 URL에서 실제 IP:PORT 추출
    for url in proxy_list_urls:
        try:
            resp = scraper.get(url, timeout=10)
            for line in resp.text.splitlines():
                line = line.strip()
                if line and not line.startswith('#') and ':' in line:
                    parts = line.split(':')
                    if len(parts) == 2 and all(part for part in parts):
                        proxies.append(line)
        except Exception as e:
            print(f"[LOG] 프록시 리스트 {url} 에서 IP:PORT 추출 실패: {e}")
            continue
    
    # 중복 제거
    proxies = list(set(proxies))
    random.shuffle(proxies)
    print(f"[LOG] 총 {len(proxies)}개의 고유 프록시 발견 (소스: {len(proxy_source_files)}개, 직접: {len(direct_proxy_files)}개)")
    return proxies

def is_valid_link(url: str) -> bool:
    domains = [
        '1fichier.com/', 'afterupload.com/', 'cjoint.net/', 'desfichiers.com/',
        'megadl.fr/', 'mesfichiers.org/', 'piecejointe.net/', 'pjointe.com/',
        'tenvoi.com/', 'dl4free.com/', 'ouo.io/'
    ]
    return any([x in url.lower() for x in domains]) 