import math
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
    socks5_proxy_list.txt, https_proxy_list.txt 파일에서 프록시 리스트 URL을 읽고,
    각 URL에서 실제 IP:PORT만 추출해서 하나의 리스트로 반환
    """
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
    random.shuffle(proxies)
    return proxies

def is_valid_link(url: str) -> bool:
    domains = [
        '1fichier.com/', 'afterupload.com/', 'cjoint.net/', 'desfichiers.com/',
        'megadl.fr/', 'mesfichiers.org/', 'piecejointe.net/', 'pjointe.com/',
        'tenvoi.com/', 'dl4free.com/', 'ouo.io/'
    ]
    return any([x in url.lower() for x in domains]) 