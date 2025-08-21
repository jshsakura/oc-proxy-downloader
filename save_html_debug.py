#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1fichier HTML 응답 저장 및 분석 도구
"""

import requests
import cloudscraper
import time

def debug_1fichier_html():
    """1fichier HTML 응답을 파일로 저장하여 분석"""
    url = "https://1fichier.com/?kz7su8x41zy3srpi84lo"
    
    print("=" * 60)
    print("1fichier HTML 디버깅")
    print("=" * 60)
    
    # Cloudscraper 사용
    scraper = cloudscraper.create_scraper()
    
    try:
        print("1단계: GET 요청...")
        r1 = scraper.get(url)
        print(f"응답 코드: {r1.status_code}")
        
        # 첫 번째 응답 저장
        with open('1fichier_step1.html', 'w', encoding='utf-8') as f:
            f.write(r1.text)
        print("1단계 HTML을 1fichier_step1.html에 저장했습니다.")
        
        # 폼 분석
        import re
        forms = re.findall(r'<form[^>]*>(.*?)</form>', r1.text, re.DOTALL | re.IGNORECASE)
        print(f"발견된 폼 수: {len(forms)}")
        
        # 폼 데이터 추출
        form_data = {'submit': 'Download'}
        for i, form in enumerate(forms):
            print(f"폼 {i+1} 분석...")
            inputs = re.findall(r'<input[^>]*name=["\']([^"\']+)["\'][^>]*(?:value=["\']([^"\']*)["\'])?[^>]*>', form, re.IGNORECASE)
            for name, value in inputs:
                if name and name not in ['submit']:
                    form_data[name] = value or ''
                    print(f"  {name} = {value}")
        
        print(f"POST 데이터: {form_data}")
        
        # 20초 대기 (카운트다운)
        print("2단계: 20초 대기 중...")
        time.sleep(20)
        
        print("3단계: POST 요청...")
        r2 = scraper.post(url, data=form_data)
        print(f"응답 코드: {r2.status_code}")
        
        # 두 번째 응답 저장
        with open('1fichier_step2.html', 'w', encoding='utf-8') as f:
            f.write(r2.text)
        print("2단계 HTML을 1fichier_step2.html에 저장했습니다.")
        
        # 실제 다운로드 링크 찾기
        print("\n실제 다운로드 링크 검색...")
        
        # 일반적인 패턴들
        patterns = [
            r'https?://[a-z]-\d+\.1fichier\.com/[^"\'>\s]+',
            r'https?://cdn-\d+\.1fichier\.com/[^"\'>\s]+',
            r'https?://[^/]*\.1fichier\.com/[^"\'>\s]{20,}',
            r'https?://[^"\'>\s]*1fichier[^"\'>\s]*\?[^"\'>\s]{20,}',
        ]
        
        for i, pattern in enumerate(patterns):
            matches = re.findall(pattern, r2.text, re.IGNORECASE)
            if matches:
                print(f"패턴 {i+1} 매칭: {matches}")
                
        # JavaScript window.location 패턴
        js_patterns = [
            r'window\.location\s*=\s*["\']([^"\']+)["\']',
            r'location\.href\s*=\s*["\']([^"\']+)["\']',
            r'document\.location\s*=\s*["\']([^"\']+)["\']',
        ]
        
        for i, pattern in enumerate(js_patterns):
            matches = re.findall(pattern, r2.text, re.IGNORECASE)
            if matches:
                print(f"JavaScript 패턴 {i+1} 매칭: {matches}")
        
        # 메타 리프레시 확인
        meta_refresh = re.findall(r'<meta[^>]*http-equiv=["\']refresh["\'][^>]*content=["\'][^"\']*url=([^"\']+)["\']', r2.text, re.IGNORECASE)
        if meta_refresh:
            print(f"메타 리프레시 발견: {meta_refresh}")
            
        print("\n분석 완료. HTML 파일들을 확인해보세요.")
        
    except Exception as e:
        print(f"에러: {e}")

if __name__ == "__main__":
    debug_1fichier_html()