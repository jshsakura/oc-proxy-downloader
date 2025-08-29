# -*- mode: python ; coding: utf-8 -*-
"""
OC Proxy Downloader - Standalone EXE PyInstaller 설정
"""

import sys
from pathlib import Path

# 현재 작업 디렉토리
WORK_DIR = Path.cwd()
PROJECT_ROOT = WORK_DIR.parent

block_cipher = None

a = Analysis(
    ['main_standalone.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 프론트엔드 빌드 파일들
        (str(PROJECT_ROOT / 'frontend' / 'build'), 'frontend/build'),
        
        # 백엔드 모듈들
        (str(PROJECT_ROOT / 'backend' / 'core'), 'core'),
        (str(PROJECT_ROOT / 'backend' / 'config'), 'config'),
        (str(PROJECT_ROOT / 'backend' / 'main.py'), '.'),
    ],
    hiddenimports=[
        # FastAPI 관련
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'fastapi',
        'fastapi.routing',
        'fastapi.staticfiles',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'fastapi.responses',
        
        # SQLAlchemy 관련
        'sqlalchemy',
        'sqlalchemy.dialects',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.pool',
        'sqlalchemy.engine',
        'sqlalchemy.ext',
        'sqlalchemy.ext.declarative',
        'sqlalchemy.orm',
        'sqlalchemy.sql',
        
        # 기타 의존성
        'selenium',
        'selenium.webdriver',
        'selenium.webdriver.chrome',
        'selenium.webdriver.chrome.service',
        'selenium.webdriver.chrome.options',
        'selenium.webdriver.common',
        'selenium.webdriver.common.by',
        'selenium.webdriver.support',
        'selenium.webdriver.support.ui',
        'selenium.webdriver.support.expected_conditions',
        'requests',
        'beautifulsoup4',
        'bs4',
        'lxml',
        'lxml.etree',
        'lxml._elementpath',
        'python-multipart',
        'websockets',
        'python-dotenv',
        'cloudscraper',
        'pydantic',
        'starlette',
        'starlette.middleware',
        'starlette.responses',
        'starlette.staticfiles',
        
        # Python 표준 라이브러리
        'queue',
        'threading',
        'asyncio',
        'json',
        'pathlib',
        'datetime',
        'time',
        'webbrowser',
        'logging',
        'signal',
        'atexit',
        'multipart',
        'email',
        'email.mime',
        'email.mime.multipart',
        'email.mime.text',
        
        # 우리 모듈들
        'core',
        'core.db',
        'core.models',
        'core.shared',
        'core.download_core',
        'core.parser_service',
        'core.proxy_manager',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 불필요한 패키지들
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'pytest',
        'IPython',
        'jupyter',
    ],
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
    name='oc-proxy-downloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 콘솔 창 표시 (로그 확인용)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None
)