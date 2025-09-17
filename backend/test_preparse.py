#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1fichier 사전파싱 테스트
"""

import sys
import os

# 백엔드 경로 추가
backend_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_path)

from core.simple_parser import preparse_1fichier_standalone

def test_preparse():
    """사전파싱 테스트"""
    test_url = "https://1fichier.com/?dmfu8vpmkq67httu87o3"

    print("=" * 50)
    print("1fichier 사전파싱 테스트")
    print("=" * 50)

    result = preparse_1fichier_standalone(test_url)

    if result:
        print(f"✅ 사전파싱 성공!")
        print(f"📁 파일명: {result.get('name', 'Unknown')}")
        print(f"📏 파일크기: {result.get('size', 'Unknown')}")
    else:
        print("❌ 사전파싱 실패")

    print("=" * 50)

if __name__ == "__main__":
    test_preparse()