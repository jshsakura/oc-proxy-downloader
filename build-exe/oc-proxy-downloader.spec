# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

# 프로젝트 루트 경로
project_root = Path('.').parent.absolute()
backend_path = project_root / 'backend'
frontend_dist = project_root / 'frontend' / 'dist'

# 백엔드 파이썬 파일들 수집
backend_files = []
for root, dirs, files in os.walk(backend_path):
    # __pycache__ 디렉토리 제외
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for file in files:
        if file.endswith('.py'):
            src = os.path.join(root, file)
            # 상대 경로로 변환
            rel_path = os.path.relpath(src, project_root)
            dst = os.path.dirname(rel_path)
            backend_files.append((src, dst))

# Frontend 빌드 파일들 수집
frontend_files = []
if frontend_dist.exists():
    for root, dirs, files in os.walk(frontend_dist):
        for file in files:
            src = os.path.join(root, file)
            # frontend/dist 기준 상대 경로
            rel_path = os.path.relpath(src, frontend_dist)
            dst = os.path.join('frontend', 'dist', os.path.dirname(rel_path)) if os.path.dirname(rel_path) != '.' else os.path.join('frontend', 'dist')
            frontend_files.append((src, dst))

block_cipher = None

a = Analysis(
    ['main_exe.py'],
    pathex=[str(backend_path)],
    binaries=[],
    datas=backend_files + frontend_files,
    hiddenimports=[
        'backend',
        'backend.main',
        'backend.core',
        'backend.core.app_factory',
        'backend.core.auth',
        'backend.core.common',
        'backend.core.config',
        'backend.core.db',
        'backend.core.download_core',
        'backend.core.error_handling',
        'backend.core.i18n',
        'backend.core.models',
        'backend.core.notifications',
        'backend.core.parser',
        'backend.core.proxy_manager',
        'backend.core.simple_parser',
        'backend.services',
        'backend.services.download_service',
        'backend.services.notification_service',
        'backend.services.preparse_service',
        'backend.api',
        'backend.api.middleware',
        'backend.utils',
        'backend.utils.logging',
        'uvicorn',
        'uvicorn.main',
        'uvicorn.server',
        'fastapi',
        'fastapi.staticfiles',
        'sqlalchemy',
        'sqlalchemy.ext.declarative',
        'pydantic',
        'aiohttp',
        'requests',
        'cloudscraper',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='OC-Proxy-Downloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 아이콘 파일이 있다면 여기에 경로 추가
)