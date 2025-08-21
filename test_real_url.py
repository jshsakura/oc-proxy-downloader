#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
실제 1fichier URL 테스트
"""

import requests
import time
import json

def test_real_1fichier_url():
    """실제 1fichier URL로 다운로드 테스트"""
    base_url = "http://127.0.0.1:8001/api"
    
    print("=" * 60)
    print("실제 1fichier URL 테스트")
    print("=" * 60)
    
    # 사용자가 제공한 실제 URL
    test_data = {
        "url": "https://1fichier.com/?kz7su8x41zy3srpi84lo",
        "password": "",
        "use_proxy": False
    }
    
    try:
        print(f"다운로드 요청 URL: {test_data['url']}")
        response = requests.post(f"{base_url}/download/", json=test_data)
        print(f"응답 상태 코드: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            download_id = result.get('id')
            print(f"다운로드 ID: {download_id}")
            
            # 진행 상황 모니터링
            for i in range(20):  # 최대 20번 확인 (2분)
                time.sleep(6)  # 6초마다 확인
                
                status_response = requests.get(f"{base_url}/history/{download_id}")
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    status = status_data.get('status')
                    print(f"[{i+1}] 상태: {status}")
                    
                    if status_data.get('error'):
                        print(f"에러 메시지: {status_data.get('error')}")
                    
                    if status_data.get('downloaded_size'):
                        print(f"다운로드 크기: {status_data.get('downloaded_size')} bytes")
                    
                    if status in ['completed', 'failed', 'error']:
                        print(f"\n최종 상태: {status}")
                        if status_data.get('filename'):
                            print(f"파일명: {status_data.get('filename')}")
                        if status_data.get('file_size'):
                            print(f"파일 크기: {status_data.get('file_size')} bytes")
                        break
                else:
                    print(f"상태 확인 실패: {status_response.status_code}")
                    break
        else:
            print(f"다운로드 요청 실패: {response.status_code}")
            if response.text:
                print(f"응답 내용: {response.text}")
            
    except Exception as e:
        print(f"테스트 실패: {e}")
    
    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)

if __name__ == "__main__":
    test_real_1fichier_url()