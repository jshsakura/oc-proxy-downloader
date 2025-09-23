# -*- mode: python ; coding: utf-8 -*-
"""
OC Proxy Downloader - 단일 EXE 빌드
래퍼 제거하고 main.py 직접 사용
"""

import sys
from pathlib import Path

# 경로 설정
backend_dir = Path("../backend").resolve()
frontend_dist_dir = Path("../frontend/dist").resolve()

# 백엔드 Python 모듈들 수집 (main.py 제외)
def collect_backend_modules():
    """백엔드 Python 모듈들을 수집"""
    files = []
    for py_file in backend_dir.rglob("*.py"):
        if "__pycache__" in str(py_file) or py_file.name == "main.py":
            continue
        rel_path = py_file.relative_to(backend_dir)
        files.append((str(py_file), str(rel_path.parent)))
    return files

# 프론트엔드 정적 파일들 수집
def collect_frontend_files():
    """프론트엔드 빌드 파일들을 static 폴더로 수집"""
    files = []
    if not frontend_dist_dir.exists():
        print(f"WARNING: Frontend dist directory not found: {frontend_dist_dir}")
        print("Run 'npm run build' in frontend directory first!")
        return files

    for file in frontend_dist_dir.rglob("*"):
        if file.is_file():
            rel_path = file.relative_to(frontend_dist_dir)
            # static 폴더로 통합
            files.append((str(file), f"static/{rel_path.parent}" if rel_path.parent != Path(".") else "static"))
    return files

# 데이터 파일들 수집
datas = []

# 백엔드 모듈들 추가
backend_modules = collect_backend_modules()
datas.extend(backend_modules)

# 프론트엔드 파일들 추가
frontend_files = collect_frontend_files()
datas.extend(frontend_files)

# 로케일 파일들 추가
locales_dir = backend_dir / "locales"
if locales_dir.exists():
    for locale_file in locales_dir.glob("*.json"):
        datas.append((str(locale_file), "locales"))

print(f"Total data files: {len(datas)}")

a = Analysis(
    [str(backend_dir / "main.py")],  # main.py 직접 사용
    pathex=[str(backend_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'uvicorn',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.http.auto',
        'uvicorn.loops.auto',
        'fastapi',
        'starlette',
        'sqlalchemy.dialects.sqlite',
        'aiohttp',
        'cloudscraper',
        'bs4',
        'yaml',
        'dotenv',
        'multipart',
        'jinja2',
        'aiofiles',
        'psutil',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'scipy',
        'numpy.distutils',
        'distutils',
        'setuptools',
        'wheel',
        'pip',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=True,  # 아카이브 비활성화
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

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
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_icon.ico',
    contents_directory='.',
)