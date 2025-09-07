# -*- coding: utf-8 -*-
"""
1fichier.com 파싱 모듈
사이트 구조 변경에 대응하는 유연한 파싱 시스템
"""

import re
import lxml.html
from urllib.parse import urljoin, urlparse
import logging

logger = logging.getLogger(__name__)

class FichierParser:
    """1fichier.com 다운로드 링크 파싱 클래스"""
    
    # 2025년 실제 1fichier 구조 기반 선택자 (실제 테스트된 패턴)
    DOWNLOAD_SELECTORS = [
        # 현재 1fichier에서 실제 사용하는 구조 (2025년 1월 기준)
        '//*[@id="dlw"]',  # 주요 다운로드 버튼 (실제 확인됨)
        '//form[@id="f1"]',  # 다운로드 폼 (POST 방식)
        
        # 실제 다운로드 링크가 생성되는 경우의 패턴들
        '//a[contains(@href, "://") and contains(@href, ".1fichier.com/") and string-length(@href) > 40]',
        
        # 서버별 다운로드 패턴 (간소화)
        '//a[contains(@href, "://cdn-") and contains(@href, ".1fichier.com/")]',  # CDN 서버
        '//a[contains(@href, "://a-") and contains(@href, ".1fichier.com/")]',    # a-서버들
        '//a[contains(@href, "://s") and contains(@href, ".1fichier.com/")]',     # s숫자 서버들
        
        # 백업 선택자들 (이전 구조 대비)
        '//a[@href and string-length(@href) > 50 and contains(@href, "1fichier")]'
        
        # 최신 1fichier 구조 (2024년 기준)
        '//a[contains(@class, "ok btn-general")]',
        '//a[contains(@class, "btn-general") and contains(@href, "cdn-")]',
        '//div[@class="ct_warn"]//a[contains(@href, "http")]',
        
        # 기존 XPath (여전히 유효할 수 있음)
        '/html/body/div[4]/div[2]/a',
        '/html/body/div[3]/div[2]/a',
        '/html/body/div[5]/div[2]/a',
        '/html/body/div[6]/div[2]/a',
        
        # 동적 컨테이너 기반
        '//div[contains(@class, "content")]//a[contains(@href, "cdn-")]',
        '//div[contains(@class, "download")]//a[contains(@href, "http")]',
        
        # CSS 선택자들 (우선순위 높음)
        'a[href*="cdn-"][href*=".1fichier.com"]',  # CDN 링크 (가장 확실)
        'a[href*="download.1fichier.com"]',  # 다운로드 서버
        'a[href*="cdn-"]',  # CDN 링크
        'a[href*="download"]',  # download가 포함된 링크
        'a[href*=".1fichier.com"][href*="?"]',  # 1fichier 도메인 + 쿼리
        
        # 클래스 기반 선택자
        '.btn-download',
        '.download-link',
        '.btn-general',
        '.ok',
        
        # 텍스트 기반 선택자 (다국어 지원)
        '//a[contains(text(), "다운로드")]',
        '//a[contains(text(), "Download")]',
        '//a[contains(text(), "DOWNLOAD")]',
        '//a[contains(text(), "Télécharger")]',
        '//a[contains(text(), "Descargar")]',
        '//a[contains(text(), "ダウンロード")]',
        
        # 버튼 패턴들
        '//a[contains(@class, "btn") and contains(@href, "http")]',
        '//button[@onclick and contains(@onclick, "location")]/..//a',
        '//a[contains(@onclick, "download")]',
        '//a[contains(@onclick, "location")]',
        
        # 폼 관련
        '//form//a[contains(@href, "http")]',
        '//form[@method="get"]//a',
        
        # 메타 리프레시 패턴
        '//meta[@http-equiv="refresh" and contains(@content, "url=")]',
        
        # JavaScript 패턴들
        '//script[contains(text(), "location.href") or contains(text(), "window.location")]',
        
        # 마지막 수단: 모든 외부 링크 (문제 페이지들 제외)
        '//a[contains(@href, "http") and (contains(@href, ".") or contains(@href, "download")) and not(contains(@href, "cgu")) and not(contains(@href, "cgv")) and not(contains(@href, "console")) and not(contains(@href, "tarifs")) and not(contains(@href, "revendeurs")) and not(contains(@href, "network")) and not(contains(@href, "hlp")) and not(contains(@href, "abus")) and not(contains(@href, "register")) and not(contains(@href, "login")) and not(contains(@href, "contact")) and not(contains(@href, "premium"))]'
    ]
    
    # 다운로드 링크 검증을 위한 패턴들 (우선순위 순)
    VALID_LINK_PATTERNS = [
        r'https?://cdn-\d+\.1fichier\.com/',  # CDN 링크 (최우선)
        r'https?://a-\d+\.1fichier\.com/',  # a-숫자 패턴 링크 (최우선)
        r'https?://[a-z]-\d+\.1fichier\.com/',  # x-숫자 패턴 링크 (최우선)
        r'https?://[^/]*download[^/]*/',  # download가 포함된 도메인
        r'https?://[^/]*\.1fichier\.com/[a-zA-Z0-9_\-]{10,}',  # 서브도메인 + 긴 경로
    ]
    
    # 제외할 링크 패턴들 (강화됨)
    EXCLUDE_PATTERNS = [
        r'javascript:',
        r'#',
        r'mailto:',
        r'/premium',
        r'/register',
        r'/login',
        r'/contact',
        r'/help',
        r'/faq',
        r'/console/abo\.pl',    # 프리미엄 결제 페이지
        r'/tarifs',             # 요금제 페이지
        r'/console/',           # 콘솔 페이지들
        r'/cgu\.html',          # 이용약관 페이지 ⭐ 핵심 문제
        r'/cgv\.html',          # 판매약관 페이지
        r'/mentions\.html',     # 법적고지 페이지
        r'/privacy\.html',      # 개인정보보호 페이지
        r'/about\.html',        # 회사소개 페이지
        r'cgu\.html$',          # 이용약관 파일명 (경로 없이)
        r'cgv\.html$',          # 판매약관 파일명
        r'mentions\.html$',     # 법적고지 파일명
        r'privacy\.html$',      # 개인정보보호 파일명
        r'about\.html$',        # 회사소개 파일명
        r'1fichier\.com/cgu',   # 1fichier 도메인의 cgu 관련
        r'1fichier\.com/cgv',   # 1fichier 도메인의 cgv 관련
        r'1fichier\.com/mentions', # 1fichier 도메인의 mentions 관련
        r'1fichier\.com/privacy',  # 1fichier 도메인의 privacy 관련
        r'1fichier\.com/about',    # 1fichier 도메인의 about 관련
        r'1fichier\.com/tarifs',   # 1fichier 도메인의 tarifs 관련
        r'1fichier\.com/premium',  # 1fichier 도메인의 premium 관련
        r'1fichier\.com/console',  # 1fichier 도메인의 console 관련
        r'1fichier\.com/register', # 1fichier 도메인의 register 관련
        r'1fichier\.com/login',    # 1fichier 도메인의 login 관련
        r'1fichier\.com/help',     # 1fichier 도메인의 help 관련
        r'1fichier\.com/faq',      # 1fichier 도메인의 faq 관련
        r'1fichier\.com/contact',  # 1fichier 도메인의 contact 관련
        r'1fichier\.com/abus',     # 1fichier 도메인의 abus 관련 (신고)
        r'1fichier\.com/hlp',      # 1fichier 도메인의 help 관련
        r'1fichier\.com/revendeurs', # 리셀러 페이지
        r'/revendeurs\.html',      # 리셀러 페이지
        r'revendeurs\.html$',      # 리셀러 파일명
        r'1fichier\.com/network',  # 네트워크 페이지
        r'/network\.html',         # 네트워크 페이지
        r'network\.html$',         # 네트워크 파일명
        r'/abus\.html',            # 신고 페이지
        r'/hlp\.html',             # 도움말 페이지
        r'abus\.html$',            # 신고 파일명 (경로 없이)
        r'hlp\.html$',             # 도움말 파일명 (경로 없이)
        r'/abus\.html$',           # 신고 페이지 (전체 경로)
        r'/hlp\.html$',            # 도움말 페이지 (전체 경로)
        r'1fichier\.com/abus\.html', # 1fichier 도메인의 abus.html (신고)
        r'1fichier\.com/hlp\.html',  # 1fichier 도메인의 hlp.html (도움말)
        r'1fichier\.com/?$',       # 1fichier 메인 페이지 (파일이 아님)
        r'https?://1fichier\.com/?$', # 1fichier 메인 페이지 (전체 URL)
        r'https?://img\.1fichier\.com/', # 이미지 서버 (logo-footer 등)
        r'/logo-footer',           # 로고 이미지
        r'logo-footer$',           # 로고 이미지 파일명
        r'/api\.html',             # API 문서 페이지
        r'api\.html$',             # API 문서 파일명
        r'1fichier\.com/api\.html', # 1fichier API 문서 페이지
    ]
    
    def __init__(self):
        self.session_cookies = {}
    
    def parse_download_link(self, html_content, base_url=None):
        """
        HTML 콘텐츠에서 다운로드 링크를 추출
        
        Args:
            html_content (str): HTML 콘텐츠
            base_url (str): 기본 URL (상대 링크 해결용)
            
        Returns:
            str: 다운로드 링크 또는 None
        """
        try:
            print(f"[DEBUG] 파싱 시작 - HTML 길이: {len(html_content)} 문자")
            
            # 1fichier 대기시간 체크 (기존 방식과 동일하게 처리)
            if 'Free download in' in html_content:
                import re
                # 16분 대기시간 체크
                wait_match = re.search(r'Free download in.*?(\d+)\s*minutes?', html_content, re.IGNORECASE)
                if wait_match:
                    wait_minutes = int(wait_match.group(1))
                    wait_seconds = wait_minutes * 60  # 분을 초로 변환
                    print(f"[LOG] 1fichier 대기시간 감지: {wait_minutes}분 ({wait_seconds}초)")
                    
                    # 5분 이상 대기시간일 때 텔레그램 알림 (로컬 다운로드만)
                    if wait_minutes >= 5:
                        try:
                            from .download_core import send_telegram_wait_notification
                            # DB에서 실제 파일명 가져오기
                            from .db import SessionLocal
                            from .models import DownloadRequest
                            
                            with SessionLocal() as db:
                                req = db.query(DownloadRequest).filter(DownloadRequest.url == url).first()
                                file_name = req.file_name if req and req.file_name else "1fichier File"
                            
                            send_telegram_wait_notification(file_name, wait_minutes, "ko")
                        except Exception as e:
                            print(f"[WARN] 텔레그램 대기시간 알림 실패: {e}")
                    
                    return None  # 기존 방식대로 None 반환하여 대기시간 처리 위임
            
            # 우선 정규식으로 직접 다운로드 링크 패턴 검색
            print(f"[DEBUG] 정규식 패턴 검색 시작...")
            download_patterns = [
                r'https?://a-\d+\.1fichier\.com/[a-zA-Z0-9_\-/]+',     # a-숫자.1fichier.com/해시
                r'https?://cdn-\d+\.1fichier\.com/[a-zA-Z0-9_\-/]+',   # cdn-숫자.1fichier.com/해시
                r'https?://[a-z]-\d+\.1fichier\.com/[a-zA-Z0-9_\-/]{8,}', # 일반적 패턴
                r'https?://[a-z]\d+\.1fichier\.com/[a-zA-Z0-9_\-/]{8,}', # s17.1fichier.com 등
                r'https?://\w+\d+\.1fichier\.com/[a-zA-Z0-9_\-/]{10,}', # 모든 서브도메인+숫자
                r'https://[^"\'>\s]*\.1fichier\.com/[^"\'>\s]{15,}',   # 서브도메인 + 긴 경로
            ]
            
            for i, pattern in enumerate(download_patterns):
                matches = re.findall(pattern, html_content, re.IGNORECASE)
                print(f"[DEBUG] 정규식 패턴 {i+1} ({pattern}) 검색 결과: {len(matches) if matches else 0}개")
                if matches:
                    print(f"[DEBUG] 정규식 패턴 {i+1} 매칭: {matches}")
                    for match in matches:
                        print(f"[DEBUG] 링크 검증 중: {match}")
                        # 검증
                        if self._is_valid_download_link(match):
                            print(f"[LOG] 정규식으로 발견된 다운로드 링크: {match}")
                            return match
                        else:
                            print(f"[DEBUG] 링크 검증 실패: {match}")
            
            print(f"[DEBUG] 모든 정규식 패턴에서 유효한 다운로드 링크를 찾지 못함")
            
            # JavaScript 리다이렉트나 동적 생성 링크 확인
            js_patterns = [
                r'window\.location\s*=\s*["\']([^"\']+)["\']',
                r'location\.href\s*=\s*["\']([^"\']+)["\']',
                r'document\.location\s*=\s*["\']([^"\']+)["\']',
                r'location\.replace\s*\(\s*["\']([^"\']+)["\']\s*\)',
                r'window\.open\s*\(\s*["\']([^"\']+)["\']\s*\)',
            ]
            
            for pattern in js_patterns:
                js_matches = re.findall(pattern, html_content, re.IGNORECASE)
                for js_match in js_matches:
                    if '1fichier.com' in js_match and len(js_match) > 30:
                        print(f"[DEBUG] JavaScript 리다이렉트 발견: {js_match}")
                        if self._is_valid_download_link(js_match):
                            print(f"[LOG] JavaScript에서 발견된 다운로드 링크: {js_match}")
                            return js_match
            
            # Meta refresh 확인
            meta_refresh = re.findall(r'<meta[^>]*http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*url=([^"\']+)["\']', html_content, re.IGNORECASE)
            for meta_url in meta_refresh:
                if '1fichier.com' in meta_url and len(meta_url) > 30:
                    print(f"[DEBUG] Meta refresh 발견: {meta_url}")
                    if self._is_valid_download_link(meta_url):
                        print(f"[LOG] Meta refresh에서 발견된 다운로드 링크: {meta_url}")
                        return meta_url
            
            # HTML 파싱
            doc = lxml.html.fromstring(html_content)
            
            # 모든 링크 수집 (디버깅용)
            all_links = doc.xpath('//a[@href]')
            print(f"[DEBUG] 전체 링크 수: {len(all_links)}")
            
            # 특별히 a-숫자 패턴 링크들 확인
            a_pattern_links = [a.get('href') for a in all_links if a.get('href') and 'a-' in a.get('href')]
            if a_pattern_links:
                print(f"[DEBUG] a-숫자 패턴 링크들:")
                for link in a_pattern_links:
                    print(f"[DEBUG]   {link}")
            
            # cgu.html 같은 문제 링크들 확인
            problem_links = [a.get('href') for a in all_links if a.get('href') and any(x in a.get('href').lower() for x in ['cgu.html', 'tarifs', 'console'])]
            if problem_links:
                print(f"[DEBUG] 문제 링크들 (제외되어야 함):")
                for link in problem_links:
                    print(f"[DEBUG]   {link}")
            
            # 각 선택자를 순서대로 시도
            for i, selector in enumerate(self.DOWNLOAD_SELECTORS):
                try:
                    links = self._extract_links_by_selector(doc, selector)
                    print(f"[DEBUG] 선택자 {i+1}: '{selector}' -> {len(links)}개 링크")
                    
                    for link in links:
                        print(f"[DEBUG]   후보 링크: {link}")
                        
                        # 상대 링크를 절대 링크로 변환
                        if base_url and not link.startswith('http'):
                            link = urljoin(base_url, link)
                        
                        # 링크 검증
                        if self._is_valid_download_link(link):
                            print(f"[LOG] OK 다운로드 링크 발견 (선택자 {i+1}: {selector}): {link}")
                            return link
                        else:
                            print(f"[DEBUG]   FAIL 링크 검증 실패: {link}")
                            
                except Exception as e:
                    print(f"[DEBUG] 선택자 {selector} 실행 중 오류: {e}")
                    continue
            
            # 모든 선택자가 실패한 경우, 휴리스틱 방법 시도
            print(f"[DEBUG] 모든 선택자 실패 - 휴리스틱 방법 시도")
            fallback_link = self._heuristic_link_extraction(doc, base_url)
            if fallback_link:
                print(f"[LOG] 휴리스틱 방법으로 링크 발견: {fallback_link}")
                return fallback_link
            
            print(f"[ERROR] 다운로드 링크를 찾을 수 없습니다")
            return None
            
        except Exception as e:
            print(f"[ERROR] HTML 파싱 중 오류: {e}")
            return None
    
    def _extract_links_by_selector(self, doc, selector):
        """선택자를 사용하여 링크 추출"""
        links = []
        
        try:
            if selector.startswith('//') or selector.startswith('/html'):
                # XPath 선택자
                elements = doc.xpath(selector)
            else:
                # CSS 선택자
                elements = doc.cssselect(selector)
            
            for element in elements:
                href = element.get('href')
                if href:
                    links.append(href)
                    
        except Exception as e:
            logger.debug(f"선택자 {selector} 처리 중 오류: {e}")
        
        return links
    
    def _is_valid_download_link(self, link):
        """다운로드 링크 유효성 검증"""
        if not link or not isinstance(link, str):
            print(f"[DEBUG] 링크 검증 실패: 빈 링크 또는 잘못된 타입")
            return False
        
        print(f"[DEBUG] 링크 검증 중: {link}")
        
        # 제외 패턴 확인 (먼저 체크)
        for pattern in self.EXCLUDE_PATTERNS:
            if re.search(pattern, link, re.IGNORECASE):
                print(f"[DEBUG] 제외 패턴 매칭: {pattern} -> {link}")
                return False
        
        # 확실히 제외해야 할 키워드들 (강화됨)
        exclude_keywords = [
            'cgu.html', 'cgv.html', 'mentions.html', 'privacy.html', 'about.html',
            'abus.html', 'hlp.html',  # 신고, 도움말 페이지
            'premium', 'console', 'register', 'login', 'help', 'contact', 'faq', 'tarifs',
            '/cgu', '/cgv', '/mentions', '/privacy', '/about', '/tarifs', '/premium',
            '/console', '/register', '/login', '/help', '/contact', '/faq', '/abus', '/hlp',
            '1fichier.com/cgu', '1fichier.com/cgv', '1fichier.com/mentions', 
            '1fichier.com/privacy', '1fichier.com/about', '1fichier.com/tarifs',
            '1fichier.com/premium', '1fichier.com/console', '1fichier.com/register',
            '1fichier.com/login', '1fichier.com/help', '1fichier.com/contact', '1fichier.com/faq',
            '1fichier.com/abus', '1fichier.com/hlp',  # 신고, 도움말 관련
            'img.1fichier.com', 'logo-footer',  # 이미지 서버와 로고
            'api.html', '1fichier.com/api.html'  # API 문서 페이지
        ]
        for keyword in exclude_keywords:
            if keyword in link.lower():
                print(f"[DEBUG] 제외 키워드 발견: {keyword} -> {link}")
                return False
        
        # CDN 링크는 최우선 허용
        if 'cdn-' in link and '.1fichier.com' in link:
            print(f"[DEBUG] OK CDN 링크 허용: {link}")
            return True
        
        # a-숫자 패턴 링크 허용 (실제 다운로드 링크)
        if re.search(r'https?://[a-z]-\d+\.1fichier\.com/', link):
            print(f"[DEBUG] OK a-숫자 패턴 링크 허용: {link}")
            return True
        
        # 다운로드 전용 도메인들
        download_domains = ['download.1fichier.com', 'dl.1fichier.com', 'static.1fichier.com']
        for domain in download_domains:
            if domain in link:
                print(f"[DEBUG] OK 다운로드 도메인 허용: {domain} -> {link}")
                return True
        
        # 원본 1fichier URL은 절대 허용하지 않음 (다운로드 링크가 아님)
        if re.match(r'https?://1fichier\.com/\?[a-zA-Z0-9]+$', link):
            print(f"[DEBUG] FAIL 원본 1fichier URL 제외 (다운로드 링크 아님): {link}")
            return False
        
        # 유효한 패턴 확인 (우선순위 순)
        for pattern in self.VALID_LINK_PATTERNS:
            if re.search(pattern, link, re.IGNORECASE):
                print(f"[DEBUG] OK 유효한 패턴 매칭: {pattern} -> {link}")
                return True
        
        # HTTP/HTTPS 링크이고 쿼리 파라미터가 있는 경우 (파일 다운로드 링크일 가능성)
        if link.startswith('http') and '?' in link and 'download' in link.lower():
            print(f"[DEBUG] OK 쿼리 파라미터 있는 다운로드 링크: {link}")
            return True
        
        # HTTP/HTTPS 링크이고 파일 확장자가 있는 경우 (단, 1fichier 메인 도메인은 제외)
        if link.startswith('http') and '.' in link.split('/')[-1]:
            # 1fichier 메인 도메인은 제외 (파일이 아님)
            if link.strip('/') in ['https://1fichier.com', 'http://1fichier.com']:
                print(f"[DEBUG] FAIL 1fichier 메인 도메인 제외: {link}")
                return False
            print(f"[DEBUG] OK 파일 확장자 있는 링크: {link}")
            return True
        
        print(f"[DEBUG] FAIL 링크 검증 실패: {link}")
        return False
    
    def _heuristic_link_extraction(self, doc, base_url):
        """휴리스틱 방법으로 다운로드 링크 추출"""
        try:
            # 1단계: JavaScript에서 링크 추출
            js_link = self._extract_from_javascript(doc, base_url)
            if js_link:
                logger.info(f"JavaScript에서 링크 발견: {js_link}")
                return js_link
            
            # 2단계: 메타 리프레시에서 링크 추출
            meta_link = self._extract_from_meta_refresh(doc, base_url)
            if meta_link:
                logger.info(f"메타 리프레시에서 링크 발견: {meta_link}")
                return meta_link
            
            # 3단계: 모든 링크 수집 및 점수 계산
            all_links = []
            
            # href 속성이 있는 모든 a 태그
            for a in doc.xpath('//a[@href]'):
                href = a.get('href')
                if href:
                    # 상대 링크를 절대 링크로 변환
                    if base_url and not href.startswith('http'):
                        href = urljoin(base_url, href)
                    all_links.append((href, a))
            
            # 링크 점수 계산 및 정렬
            scored_links = []
            for link, element in all_links:
                score = self._calculate_link_score(link, element)
                if score > 0:
                    scored_links.append((score, link))
            
            # 점수 순으로 정렬
            scored_links.sort(reverse=True)
            
            # 가장 높은 점수의 링크 반환 (추가 검증)
            for score, link in scored_links:
                print(f"[DEBUG] 휴리스틱 후보 링크 검토: 점수={score}, 링크={link}")
                if self._is_valid_download_link(link):
                    # 최종 안전 검사 - 문제 링크들 차단
                    bad_links = ['cgu.html', 'cgv.html', 'mentions.html', 'privacy.html', 'about.html', 'abus.html', 'hlp.html', 'api.html']
                    if any(bad in link.lower() for bad in bad_links):
                        print(f"[DEBUG] 휴리스틱에서 문제 링크 차단: {link}")
                        continue
                    print(f"[DEBUG] 휴리스틱 최종 선택: {link}")
                    return link
            
        except Exception as e:
            logger.error(f"휴리스틱 링크 추출 중 오류: {e}")
        
        return None
    
    def _extract_from_javascript(self, doc, base_url):
        """JavaScript 코드에서 다운로드 링크 추출"""
        try:
            # 모든 script 태그 찾기
            scripts = doc.xpath('//script/text()')
            
            # 더 포괄적인 JavaScript 패턴들
            js_patterns = [
                r'window\.location\s*=\s*[\'"]([^\'"]+)[\'"]',
                r'document\.location\s*=\s*[\'"]([^\'"]+)[\'"]',
                r'location\.href\s*=\s*[\'"]([^\'"]+)[\'"]',
                r'var\s+download_url\s*=\s*[\'"]([^\'"]+)[\'"]',
                r'var\s+url\s*=\s*[\'"]([^\'"]+)[\'"]',
                r'setTimeout\s*\(\s*function\s*\(\)\s*\{\s*location\s*=\s*[\'"]([^\'"]+)[\'"]',
                r'href\s*=\s*[\'"]([^\'"]*cdn-[^\'"]*)[\'"]',
                r'href\s*=\s*[\'"]([^\'"]*a-\d+[^\'"]*)[\'"]',  # a-숫자 패턴
                r'[\'"]https://[a-z]-\d+\.1fichier\.com/[^\'"]*[\'"]',  # 직접 URL 패턴
                r'submit\(\)\s*\}\s*\}\s*[;\s]*[\'"]([^\'"]*a-\d+[^\'"]*)[\'"]',  # submit 후 URL
                r'\.click\(.*?\)\s*\}\s*\}\s*[;\s]*[\'"]([^\'"]*a-\d+[^\'"]*)[\'"]',  # click 후 URL
            ]
            
            print(f"[DEBUG] JavaScript 링크 추출 시작 - {len(scripts)}개 스크립트")
            
            for i, script_content in enumerate(scripts):
                if script_content:
                    print(f"[DEBUG] Script {i+1} 분석 중... (길이: {len(script_content)})")
                    
                    # a-숫자 패턴 직접 검색
                    a_pattern_matches = re.findall(r'https://[a-z]-\d+\.1fichier\.com/[^\s\'"<>]+', script_content)
                    if a_pattern_matches:
                        print(f"[DEBUG] Script에서 a-패턴 발견: {a_pattern_matches}")
                        for match in a_pattern_matches:
                            if self._is_valid_download_link(match):
                                print(f"[DEBUG] JavaScript에서 a-패턴 링크 발견: {match}")
                                return match
                    
                    # 기존 패턴들도 시도
                    for pattern in js_patterns:
                        matches = re.findall(pattern, script_content, re.IGNORECASE)
                        for match in matches:
                            # 상대 링크를 절대 링크로 변환
                            if base_url and not match.startswith('http'):
                                match = urljoin(base_url, match)
                            
                            if self._is_valid_download_link(match):
                                print(f"[DEBUG] JavaScript 패턴 매칭: {pattern} -> {match}")
                                return match
            
        except Exception as e:
            print(f"[DEBUG] JavaScript 링크 추출 중 오류: {e}")
        
        return None
    
    def _extract_from_meta_refresh(self, doc, base_url):
        """메타 리프레시 태그에서 링크 추출"""
        try:
            # 메타 리프레시 태그 찾기
            meta_refreshes = doc.xpath('//meta[@http-equiv="refresh"]/@content')
            
            for content in meta_refreshes:
                # url= 부분 추출
                match = re.search(r'url=([^;\'"\s]+)', content, re.IGNORECASE)
                if match:
                    url = match.group(1)
                    
                    # 상대 링크를 절대 링크로 변환
                    if base_url and not url.startswith('http'):
                        url = urljoin(base_url, url)
                    
                    if self._is_valid_download_link(url):
                        return url
            
        except Exception as e:
            logger.debug(f"메타 리프레시 링크 추출 중 오류: {e}")
        
        return None
    
    def _calculate_link_score(self, link, element):
        """링크의 다운로드 가능성 점수 계산"""
        score = 0
        
        # URL 기반 점수 (우선순위 높음)
        if 'cdn-' in link and '1fichier.com' in link:
            score += 100  # CDN 링크는 최고 점수
        elif 'download' in link.lower() and '1fichier.com' in link:
            score += 80   # 다운로드 서버 링크
        elif '1fichier.com' in link:
            score += 30   # 일반 1fichier 링크
        
        # 제외할 링크들에 대한 강한 페널티 (강화됨)
        exclude_keywords = [
            'console', 'abo', 'premium', 'register', 'login', 'help', 'contact', 'faq', 'tarifs',
            'cgu.html', 'cgv.html', 'mentions.html', 'privacy.html', 'about.html',
            'abus.html', 'hlp.html',  # 신고, 도움말 페이지
            '/cgu', '/cgv', '/mentions', '/privacy', '/about', '/tarifs', '/premium',
            '/console', '/register', '/login', '/help', '/contact', '/faq', '/abus', '/hlp',
            '1fichier.com/cgu', '1fichier.com/cgv', '1fichier.com/mentions',
            '1fichier.com/privacy', '1fichier.com/about', '1fichier.com/tarifs',
            '1fichier.com/premium', '1fichier.com/console', '1fichier.com/abus', '1fichier.com/hlp',
            'api.html', '1fichier.com/api.html'  # API 문서 페이지
        ]
        for keyword in exclude_keywords:
            if keyword in link.lower():
                score -= 1000  # 매우 큰 페널티로 확실히 제외
        
        if link.startswith('https://'):
            score += 10
        
        # 요소 속성 기반 점수
        class_attr = element.get('class', '').lower()
        if 'btn' in class_attr:
            score += 15
        if 'download' in class_attr:
            score += 25
        if 'primary' in class_attr or 'success' in class_attr:
            score += 10
        
        # 텍스트 기반 점수
        text = (element.text or '').lower().strip()
        if text in ['download', '다운로드', 'télécharger']:
            score += 30
        if 'download' in text:
            score += 20
        
        # 부모 요소 확인
        parent = element.getparent()
        if parent is not None:
            parent_class = parent.get('class', '').lower()
            if 'download' in parent_class:
                score += 15
        
        return score
    
    def extract_file_info(self, html_content):
        """HTML에서 파일 정보 추출"""
        try:
            doc = lxml.html.fromstring(html_content)
            
            file_info = {
                'name': None,
                'size': None,
                'type': None
            }
            
            # 파일명 추출 시도 (단순하고 확실한 방법)
            name_selectors = [
                # 가장 확실한: 볼드체 스팬 중에서 점이 있는 것 (파일명)
                '//span[@style="font-weight:bold"]/text()',
                # 테이블 내의 볼드체
                '//table//span[@style="font-weight:bold"]/text()',
                # td.normal 내의 볼드체
                '//td[@class="normal"]//span[@style="font-weight:bold"]/text()',
                # 메타 태그 백업
                '//meta[@property="og:title"]/@content',
                '//title/text()'
            ]
            
            for selector in name_selectors:
                try:
                    texts = doc.xpath(selector)
                    for text in texts:
                        # JSON-LD 데이터 처리
                        if 'json' in selector.lower():
                            try:
                                import json
                                data = json.loads(text)
                                if isinstance(data, dict) and 'name' in data:
                                    text = data['name']
                                else:
                                    continue
                            except:
                                continue
                        
                        text = text.strip()
                        # 기본적인 파일명 검증 (최소한의 필터링만)
                        if text and len(text) > 3 and len(text) < 200:
                            # 명확한 프로모션/광고 텍스트만 제외 (매우 제한적)
                            obvious_ads = [
                                '1fichier.com !',  # 정확한 프로모션 문구
                                'started on 1fichier.com',  # 정확한 프로모션 문구
                                'http://', 'https://',  # URL 포함
                                '€', '$',  # 가격 표시
                            ]
                            
                            # 명백한 광고 텍스트만 제외
                            if any(ad in text for ad in obvious_ads):
                                print(f"[DEBUG] 명백한 광고 텍스트 제외: {text}")
                                continue
                            
                            # 점이 있는 텍스트면 파일명으로 인정 (확장자 제한 없음)
                            if '.' in text:
                                # 타이틀에서 온 경우 정리
                                if 'title' in selector.lower():
                                    # "filename - 1fichier.com" 형태에서 파일명만 추출
                                    text = re.sub(r'\s*-\s*1fichier\.com.*$', '', text, flags=re.IGNORECASE)
                                    text = re.sub(r'\s*\|\s*1fichier.*$', '', text, flags=re.IGNORECASE)
                                
                                file_info['name'] = text.strip()
                                print(f"[DEBUG] ★ 파일명 추출 성공: '{file_info['name']}' (선택자: {selector})")
                                print(f"[DEBUG] ★ 추출된 파일명 길이: {len(file_info['name'])} 문자")
                                print(f"[DEBUG] ★ 추출된 파일명 타입: {type(file_info['name'])}")
                                break
                    if file_info['name']:
                        break
                except Exception as e:
                    print(f"[DEBUG] 선택자 '{selector}' 실패: {e}")
                    continue
            
            # 파일 크기 추출 시도 (유연한 접근법)
            size_selectors = [
                # 볼드체 span 다음의 br 다음의 이탤릭 span (정확한 구조 매치)
                '//span[contains(@style, "font-weight:bold")]/following-sibling::br/following-sibling::span[contains(@style, "font-style:italic")]/text()',
                '//td[@class="normal"]//span[contains(@style, "font-weight:bold")]/following-sibling::br/following-sibling::span[contains(@style, "font-style:italic")]/text()',
                
                # 정확한 스타일 매치 (가장 확실한 방법)
                '//table[contains(@class, "premium")]//span[@style="font-size:0.9em;font-style:italic"]/text()',
                '//table[contains(@class, "premium")]//span[contains(@style, "font-style:italic") and contains(@style, "font-size:0.9em")]/text()',
                
                # 이탤릭 스타일로 된 크기 정보
                '//table[contains(@class, "premium")]//span[contains(@style, "font-style:italic")]/text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]',
                '//table//span[contains(@style, "italic")]/text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]',
                
                # QR코드가 있는 테이블의 두 번째 span (크기 정보)
                '//table[.//img[contains(@src, "qr.pl")]]//td[contains(@class, "normal")]//span[2]/text()',
                '//table//tr[td//img[contains(@src, "qr.pl")]]//td[position()=2]//span[2]/text()',
                
                # 볼드체 다음에 오는 span (일반적으로 크기 정보)
                '//table//span[contains(@style, "bold")]/following-sibling::*/text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]',
                '//table//span[contains(@style, "bold")]/following-sibling::text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]',
                
                # br 태그 다음에 오는 크기 정보
                '//table//br/following-sibling::span/text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]',
                '//table//br/following-sibling::text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]',
                
                # 위치 기반 (두 번째 span이 크기일 가능성)
                '//table[contains(@class, "premium")]//td[contains(@class, "normal")]//span[2]/text()',
                '//table//tr[td[@rowspan]]//td[position()=2]//span[2]/text()',
                
                # 모든 테이블에서 크기 패턴 찾기 (광범위한 폴백)
                '//table//span/text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]'
            ]
            
            for selector in size_selectors:
                try:
                    texts = doc.xpath(selector)
                    for text in texts:
                        text = text.strip()
                        # 파일 크기 패턴 확인
                        size_match = re.search(r'(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB|Ko|Mo|Go|To)', text, re.IGNORECASE)
                        if size_match:
                            size_value = float(size_match.group(1))
                            size_unit = size_match.group(2).upper().replace('O', 'B')  # Ko -> KB, Mo -> MB
                            file_info['size'] = f"{size_value} {size_unit}"
                            print(f"[DEBUG] 파일 크기 추출 성공: '{file_info['size']}' (선택자: {selector})")
                            break
                    if file_info['size']:
                        break
                except Exception as e:
                    print(f"[DEBUG] 크기 선택자 '{selector}' 실패: {e}")
                    continue
            
            # 2. 전체 HTML에서 크기 패턴 찾기 (폴백)
            if not file_info['size']:
                size_patterns = [
                    r'(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB|Ko|Mo|Go|To)',
                    r'Size:\s*(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)',
                    r'크기:\s*(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)'
                ]
                
                html_text = lxml.html.tostring(doc, encoding='unicode')
                for pattern in size_patterns:
                    match = re.search(pattern, html_text, re.IGNORECASE)
                    if match:
                        size_value = float(match.group(1))
                        size_unit = match.group(2).upper().replace('O', 'B')  # Ko -> KB, Mo -> MB
                        file_info['size'] = f"{size_value} {size_unit}"
                        break
            
            return file_info
            
        except Exception as e:
            logger.error(f"파일 정보 추출 중 오류: {e}")
            return {'name': None, 'size': None, 'type': None}


# 전역 파서 인스턴스
fichier_parser = FichierParser()