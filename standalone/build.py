#!/usr/bin/env python3
"""
OC Proxy Downloader - 올인원 빌드 스크립트
프론트엔드 + 백엔드 전체 빌드 후 EXE 생성
"""
import subprocess
import sys
import os
from pathlib import Path

def run_cmd(cmd, cwd=None):
    """명령어 실행"""
    print(f"실행: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd)
    if result.returncode != 0:
        print(f"실패: {cmd}")
        sys.exit(1)

def main():
    root_dir = Path(__file__).parent.parent
    standalone_dir = Path(__file__).parent

    print("OC Proxy Downloader 전체 빌드")
    print("=" * 60)

    # 1. 프론트엔드 빌드
    print("\n1. 프론트엔드 빌드")
    frontend_dir = root_dir / "frontend"

    # 권한 문제 회피: node_modules 삭제 후 재설치
    node_modules = frontend_dir / "node_modules"
    if node_modules.exists():
        print("node_modules 삭제 (권한 문제 회피)")
        import shutil
        shutil.rmtree(node_modules, ignore_errors=True)

    run_cmd("npm install", cwd=frontend_dir)
    run_cmd("npm run build", cwd=frontend_dir)

    # 2. EXE 빌드
    print("\n2. EXE 빌드")
    os.chdir(standalone_dir)
    run_cmd(f"{sys.executable} -m PyInstaller --clean oc-proxy-downloader.spec")

    print("\n빌드 완료!")
    print(f"실행 파일: {standalone_dir / 'dist' / 'oc-proxy-downloader.exe'}")

if __name__ == "__main__":
    main()