import glob
import json
import os

# Translation cache: { lang_code: { key: text } }
_translations_cache = {}

# Absolute path to the locales directory
LOCALES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locales"
)

# Language code -> display name written in that language (native name).
# When locales/{code}.json exists, its display name is looked up here.
# Codes missing from this table fall back to using the code itself.
LANGUAGE_NAMES = {
    "ko": "한국어",
    "en": "English",
    "ja": "日本語",
    "zh-CN": "简体中文",
    "zh-TW": "繁體中文",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "ru": "Русский",
    "pt-BR": "Português (Brasil)",
    "it": "Italiano",
    "vi": "Tiếng Việt",
    "id": "Bahasa Indonesia",
    "th": "ไทย",
    "tr": "Türkçe",
    "pl": "Polski",
    "ar": "العربية",
    "nl": "Nederlands",
}

# RTL (right-to-left) language codes. Used by the frontend to apply dir="rtl".
RTL_LANGUAGES = {"ar"}

# Default language (fallback when the requested language is unavailable)
DEFAULT_LANG = "en"


def load_all_translations():
    """Load every locales/{lang}.json into memory at server startup.

    Scans the folder instead of using a hardcoded language list, so a new
    language is recognized automatically by just adding its JSON file.
    """
    global _translations_cache
    _translations_cache = {}

    for locale_file_path in sorted(glob.glob(os.path.join(LOCALES_DIR, "*.json"))):
        lang = os.path.splitext(os.path.basename(locale_file_path))[0]
        with open(locale_file_path, encoding="utf-8") as f:
            file_translations = json.load(f)
        if not isinstance(file_translations, dict):
            print(f"[i18n] Skipped {lang}.json: not a JSON object")
            continue
        _translations_cache[lang] = file_translations
        print(f"[i18n] Loaded {len(file_translations)} translations from {lang}.json")

    print(
        f"[i18n] Translation cache initialized with {len(_translations_cache)} "
        f"languages: {', '.join(sorted(_translations_cache)) or '(none)'}"
    )


def get_translations(lang=DEFAULT_LANG):
    """Return all translations for a language, falling back to the default."""
    return _translations_cache.get(lang, _translations_cache.get(DEFAULT_LANG, {}))


def get_message(key, lang=DEFAULT_LANG):
    """Return the translated message for a key, or the key itself if missing."""
    translations = get_translations(lang)
    return translations.get(key, key)


def get_available_languages():
    """Return loaded languages as [{code, name, rtl}], sorted by display name."""
    languages = [
        {
            "code": code,
            "name": LANGUAGE_NAMES.get(code, code),
            "rtl": code in RTL_LANGUAGES,
        }
        for code in _translations_cache
    ]
    return sorted(languages, key=lambda item: item["name"])


def reload_translations():
    """Reload the translation cache from disk."""
    print("[i18n] Reloading translations...")
    load_all_translations()
    return True
