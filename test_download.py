#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
다운로드 시스템 테스트 스크립트
"""

import requests
import time
import json

def test_download_api():
    """다운로드 API 테스트"""
    base_url = "http://localhost:8000/api"
    
    print("=" * 60)
    print("다운로드 시스템 테스트 시작")
    print("=" * 60)
    
    # 1. 유효하지 않은 URL로 테스트
    print("\n1. 유효하지 않은 URL 테스트...")
    test_data = {
        "url": "https://1fichier.com/?invalid_test_file",
        "password": "",
        "use_proxy": False
    }
    
    try:
        response = requests.post(f"{base_url}/download/", json=test_data)
        print(f"응답 상태 코드: {response.status_code}")
        print(f"응답 내용: {response.json()}")
        
        download_id = response.json().get('id')
        if download_id:
            print(f"다운로드 ID: {download_id}")
            
            # 몇 초 후 상태 확인
            time.sleep(3)
            
            # 히스토리에서 상태 확인
            history_response = requests.get(f"{base_url}/history/{download_id}")
            if history_response.status_code == 200:
                status_data = history_response.json()
                print(f"다운로드 상태: {status_data.get('status')}")
                print(f"에러 메시지: {status_data.get('error')}")
            else:
                print(f"상태 확인 실패: {history_response.status_code}")
        
    except Exception as e:
        print(f"테스트 실패: {e}")
    
    # 2. 다운로드 히스토리 확인
    print("\n2. 다운로드 히스토리 확인...")
    try:
        history_response = requests.get(f"{base_url}/history/")
        if history_response.status_code == 200:
            history = history_response.json()
            print(f"히스토리 항목 수: {len(history)}")
            if history:
                latest = history[0]
                print(f"최근 다운로드:")
                print(f"  ID: {latest.get('id')}")
                print(f"  URL: {latest.get('url')}")
                print(f"  상태: {latest.get('status')}")
                print(f"  에러: {latest.get('error')}")
                print(f"  요청 시간: {latest.get('requested_at')}")
        else:
            print(f"히스토리 조회 실패: {history_response.status_code}")
    except Exception as e:
        print(f"히스토리 조회 실패: {e}")
    
    # 3. 활성 다운로드 확인
    print("\n3. 활성 다운로드 확인...")
    try:
        active_response = requests.get(f"{base_url}/downloads/active")
        if active_response.status_code == 200:
            active_data = active_response.json()
            print(f"활성 다운로드 수: {active_data.get('count', 0)}")
            print(f"활성 다운로드 ID들: {active_data.get('active_downloads', [])}")
        else:
            print(f"활성 다운로드 조회 실패: {active_response.status_code}")
    except Exception as e:
        print(f"활성 다운로드 조회 실패: {e}")
    
    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)

if __name__ == "__main__":
    test_download_api()