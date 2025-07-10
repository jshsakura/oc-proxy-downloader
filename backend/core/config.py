
import json
import os
from pathlib import Path

CONFIG_FILE = Path('config.json')
DEFAULT_CONFIG = {
    'download_path': 'downloads',
    'theme': 'system'
}

def get_config():
    if not CONFIG_FILE.is_file():
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    
    with open(CONFIG_FILE, 'r') as f:
        try:
            config = json.load(f)
            # Ensure all default keys exist
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
            return config
        except json.JSONDecodeError:
            return DEFAULT_CONFIG

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def get_download_path() -> Path:
    config = get_config()
    path = Path(config.get('download_path', DEFAULT_CONFIG['download_path']))
    path.mkdir(parents=True, exist_ok=True)
    return path
