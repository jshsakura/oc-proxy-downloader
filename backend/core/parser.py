# -*- coding: utf-8 -*-
"""
1fichier.com parsing module
A flexible parsing system that adapts to site structure changes
"""

import re
import lxml.html
import json
from urllib.parse import urljoin, urlparse
import logging

# Removed the send_telegram_wait_notification dependency - keep pure parsing logic only
from .db import SessionLocal
from .models import DownloadRequest

logger = logging.getLogger(__name__)

class FichierParser:
    """1fichier.com download link parsing class"""

    # Selectors based on the actual 2025 1fichier structure (real, tested patterns)
    DOWNLOAD_SELECTORS = [
        # The structure 1fichier currently uses in practice (as of January 2025)
        '//*[@id="dlw"]',  # Main download button (verified in practice)
        '//form[@id="f1"]',  # Download form (POST method)

        # Patterns for when the actual download link has been generated
        '//a[contains(@href, "://") and contains(@href, ".1fichier.com/") and string-length(@href) > 40]',

        # Per-server download patterns (simplified)
        '//a[contains(@href, "://cdn-") and contains(@href, ".1fichier.com/")]',  # CDN servers
        '//a[contains(@href, "://a-") and contains(@href, ".1fichier.com/")]',    # a- servers
        '//a[contains(@href, "://s") and contains(@href, ".1fichier.com/")]',     # s<number> servers

        # Backup selectors (against the older structure)
        '//a[@href and string-length(@href) > 50 and contains(@href, "1fichier")]'

        # Newer 1fichier structure (as of 2024)
        '//a[contains(@class, "ok btn-general")]',
        '//a[contains(@class, "btn-general") and contains(@href, "cdn-")]',
        '//div[@class="ct_warn"]//a[contains(@href, "http")]',

        # Legacy XPath (may still be valid)
        '/html/body/div[4]/div[2]/a',
        '/html/body/div[3]/div[2]/a',
        '/html/body/div[5]/div[2]/a',
        '/html/body/div[6]/div[2]/a',

        # Based on dynamic containers
        '//div[contains(@class, "content")]//a[contains(@href, "cdn-")]',
        '//div[contains(@class, "download")]//a[contains(@href, "http")]',

        # CSS selectors (high priority)
        'a[href*="cdn-"][href*=".1fichier.com"]',  # CDN link (most reliable)
        'a[href*="download.1fichier.com"]',  # Download server
        'a[href*="cdn-"]',  # CDN link
        'a[href*="download"]',  # Link containing "download"
        'a[href*=".1fichier.com"][href*="?"]',  # 1fichier domain + query

        # Class-based selectors
        '.btn-download',
        '.download-link',
        '.btn-general',
        '.ok',

        # Text-based selectors (multilingual support)
        '//a[contains(text(), "다운로드")]',
        '//a[contains(text(), "Download")]',
        '//a[contains(text(), "DOWNLOAD")]',
        '//a[contains(text(), "Télécharger")]',
        '//a[contains(text(), "Descargar")]',
        '//a[contains(text(), "ダウンロード")]',

        # Button patterns
        '//a[contains(@class, "btn") and contains(@href, "http")]',
        '//button[@onclick and contains(@onclick, "location")]/..//a',
        '//a[contains(@onclick, "download")]',
        '//a[contains(@onclick, "location")]',

        # Form-related
        '//form//a[contains(@href, "http")]',
        '//form[@method="get"]//a',

        # Meta refresh pattern
        '//meta[@http-equiv="refresh" and contains(@content, "url=")]',

        # JavaScript patterns
        '//script[contains(text(), "location.href") or contains(text(), "window.location")]',

        # Last resort: all external links (excluding the problem pages)
        '//a[contains(@href, "http") and (contains(@href, ".") or contains(@href, "download")) and not(contains(@href, "cgu")) and not(contains(@href, "cgv")) and not(contains(@href, "console")) and not(contains(@href, "tarifs")) and not(contains(@href, "revendeurs")) and not(contains(@href, "network")) and not(contains(@href, "hlp")) and not(contains(@href, "abus")) and not(contains(@href, "register")) and not(contains(@href, "login")) and not(contains(@href, "contact")) and not(contains(@href, "premium"))]'
    ]

    # Patterns for validating download links (in priority order)
    VALID_LINK_PATTERNS = [
        r'https?://cdn-\d+\.1fichier\.com/',  # CDN link (top priority)
        r'https?://a-\d+\.1fichier\.com/',  # a-<number> pattern link (top priority)
        r'https?://[a-z]-\d+\.1fichier\.com/',  # x-<number> pattern link (top priority)
        r'https?://[^/]*download[^/]*/',  # Domain containing "download"
        r'https?://[^/]*\.1fichier\.com/[a-zA-Z0-9_\-]{10,}',  # Subdomain + long path
    ]

    # Link patterns to exclude (hardened)
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
        r'/console/abo\.pl',    # Premium payment page
        r'/tarifs',             # Pricing page
        r'/console/',           # Console pages
        r'/cgu\.html',          # Terms of use page ⭐ key problem
        r'/cgv\.html',          # Terms of sale page
        r'/mentions\.html',     # Legal notice page
        r'/privacy\.html',      # Privacy page
        r'/about\.html',        # About page
        r'cgu\.html$',          # Terms of use filename (no path)
        r'cgv\.html$',          # Terms of sale filename
        r'mentions\.html$',     # Legal notice filename
        r'privacy\.html$',      # Privacy filename
        r'about\.html$',        # About filename
        r'1fichier\.com/cgu',   # cgu on the 1fichier domain
        r'1fichier\.com/cgv',   # cgv on the 1fichier domain
        r'1fichier\.com/mentions', # mentions on the 1fichier domain
        r'1fichier\.com/privacy',  # privacy on the 1fichier domain
        r'1fichier\.com/about',    # about on the 1fichier domain
        r'1fichier\.com/tarifs',   # tarifs on the 1fichier domain
        r'1fichier\.com/premium',  # premium on the 1fichier domain
        r'1fichier\.com/console',  # console on the 1fichier domain
        r'1fichier\.com/register', # register on the 1fichier domain
        r'1fichier\.com/login',    # login on the 1fichier domain
        r'1fichier\.com/help',     # help on the 1fichier domain
        r'1fichier\.com/faq',      # faq on the 1fichier domain
        r'1fichier\.com/contact',  # contact on the 1fichier domain
        r'1fichier\.com/abus',     # abus on the 1fichier domain (abuse report)
        r'1fichier\.com/hlp',      # help on the 1fichier domain
        r'1fichier\.com/revendeurs', # Reseller page
        r'/revendeurs\.html',      # Reseller page
        r'revendeurs\.html$',      # Reseller filename
        r'1fichier\.com/network',  # Network page
        r'/network\.html',         # Network page
        r'network\.html$',         # Network filename
        r'/abus\.html',            # Abuse report page
        r'/hlp\.html',             # Help page
        r'abus\.html$',            # Abuse report filename (no path)
        r'hlp\.html$',             # Help filename (no path)
        r'/abus\.html$',           # Abuse report page (full path)
        r'/hlp\.html$',            # Help page (full path)
        r'1fichier\.com/abus\.html', # abus.html on the 1fichier domain (abuse report)
        r'1fichier\.com/hlp\.html',  # hlp.html on the 1fichier domain (help)
        r'1fichier\.com/?$',       # 1fichier main page (not a file)
        r'https?://1fichier\.com/?$', # 1fichier main page (full URL)
        r'https?://img\.1fichier\.com/', # Image server (logo-footer, etc.)
        r'/logo-footer',           # Logo image
        r'logo-footer$',           # Logo image filename
        r'/api\.html',             # API docs page
        r'api\.html$',             # API docs filename
        r'1fichier\.com/api\.html', # 1fichier API docs page
    ]
    
    def __init__(self):
        self.session_cookies = {}
    
    def parse_download_link(self, html_content, base_url=None):
        """
        Extract the download link from HTML content

        Args:
            html_content (str): HTML content
            base_url (str): Base URL (for resolving relative links)

        Returns:
            str: The download link, or None
        """
        try:
            print(f"[DEBUG] 파싱 시작 - HTML 길이: {len(html_content)} 문자")

            # Check 1fichier wait time (handled the same way as before)
            if 'Free download in' in html_content:
                # Check for a 16-minute wait time
                wait_match = re.search(r'Free download in.*?(\d+)\s*minutes?', html_content, re.IGNORECASE)
                if wait_match:
                    wait_minutes = int(wait_match.group(1))
                    wait_seconds = wait_minutes * 60  # Convert minutes to seconds
                    print(f"[LOG] 1fichier 대기시간 감지: {wait_minutes}분 ({wait_seconds}초)")

                    # Telegram notification when the wait is 5 minutes or more (local downloads only)
                    if wait_minutes >= 5:
                        try:

                            with SessionLocal() as db:
                                req = db.query(DownloadRequest).filter(DownloadRequest.url == url).first()
                                file_name = req.file_name if req and req.file_name else "1fichier File"
                                file_size = req.file_size if req and req.file_size else None

                            # Changed so the Telegram notification is handled by the caller
                            # send_telegram_wait_notification(file_name, wait_minutes, "ko", file_size)
                            print(f"[PARSER] 대기 시간 감지: {file_name}, {wait_minutes}분")
                        except Exception as e:
                            print(f"[WARN] 텔레그램 대기시간 알림 실패: {e}")

                    return None  # Return None as before to delegate wait-time handling

            # First search for direct download link patterns with regex
            print(f"[DEBUG] 정규식 패턴 검색 시작...")
            download_patterns = [
                r'https?://a-\d+\.1fichier\.com/[a-zA-Z0-9_\-/]+',     # a-<number>.1fichier.com/<hash>
                r'https?://cdn-\d+\.1fichier\.com/[a-zA-Z0-9_\-/]+',   # cdn-<number>.1fichier.com/<hash>
                r'https?://[a-z]-\d+\.1fichier\.com/[a-zA-Z0-9_\-/]{8,}', # General pattern
                r'https?://[a-z]\d+\.1fichier\.com/[a-zA-Z0-9_\-/]{8,}', # s17.1fichier.com, etc.
                r'https?://\w+\d+\.1fichier\.com/[a-zA-Z0-9_\-/]{10,}', # Any subdomain + number
                r'https://[^"\'>\s]*\.1fichier\.com/[^"\'>\s]{15,}',   # Subdomain + long path
            ]

            for i, pattern in enumerate(download_patterns):
                matches = re.findall(pattern, html_content, re.IGNORECASE)
                print(f"[DEBUG] 정규식 패턴 {i+1} ({pattern}) 검색 결과: {len(matches) if matches else 0}개")
                if matches:
                    print(f"[DEBUG] 정규식 패턴 {i+1} 매칭: {matches}")
                    for match in matches:
                        print(f"[DEBUG] 링크 검증 중: {match}")
                        # Validate
                        if self._is_valid_download_link(match):
                            print(f"[LOG] 정규식으로 발견된 다운로드 링크: {match}")
                            return match
                        else:
                            print(f"[DEBUG] 링크 검증 실패: {match}")
            
            print(f"[DEBUG] 모든 정규식 패턴에서 유효한 다운로드 링크를 찾지 못함")

            # Check for JavaScript redirects or dynamically generated links
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
            
            # Check Meta refresh
            meta_refresh = re.findall(r'<meta[^>]*http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*url=([^"\']+)["\']', html_content, re.IGNORECASE)
            for meta_url in meta_refresh:
                if '1fichier.com' in meta_url and len(meta_url) > 30:
                    print(f"[DEBUG] Meta refresh 발견: {meta_url}")
                    if self._is_valid_download_link(meta_url):
                        print(f"[LOG] Meta refresh에서 발견된 다운로드 링크: {meta_url}")
                        return meta_url
            
            # Parse HTML
            doc = lxml.html.fromstring(html_content)

            # Collect all links (for debugging)
            all_links = doc.xpath('//a[@href]')
            print(f"[DEBUG] 전체 링크 수: {len(all_links)}")

            # Specifically check a-<number> pattern links
            a_pattern_links = [a.get('href') for a in all_links if a.get('href') and 'a-' in a.get('href')]
            if a_pattern_links:
                print(f"[DEBUG] a-숫자 패턴 링크들:")
                for link in a_pattern_links:
                    print(f"[DEBUG]   {link}")

            # Check problem links such as cgu.html
            problem_links = [a.get('href') for a in all_links if a.get('href') and any(x in a.get('href').lower() for x in ['cgu.html', 'tarifs', 'console'])]
            if problem_links:
                print(f"[DEBUG] 문제 링크들 (제외되어야 함):")
                for link in problem_links:
                    print(f"[DEBUG]   {link}")

            # Try each selector in order
            for i, selector in enumerate(self.DOWNLOAD_SELECTORS):
                try:
                    links = self._extract_links_by_selector(doc, selector)
                    print(f"[DEBUG] 선택자 {i+1}: '{selector}' -> {len(links)}개 링크")

                    for link in links:
                        print(f"[DEBUG]   후보 링크: {link}")

                        # Convert a relative link to an absolute link
                        if base_url and not link.startswith('http'):
                            link = urljoin(base_url, link)

                        # Validate the link
                        if self._is_valid_download_link(link):
                            print(f"[LOG] OK 다운로드 링크 발견 (선택자 {i+1}: {selector}): {link}")
                            return link
                        else:
                            print(f"[DEBUG]   FAIL 링크 검증 실패: {link}")
                            
                except Exception as e:
                    print(f"[DEBUG] 선택자 {selector} 실행 중 오류: {e}")
                    continue
            
            # If all selectors failed, try the heuristic approach
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
        """Extract links using a selector"""
        links = []

        try:
            if selector.startswith('//') or selector.startswith('/html'):
                # XPath selector
                elements = doc.xpath(selector)
            else:
                # CSS selector
                elements = doc.cssselect(selector)
            
            for element in elements:
                href = element.get('href')
                if href:
                    links.append(href)
                    
        except Exception as e:
            logger.debug(f"선택자 {selector} 처리 중 오류: {e}")
        
        return links
    
    def _is_valid_download_link(self, link):
        """Validate a download link"""
        if not link or not isinstance(link, str):
            print(f"[DEBUG] 링크 검증 실패: 빈 링크 또는 잘못된 타입")
            return False

        print(f"[DEBUG] 링크 검증 중: {link}")

        # Check the exclude patterns (checked first)
        for pattern in self.EXCLUDE_PATTERNS:
            if re.search(pattern, link, re.IGNORECASE):
                print(f"[DEBUG] 제외 패턴 매칭: {pattern} -> {link}")
                return False

        # Keywords that must definitely be excluded (hardened)
        exclude_keywords = [
            'cgu.html', 'cgv.html', 'mentions.html', 'privacy.html', 'about.html',
            'abus.html', 'hlp.html',  # Abuse report, help pages
            'premium', 'console', 'register', 'login', 'help', 'contact', 'faq', 'tarifs',
            '/cgu', '/cgv', '/mentions', '/privacy', '/about', '/tarifs', '/premium',
            '/console', '/register', '/login', '/help', '/contact', '/faq', '/abus', '/hlp',
            '1fichier.com/cgu', '1fichier.com/cgv', '1fichier.com/mentions',
            '1fichier.com/privacy', '1fichier.com/about', '1fichier.com/tarifs',
            '1fichier.com/premium', '1fichier.com/console', '1fichier.com/register',
            '1fichier.com/login', '1fichier.com/help', '1fichier.com/contact', '1fichier.com/faq',
            '1fichier.com/abus', '1fichier.com/hlp',  # Abuse report, help related
            'img.1fichier.com', 'logo-footer',  # Image server and logo
            'api.html', '1fichier.com/api.html'  # API docs page
        ]
        for keyword in exclude_keywords:
            if keyword in link.lower():
                print(f"[DEBUG] 제외 키워드 발견: {keyword} -> {link}")
                return False

        # CDN links are allowed with top priority
        if 'cdn-' in link and '.1fichier.com' in link:
            print(f"[DEBUG] OK CDN 링크 허용: {link}")
            return True

        # Allow a-<number> pattern links (real download links)
        if re.search(r'https?://[a-z]-\d+\.1fichier\.com/', link):
            print(f"[DEBUG] OK a-숫자 패턴 링크 허용: {link}")
            return True

        # Download-only domains
        download_domains = ['download.1fichier.com', 'dl.1fichier.com', 'static.1fichier.com']
        for domain in download_domains:
            if domain in link:
                print(f"[DEBUG] OK 다운로드 도메인 허용: {domain} -> {link}")
                return True

        # Never allow the original 1fichier URL (it is not a download link)
        if re.match(r'https?://1fichier\.com/\?[a-zA-Z0-9]+$', link):
            print(f"[DEBUG] FAIL 원본 1fichier URL 제외 (다운로드 링크 아님): {link}")
            return False

        # Check valid patterns (in priority order)
        for pattern in self.VALID_LINK_PATTERNS:
            if re.search(pattern, link, re.IGNORECASE):
                print(f"[DEBUG] OK 유효한 패턴 매칭: {pattern} -> {link}")
                return True

        # HTTP/HTTPS link with a query parameter (possibly a file download link)
        if link.startswith('http') and '?' in link and 'download' in link.lower():
            print(f"[DEBUG] OK 쿼리 파라미터 있는 다운로드 링크: {link}")
            return True

        # HTTP/HTTPS link with a file extension (but excluding the 1fichier main domain)
        if link.startswith('http') and '.' in link.split('/')[-1]:
            # Exclude the 1fichier main domain (not a file)
            if link.strip('/') in ['https://1fichier.com', 'http://1fichier.com']:
                print(f"[DEBUG] FAIL 1fichier 메인 도메인 제외: {link}")
                return False
            print(f"[DEBUG] OK 파일 확장자 있는 링크: {link}")
            return True

        print(f"[DEBUG] FAIL 링크 검증 실패: {link}")
        return False
    
    def _heuristic_link_extraction(self, doc, base_url):
        """Extract the download link using heuristics"""
        try:
            # Step 1: extract a link from JavaScript
            js_link = self._extract_from_javascript(doc, base_url)
            if js_link:
                logger.info(f"JavaScript에서 링크 발견: {js_link}")
                return js_link

            # Step 2: extract a link from meta refresh
            meta_link = self._extract_from_meta_refresh(doc, base_url)
            if meta_link:
                logger.info(f"메타 리프레시에서 링크 발견: {meta_link}")
                return meta_link

            # Step 3: collect all links and compute scores
            all_links = []

            # Every a tag with an href attribute
            for a in doc.xpath('//a[@href]'):
                href = a.get('href')
                if href:
                    # Convert a relative link to an absolute link
                    if base_url and not href.startswith('http'):
                        href = urljoin(base_url, href)
                    all_links.append((href, a))

            # Compute and sort link scores
            scored_links = []
            for link, element in all_links:
                score = self._calculate_link_score(link, element)
                if score > 0:
                    scored_links.append((score, link))

            # Sort by score
            scored_links.sort(reverse=True)

            # Return the highest-scoring link (with extra validation)
            for score, link in scored_links:
                print(f"[DEBUG] 휴리스틱 후보 링크 검토: 점수={score}, 링크={link}")
                if self._is_valid_download_link(link):
                    # Final safety check - block problem links
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
        """Extract the download link from JavaScript code"""
        try:
            # Find all script tags
            scripts = doc.xpath('//script/text()')

            # More comprehensive JavaScript patterns
            js_patterns = [
                r'window\.location\s*=\s*[\'"]([^\'"]+)[\'"]',
                r'document\.location\s*=\s*[\'"]([^\'"]+)[\'"]',
                r'location\.href\s*=\s*[\'"]([^\'"]+)[\'"]',
                r'var\s+download_url\s*=\s*[\'"]([^\'"]+)[\'"]',
                r'var\s+url\s*=\s*[\'"]([^\'"]+)[\'"]',
                r'setTimeout\s*\(\s*function\s*\(\)\s*\{\s*location\s*=\s*[\'"]([^\'"]+)[\'"]',
                r'href\s*=\s*[\'"]([^\'"]*cdn-[^\'"]*)[\'"]',
                r'href\s*=\s*[\'"]([^\'"]*a-\d+[^\'"]*)[\'"]',  # a-<number> pattern
                r'[\'"]https://[a-z]-\d+\.1fichier\.com/[^\'"]*[\'"]',  # Direct URL pattern
                r'submit\(\)\s*\}\s*\}\s*[;\s]*[\'"]([^\'"]*a-\d+[^\'"]*)[\'"]',  # URL after submit
                r'\.click\(.*?\)\s*\}\s*\}\s*[;\s]*[\'"]([^\'"]*a-\d+[^\'"]*)[\'"]',  # URL after click
            ]

            print(f"[DEBUG] JavaScript 링크 추출 시작 - {len(scripts)}개 스크립트")

            for i, script_content in enumerate(scripts):
                if script_content:
                    print(f"[DEBUG] Script {i+1} 분석 중... (길이: {len(script_content)})")

                    # Directly search for the a-<number> pattern
                    a_pattern_matches = re.findall(r'https://[a-z]-\d+\.1fichier\.com/[^\s\'"<>]+', script_content)
                    if a_pattern_matches:
                        print(f"[DEBUG] Script에서 a-패턴 발견: {a_pattern_matches}")
                        for match in a_pattern_matches:
                            if self._is_valid_download_link(match):
                                print(f"[DEBUG] JavaScript에서 a-패턴 링크 발견: {match}")
                                return match

                    # Also try the existing patterns
                    for pattern in js_patterns:
                        matches = re.findall(pattern, script_content, re.IGNORECASE)
                        for match in matches:
                            # Convert a relative link to an absolute link
                            if base_url and not match.startswith('http'):
                                match = urljoin(base_url, match)
                            
                            if self._is_valid_download_link(match):
                                print(f"[DEBUG] JavaScript 패턴 매칭: {pattern} -> {match}")
                                return match
            
        except Exception as e:
            print(f"[DEBUG] JavaScript 링크 추출 중 오류: {e}")
        
        return None
    
    def _extract_from_meta_refresh(self, doc, base_url):
        """Extract a link from meta refresh tags"""
        try:
            # Find meta refresh tags
            meta_refreshes = doc.xpath('//meta[@http-equiv="refresh"]/@content')

            for content in meta_refreshes:
                # Extract the url= part
                match = re.search(r'url=([^;\'"\s]+)', content, re.IGNORECASE)
                if match:
                    url = match.group(1)

                    # Convert a relative link to an absolute link
                    if base_url and not url.startswith('http'):
                        url = urljoin(base_url, url)
                    
                    if self._is_valid_download_link(url):
                        return url
            
        except Exception as e:
            logger.debug(f"메타 리프레시 링크 추출 중 오류: {e}")
        
        return None
    
    def _calculate_link_score(self, link, element):
        """Compute a score for how likely a link is a download link"""
        score = 0

        # URL-based score (high priority)
        if 'cdn-' in link and '1fichier.com' in link:
            score += 100  # CDN links get the highest score
        elif 'download' in link.lower() and '1fichier.com' in link:
            score += 80   # Download server link
        elif '1fichier.com' in link:
            score += 30   # Generic 1fichier link

        # Strong penalty for links to exclude (hardened)
        exclude_keywords = [
            'console', 'abo', 'premium', 'register', 'login', 'help', 'contact', 'faq', 'tarifs',
            'cgu.html', 'cgv.html', 'mentions.html', 'privacy.html', 'about.html',
            'abus.html', 'hlp.html',  # Abuse report, help pages
            '/cgu', '/cgv', '/mentions', '/privacy', '/about', '/tarifs', '/premium',
            '/console', '/register', '/login', '/help', '/contact', '/faq', '/abus', '/hlp',
            '1fichier.com/cgu', '1fichier.com/cgv', '1fichier.com/mentions',
            '1fichier.com/privacy', '1fichier.com/about', '1fichier.com/tarifs',
            '1fichier.com/premium', '1fichier.com/console', '1fichier.com/abus', '1fichier.com/hlp',
            'api.html', '1fichier.com/api.html'  # API docs page
        ]
        for keyword in exclude_keywords:
            if keyword in link.lower():
                score -= 1000  # A very large penalty to definitely exclude it

        if link.startswith('https://'):
            score += 10

        # Score based on element attributes
        class_attr = element.get('class', '').lower()
        if 'btn' in class_attr:
            score += 15
        if 'download' in class_attr:
            score += 25
        if 'primary' in class_attr or 'success' in class_attr:
            score += 10

        # Score based on text
        text = (element.text or '').lower().strip()
        if text in ['download', '다운로드', 'télécharger']:
            score += 30
        if 'download' in text:
            score += 20

        # Check the parent element
        parent = element.getparent()
        if parent is not None:
            parent_class = parent.get('class', '').lower()
            if 'download' in parent_class:
                score += 15
        
        return score
    
    def extract_file_info(self, html_content):
        """Extract file info from HTML"""
        try:
            doc = lxml.html.fromstring(html_content)

            file_info = {
                'name': None,
                'size': None,
                'type': None
            }

            # Try to extract the file name (a simple, reliable approach)
            name_selectors = [
                # Most reliable: a bold span containing a dot (the file name)
                '//span[@style="font-weight:bold"]/text()',
                # Bold text inside a table
                '//table//span[@style="font-weight:bold"]/text()',
                # Bold text inside td.normal
                '//td[@class="normal"]//span[@style="font-weight:bold"]/text()',
                # Meta tag fallback
                '//meta[@property="og:title"]/@content',
                '//title/text()'
            ]

            for selector in name_selectors:
                try:
                    texts = doc.xpath(selector)
                    for text in texts:
                        # Handle JSON-LD data
                        if 'json' in selector.lower():
                            try:
                                data = json.loads(text)
                                if isinstance(data, dict) and 'name' in data:
                                    text = data['name']
                                else:
                                    continue
                            except (json.JSONDecodeError, TypeError):
                                continue
                        
                        text = text.strip()
                        # Basic file name validation (minimal filtering only)
                        if text and len(text) > 3 and len(text) < 200:
                            # Exclude only clear promotional/ad text (very restrictive)
                            obvious_ads = [
                                '1fichier.com !',  # Exact promotional phrase
                                'started on 1fichier.com',  # Exact promotional phrase
                                'http://', 'https://',  # Contains a URL
                                '€', '$',  # Price indicator
                            ]

                            # Exclude only obvious ad text
                            if any(ad in text for ad in obvious_ads):
                                print(f"[DEBUG] 명백한 광고 텍스트 제외: {text}")
                                continue

                            # Accept text containing a dot as a file name (no extension restriction)
                            if '.' in text:
                                # Clean up if it came from the title
                                if 'title' in selector.lower():
                                    # Extract only the file name from "filename - 1fichier.com"
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
            
            # Try to extract the file size (a flexible approach)
            size_selectors = [
                # Italic span after a br after a bold span (exact structural match)
                '//span[contains(@style, "font-weight:bold")]/following-sibling::br/following-sibling::span[contains(@style, "font-style:italic")]/text()',
                '//td[@class="normal"]//span[contains(@style, "font-weight:bold")]/following-sibling::br/following-sibling::span[contains(@style, "font-style:italic")]/text()',

                # Exact style match (the most reliable method)
                '//table[contains(@class, "premium")]//span[@style="font-size:0.9em;font-style:italic"]/text()',
                '//table[contains(@class, "premium")]//span[contains(@style, "font-style:italic") and contains(@style, "font-size:0.9em")]/text()',

                # Size info in italic style
                '//table[contains(@class, "premium")]//span[contains(@style, "font-style:italic")]/text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]',
                '//table//span[contains(@style, "italic")]/text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]',

                # The second span in the table with the QR code (size info)
                '//table[.//img[contains(@src, "qr.pl")]]//td[contains(@class, "normal")]//span[2]/text()',
                '//table//tr[td//img[contains(@src, "qr.pl")]]//td[position()=2]//span[2]/text()',

                # The span following a bold span (usually size info)
                '//table//span[contains(@style, "bold")]/following-sibling::*/text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]',
                '//table//span[contains(@style, "bold")]/following-sibling::text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]',

                # Size info following a br tag
                '//table//br/following-sibling::span/text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]',
                '//table//br/following-sibling::text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]',

                # Position-based (the second span is likely the size)
                '//table[contains(@class, "premium")]//td[contains(@class, "normal")]//span[2]/text()',
                '//table//tr[td[@rowspan]]//td[position()=2]//span[2]/text()',

                # Find the size pattern in any table (broad fallback)
                '//table//span/text()[contains(., "GB") or contains(., "MB") or contains(., "KB") or contains(., "TB")]'
            ]

            for selector in size_selectors:
                try:
                    texts = doc.xpath(selector)
                    for text in texts:
                        text = text.strip()
                        # Check for the file size pattern
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
            
            # 2. Find the size pattern in the entire HTML (fallback)
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


# Global parser instance
fichier_parser = FichierParser()