#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
빈 파일 생성 문제 수정 테스트 스크립트
"""

import requests
import time
import json
import os

def test_empty_file_prevention():
    """빈 파일 생성 방지 기능 테스트"""
    base_url = "http://localhost:8000/api"
    
    print("=" * 60)
    print("빈 파일 생성 방지 기능 테스트")
    print("=" * 60)
    
    # 1. 존재하지 않는 파일로 테스트 (404 에러 예상)
    print("\n1. 존재하지 않는 파일 테스트...")
    test_data = {
        "url": "https://1fichier.com/?nonexistent_file_test_123",
        "password": "",
        "use_proxy": False
    }
    
    try:
        response = requests.post(f"{base_url}/download/", json=test_data)
        print(f"응답 상태 코드: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            download_id = result.get('id')
            print(f"다운로드 ID: {download_id}")
            
            # 몇 초 후 상태 확인
            time.sleep(5)
            
            # 상태 확인
            status_response = requests.get(f"{base_url}/history/{download_id}")
            if status_response.status_code == 200:
                status_data = status_response.json()
                print(f"최종 상태: {status_data.get('status')}")
                print(f"에러 메시지: {status_data.get('error')}")
                print(f"다운로드 크기: {status_data.get('downloaded_size')} bytes")
                
                # 다운로드 폴더에 파일이 생성되었는지 확인
                download_path = "C:\\Users\\WIN11\\Downloads"
                possible_files = [
                    f"download_{download_id}",
                    f"download_{download_id}.part"
                ]
                
                files_found = []
                for filename in possible_files:
                    full_path = os.path.join(download_path, filename)
                    if os.path.exists(full_path):
                        file_size = os.path.getsize(full_path)
                        files_found.append(f"{filename} ({file_size} bytes)")
                
                if files_found:
                    print(f"⚠️  생성된 파일: {files_found}")
                    print("❌ 빈 파일이 생성되었습니다!")
                else:
                    print("✅ 빈 파일이 생성되지 않았습니다!")
            else:
                print(f"상태 확인 실패: {status_response.status_code}")
        else:
            print(f"다운로드 요청 실패: {response.status_code}")
            
    except Exception as e:
        print(f"테스트 실패: {e}")
    
    # 2. 일반적인 웹사이트 URL로 테스트 (HTML 응답 예상)
    print("\n2. HTML 응답 테스트...")
    test_data2 = {
        "url": "https://www.google.com",
        "password": "",
        "use_proxy": False
    }
    
    try:
        response = requests.post(f"{base_url}/download/", json=test_data2)
        print(f"응답 상태 코드: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            download_id = result.get('id')
            print(f"다운로드 ID: {download_id}")
            
            # 몇 초 후 상태 확인
            time.sleep(5)
            
            # 상태 확인
            status_response = requests.get(f"{base_url}/history/{download_id}")
            if status_response.status_code == 200:
                status_data = status_response.json()
                print(f"최종 상태: {status_data.get('status')}")
                print(f"에러 메시지: {status_data.get('error')}")
                
                if 'HTML' in str(status_data.get('error', '')):
                    print("✅ HTML 응답이 올바르게 감지되었습니다!")
                else:
                    print("⚠️  HTML 응답 감지가 예상과 다릅니다")
            else:
                print(f"상태 확인 실패: {status_response.status_code}")
        else:
            print(f"다운로드 요청 실패: {response.status_code}")
            
    except Exception as e:
        print(f"테스트 실패: {e}")
    
    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)

if __name__ == "__main__":
    test_empty_file_prevention()