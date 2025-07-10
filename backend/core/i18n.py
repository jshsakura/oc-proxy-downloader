import json
import os

def get_message(key, lang="ko"):
    # Get the absolute path to the backend directory
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    locale_file_path = os.path.join(backend_dir, "locales", f"{lang}.json")

    try:
        with open(locale_file_path, encoding="utf-8") as f:
            messages = json.load(f)
        return messages.get(key, key)
    except Exception:
        return key 