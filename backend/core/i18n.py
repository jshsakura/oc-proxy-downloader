import json
import os

# 번역 캐시
_translations_cache = {}

def load_all_translations():
    """서버 시작 시 모든 번역 파일을 메모리에 로드"""
    global _translations_cache
    
    # Get the absolute path to the locales directory
    locales_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'locales')
    
    # 기본 fallback 번역 (최소한만 유지, JSON 파일이 우선됨)
    fallback_translations = {
        "ko": {},
        "en": {}
    }
    
    # 먼저 fallback 번역으로 초기화
    _translations_cache = fallback_translations.copy()
    
    # 파일에서 번역 로드하여 fallback과 병합
    for lang in ['ko', 'en']:
        locale_file_path = os.path.join(locales_dir, f"{lang}.json")
        try:
            with open(locale_file_path, encoding="utf-8") as f:
                file_translations = json.load(f)
                # fallback과 파일 번역 병합 (파일 번역이 우선)
                _translations_cache[lang].update(file_translations)
                print(f"[i18n] Loaded {len(file_translations)} translations from {lang}.json")
        except Exception as e:
            print(f"[i18n] Failed to load {lang}.json: {e}")
    
    print(f"[i18n] Translation cache initialized with {len(_translations_cache)} languages")

def get_translations(lang="ko"):
    """특정 언어의 모든 번역을 반환"""
    return _translations_cache.get(lang, _translations_cache.get("en", {}))

def get_message(key, lang="ko"):
    """특정 키의 번역 메시지를 반환"""
    translations = get_translations(lang)
    return translations.get(key, key)

def reload_translations():
    """번역 캐시를 다시 로드"""
    global _translations_cache
    print("[i18n] Reloading translations...")
    load_all_translations()
    return True 