# -*- coding: utf-8 -*-
"""
1fichier URL 사전 파싱 서비스
URL 추가 시 1fichier 링크의 파일명과 크기를 미리 가져옴
"""

import re
import httpx
from typing import Optional, Dict, Any
from urllib.parse import urlparse
import logging

from core.parser import fichier_parser

logger = logging.getLogger(__name__)

class PreparseService:
    """1fichier URL 사전 파싱 서비스"""
    
    def __init__(self):
        self.timeout = 30  # 30초 타임아웃
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
    
    def is_1fichier_url(self, url: str) -> bool:
        """1fichier URL인지 확인"""
        try:
            parsed = urlparse(url)
            return '1fichier.com' in parsed.netloc.lower()
        except Exception as e:
            print(f"[LOG] URL parsing error: {e}")
            return False
    
    async def preparse_1fichier(self, url: str) -> Dict[str, Any]:
        """
        1fichier URL에서 파일 정보를 사전 파싱
        
        Args:
            url: 1fichier URL
            
        Returns:
            Dict: {'name': str, 'size': str, 'success': bool, 'error': str}
        """
        result = {
            'name': None,
            'size': None,
            'success': False,
            'error': None
        }
        
        if not self.is_1fichier_url(url):
            result['error'] = "1fichier URL이 아닙니다"
            return result
        
        try:
            logger.info(f"[PREPARSE] 1fichier URL 사전 파싱 시작: {url}")
            
            # HTTP 요청으로 페이지 가져오기
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers=self.headers,
                follow_redirects=True
            ) as client:
                
                logger.info(f"[PREPARSE] HTTP 요청 시작...")
                response = await client.get(url)
                response.raise_for_status()
                
                html_content = response.text
                logger.info(f"[PREPARSE] HTML 응답 받음 (길이: {len(html_content)})")
                
                # 파일 정보 추출
                file_info = fichier_parser.extract_file_info(html_content)
                
                if file_info.get('name'):
                    result['name'] = file_info['name']
                    result['success'] = True
                    logger.info(f"[PREPARSE] ✓ 파일명 추출 성공: {result['name']}")
                else:
                    logger.warning(f"[PREPARSE] ✗ 파일명 추출 실패")
                
                if file_info.get('size'):
                    result['size'] = file_info['size']
                    logger.info(f"[PREPARSE] ✓ 파일 크기 추출 성공: {result['size']}")
                else:
                    logger.warning(f"[PREPARSE] ✗ 파일 크기 추출 실패")
                
                # 파일명이나 크기 중 하나라도 추출되면 성공으로 간주
                if result['name'] or result['size']:
                    result['success'] = True
                    logger.info(f"[PREPARSE] 사전 파싱 완료 - 이름: {result['name']}, 크기: {result['size']}")
                else:
                    result['error'] = "파일 정보를 추출할 수 없습니다"
                    logger.error(f"[PREPARSE] 파일 정보 추출 실패")
                
        except httpx.TimeoutException:
            result['error'] = "요청 시간 초과"
            logger.error(f"[PREPARSE] 타임아웃 오류: {url}")
        except httpx.HTTPStatusError as e:
            result['error'] = f"HTTP 오류: {e.response.status_code}"
            logger.error(f"[PREPARSE] HTTP 오류 {e.response.status_code}: {url}")
        except Exception as e:
            result['error'] = f"예상치 못한 오류: {str(e)}"
            logger.error(f"[PREPARSE] 예상치 못한 오류: {e}")
        
        return result

# 전역 인스턴스
preparse_service = PreparseService()