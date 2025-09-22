
import os
import sys
from pathlib import Path
import json

# 환경별 config 디렉토리 설정
# 1. OC_CONFIG_DIR 환경변수 (스탠드얼론 실행 시 설정됨)
# 2. CONFIG_PATH 환경변수 (도커 환경에서 설정됨)
# 3. 기본값: backend/config (로컬 개발)
if os.environ.get("OC_CONFIG_DIR"):
    CONFIG_DIR = Path(os.environ["OC_CONFIG_DIR"])
    IS_STANDALONE = True
elif os.environ.get("CONFIG_PATH"):
    CONFIG_DIR = Path(os.environ["CONFIG_PATH"])
    IS_STANDALONE = False
else:
    CONFIG_DIR = Path(__file__).parent.parent / "config"
    IS_STANDALONE = False

CONFIG_FILE = CONFIG_DIR / "config.json"

def get_default_download_path():
    """환경별 기본 다운로드 경로 반환"""
    if IS_STANDALONE:
        # 스탠드얼론: 사용자 다운로드 폴더
        try:
            # Windows 환경에서만 winreg 사용
            if sys.platform.startswith('win'):
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
                    downloads_path = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
                    return downloads_path
            else:
                # Linux/Mac의 경우 일반적인 다운로드 폴더
                return str(Path.home() / "Downloads")
        except:
            # 오류 발생시 기본 경로
            return str(Path.home() / "Downloads")
    elif os.environ.get("CONFIG_PATH"):
        # 도커 환경: /downloads
        return "/downloads"
    else:
        # 로컬 개발: 프로젝트 내 downloads 폴더
        project_root = Path(__file__).parent.parent.parent
        return str(project_root / "downloads")

DEFAULT_CONFIG = {
    "download_path": get_default_download_path(),
    "theme": "light",
    "language": "ko"
}

def get_config():
    # CONFIG_DIR 생성
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"[ERROR] config.json is corrupted or empty. Using default config.")
            # 파일이 손상되었거나 비어있으면 기본값으로 덮어쓰기
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
            return DEFAULT_CONFIG.copy()
    # 파일이 없으면 기본값으로 생성
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
    return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except PermissionError:
        print(f"[WARN] Cannot write to config file: {CONFIG_FILE}")
        print("[WARN] Config changes will not be persisted")

def get_download_path():
    env_path = os.environ.get("DOWNLOAD_PATH")
    if env_path:
        path = Path(env_path)
    else:
        config = get_config()
        raw_path = config.get("download_path", "./downloads")
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(__file__).parent.parent / path
    path.mkdir(parents=True, exist_ok=True)
    return path
