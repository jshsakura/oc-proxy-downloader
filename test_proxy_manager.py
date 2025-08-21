#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
프록시 관리 시스템 테스트
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from backend.core.common import get_all_proxies

def test_proxy_system():
    """프록시 시스템 테스트"""
    print("=" * 60)
    print("프록시 관리 시스템 테스트")
    print("=" * 60)
    
    try:
        proxies = get_all_proxies()
        print(f"총 프록시 수: {len(proxies)}")
        
        if proxies:
            print(f"\n처음 10개 프록시:")
            for i, proxy in enumerate(proxies[:10], 1):
                print(f"  {i}. {proxy}")
                
            print(f"\n마지막 5개 프록시:")
            for i, proxy in enumerate(proxies[-5:], len(proxies)-4):
                print(f"  {i}. {proxy}")
        else:
            print("⚠️ 프록시를 찾을 수 없습니다")
    
    except Exception as e:
        print(f"❌ 에러: {e}")
    
    print("\n" + "=" * 60)
    print("테스트 완료")
    print("=" * 60)

if __name__ == "__main__":
    test_proxy_system()