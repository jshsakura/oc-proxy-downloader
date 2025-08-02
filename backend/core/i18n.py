import json
import os

def get_message(key, lang="ko"):
    # Get the absolute path to the locales directory
    locales_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'locales')
    locale_file_path = os.path.join(locales_dir, f"{lang}.json")

    try:
        with open(locale_file_path, encoding="utf-8") as f:
            messages = json.load(f)
        return messages.get(key, key)
    except Exception:
        return key 