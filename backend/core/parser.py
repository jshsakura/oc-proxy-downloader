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
    
    # 다운로드 링크를 찾기 위한 다양한 선택자들 (우선순위 순)
    DOWNLOAD_SELECTORS = [
        # 기존 XPath
        '/html/body/div[4]/div[2]/a',
        '/html/body/div[3]/div[2]/a',
        '/html/body/div[5]/div[2]/a',
        
        # CSS 선택자들
        'a[href*="cdn-"]',  # CDN 링크
        'a[href*="download"]',  # download가 포함된 링크
        'a[href*=".1fichier.com"]',  # 1fichier 도메인 링크
        
        # 클래스 기반 선택자
        '.btn-download',
        '.download-link',
        '.btn-general',
        
        # 텍스트 기반 선택자
        '//a[contains(text(), "다운로드")]',
        '//a[contains(text(), "Download")]',
        '//a[contains(text(), "Télécharger")]',
        
        # 일반적인 다운로드 버튼 패턴
        '//a[contains(@class, "btn") and contains(@href, "http")]',
        '//a[contains(@onclick, "download")]',
        
        # 폼 내부의 링크
        '//form//a[contains(@href, "http")]',
        
        # 마지막 수단: 모든 외부 링크 중 파일 확장자가 있는 것
        '//a[contains(@href, "http") and (contains(@href, ".") or contains(@href, "download"))]'
    ]
    
    # 다운로드 링크 검증을 위한 패턴들
    VALID_LINK_PATTERNS = [
        r'https?://[^/]*1fichier\.com/',  # 1fichier 도메인
        r'https?://[^/]*\.1fichier\.com/',  # 서브도메인
        r'https?://cdn-\d+\.1fichier\.com/',  # CDN 링크
        r'https?://[^/]*download[^/]*/',  # download가 포함된 도메인
    ]
    
    # 제외할 링크 패턴들
    EXCLUDE_PATTERNS = [
        r'javascript:',
        r'#',
        r'mailto:',
        r'/premium',
        r'/register',
        r'/login',
        r'/contact',
        r'/help',
        r'/faq'
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
            # HTML 파싱
            doc = lxml.html.fromstring(html_content)
            
            # 각 선택자를 순서대로 시도
            for selector in self.DOWNLOAD_SELECTORS:
                try:
                    links = self._extract_links_by_selector(doc, selector)
                    
                    for link in links:
                        # 상대 링크를 절대 링크로 변환
                        if base_url and not link.startswith('http'):
                            link = urljoin(base_url, link)
                        
                        # 링크 검증
                        if self._is_valid_download_link(link):
                            logger.info(f"다운로드 링크 발견 (선택자: {selector}): {link}")
                            return link
                            
                except Exception as e:
                    logger.debug(f"선택자 {selector} 실행 중 오류: {e}")
                    continue
            
            # 모든 선택자가 실패한 경우, 휴리스틱 방법 시도
            fallback_link = self._heuristic_link_extraction(doc, base_url)
            if fallback_link:
                logger.info(f"휴리스틱 방법으로 링크 발견: {fallback_link}")
                return fallback_link
            
            logger.warning("다운로드 링크를 찾을 수 없습니다")
            return None
            
        except Exception as e:
            logger.error(f"HTML 파싱 중 오류: {e}")
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
            return False
        
        # 제외 패턴 확인
        for pattern in self.EXCLUDE_PATTERNS:
            if re.search(pattern, link, re.IGNORECASE):
                return False
        
        # 유효한 패턴 확인
        for pattern in self.VALID_LINK_PATTERNS:
            if re.search(pattern, link, re.IGNORECASE):
                return True
        
        # HTTP/HTTPS 링크이고 파일 확장자가 있는 경우
        if link.startswith('http') and ('.' in link.split('/')[-1] or 'download' in link.lower()):
            return True
        
        return False
    
    def _heuristic_link_extraction(self, doc, base_url):
        """휴리스틱 방법으로 다운로드 링크 추출"""
        try:
            # 모든 링크 수집
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
            
            # 가장 높은 점수의 링크 반환
            for score, link in scored_links:
                if self._is_valid_download_link(link):
                    return link
            
        except Exception as e:
            logger.error(f"휴리스틱 링크 추출 중 오류: {e}")
        
        return None
    
    def _calculate_link_score(self, link, element):
        """링크의 다운로드 가능성 점수 계산"""
        score = 0
        
        # URL 기반 점수
        if '1fichier.com' in link:
            score += 50
        if 'cdn-' in link:
            score += 30
        if 'download' in link.lower():
            score += 20
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
            
            # 파일명 추출 시도
            name_selectors = [
                '//h1[contains(@class, "file")]//text()',
                '//div[contains(@class, "filename")]//text()',
                '//span[contains(@class, "filename")]//text()',
                '//title/text()',
                '//*[contains(text(), ".")]//text()'
            ]
            
            for selector in name_selectors:
                try:
                    texts = doc.xpath(selector)
                    for text in texts:
                        text = text.strip()
                        if text and '.' in text and len(text) < 200:
                            file_info['name'] = text
                            break
                    if file_info['name']:
                        break
                except:
                    continue
            
            # 파일 크기 추출 시도
            size_patterns = [
                r'(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)',
                r'Size:\s*(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)',
                r'크기:\s*(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)'
            ]
            
            html_text = lxml.html.tostring(doc, encoding='unicode')
            for pattern in size_patterns:
                match = re.search(pattern, html_text, re.IGNORECASE)
                if match:
                    size_value = float(match.group(1))
                    size_unit = match.group(2).upper()
                    file_info['size'] = f"{size_value} {size_unit}"
                    break
            
            return file_info
            
        except Exception as e:
            logger.error(f"파일 정보 추출 중 오류: {e}")
            return {'name': None, 'size': None, 'type': None}


# 전역 파서 인스턴스
fichier_parser = FichierParser()