
import os
import sys
from pathlib import Path
import json

# Environment-specific config directory setup
# 1. OC_CONFIG_DIR environment variable (set when running standalone)
# 2. CONFIG_PATH environment variable (set in Docker environment)
# 3. Default: backend/config (local development)
if os.environ.get("OC_CONFIG_DIR"):
    CONFIG_DIR = Path(os.environ["OC_CONFIG_DIR"])
    IS_STANDALONE = True
    print(f"[DEBUG] Standalone CONFIG_DIR: {CONFIG_DIR}")
elif os.environ.get("CONFIG_PATH"):
    CONFIG_DIR = Path(os.environ["CONFIG_PATH"])
    IS_STANDALONE = False
    print(f"[DEBUG] Docker CONFIG_DIR: {CONFIG_DIR}")
else:
    CONFIG_DIR = Path(__file__).parent.parent / "config"
    IS_STANDALONE = False
    print(f"[DEBUG] Local CONFIG_DIR: {CONFIG_DIR}")

# CONFIG_DIR 생성 확보
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = CONFIG_DIR / "config.json"
print(f"[DEBUG] CONFIG_FILE path: {CONFIG_FILE}")

def get_default_download_path():
    """Return default download path by environment"""
    if IS_STANDALONE:
        # Standalone: User downloads folder
        # Use standard downloads folder path
        try:
            if sys.platform.startswith('win'):
                # Windows user downloads folder
                home_downloads = str(Path.home() / "Downloads")
                print(f"[DEBUG] Windows download path: {home_downloads}")

                # Create folder if it doesn't exist
                downloads_path = Path(home_downloads)
                downloads_path.mkdir(exist_ok=True)

                return home_downloads
            else:
                # Linux/Mac downloads folder
                home_downloads = str(Path.home() / "Downloads")
                print(f"[DEBUG] Linux/Mac download path: {home_downloads}")

                # Create folder if it doesn't exist
                downloads_path = Path(home_downloads)
                downloads_path.mkdir(exist_ok=True)

                return home_downloads
        except Exception as e:
            # Final fallback: downloads folder in current directory
            fallback_path = str(Path.cwd() / "downloads")
            print(f"[ERROR] Download path setup failed, using fallback: {fallback_path}, error: {e}")
            Path(fallback_path).mkdir(exist_ok=True)
            return fallback_path
    elif os.environ.get("CONFIG_PATH"):
        # Docker environment: /downloads
        return "/downloads"
    else:
        # Local development: downloads folder in project
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
