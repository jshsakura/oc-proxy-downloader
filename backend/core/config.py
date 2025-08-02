
import os
from pathlib import Path
import json

CONFIG_FILE = Path(__file__).parent.parent / "config.json"
DEFAULT_CONFIG = {
    "download_path": "./downloads",
    "theme": "light",
    "language": "ko"
}

def get_config():
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
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

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
