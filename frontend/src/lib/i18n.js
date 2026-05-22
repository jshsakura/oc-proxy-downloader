import { writable, derived, get } from 'svelte/store';

const isLoading = writable(true);
const translations = writable({});
const locale = writable('en');

// Apply text direction (rtl/ltr) and lang attribute to <html> for the active language.
function applyDocumentDirection(lang) {
    if (typeof document === 'undefined') return;
    const entry = get(availableLanguages).find((item) => item.code === lang);
    document.documentElement.lang = lang;
    document.documentElement.dir = entry && entry.rtl ? 'rtl' : 'ltr';
}

async function loadTranslations(lang) {
    isLoading.set(true);
    try {
        const response = await fetch(`/api/locales/${lang}.json`);
        if (!response.ok) {
            throw new Error(`Could not load ${lang}.json (Status: ${response.status})`);
        }
        const data = await response.json();


        translations.set(data);
        locale.set(lang);
        applyDocumentDirection(lang);
    } catch (error) {
        console.error('[i18n] Failed to load translations:', error);
        translations.set({}); // Clear translations on error
    } finally {
        isLoading.set(false);
    }
}

const t = derived(translations, ($translations) => {
    return (key, vars = {}) => {
        let text = $translations[key];

        if (text === undefined) {
            console.warn(`[i18n] Translation key not found: ${key}`);
            return key; // Return the key itself as a fallback
        }

        if (text && typeof text === 'string' && vars) {
            for (const [varKey, value] of Object.entries(vars)) {
                const placeholder = `{${varKey}}`;
                text = text.split(placeholder).join(value);
            }
        }
        return text;
    };
});

// Available languages ([{code, name, rtl}]). Populated from backend /api/locales.
const availableLanguages = writable([]);

// Minimal fallback used when the backend does not respond.
const FALLBACK_LANGUAGES = [
    { code: 'en', name: 'English', rtl: false },
    { code: 'ko', name: '한국어', rtl: false },
];

async function fetchAvailableLanguages() {
    try {
        const response = await fetch('/api/locales');
        if (!response.ok) throw new Error(`Status ${response.status}`);
        const data = await response.json();
        const langs = Array.isArray(data.languages) && data.languages.length
            ? data.languages
            : FALLBACK_LANGUAGES;
        availableLanguages.set(langs);
        return langs;
    } catch (error) {
        console.error('[i18n] Failed to load language list:', error);
        availableLanguages.set(FALLBACK_LANGUAGES);
        return FALLBACK_LANGUAGES;
    }
}

// Resolve a stored/browser language to a supported code (e.g. fall back to a base variant).
function resolveLang(candidate, supportedCodes) {
    if (!candidate) return null;
    if (supportedCodes.includes(candidate)) return candidate;
    const base = candidate.split('-')[0];
    if (supportedCodes.includes(base)) return base;
    return supportedCodes.find((code) => code.split('-')[0] === base) || null;
}

async function initializeLocale() {
    const langs = await fetchAvailableLanguages();
    const supportedCodes = langs.map((item) => item.code);

    const lang =
        resolveLang(localStorage.getItem('lang'), supportedCodes) ||
        resolveLang(navigator.language, supportedCodes) ||
        (supportedCodes.includes('en') ? 'en' : supportedCodes[0]);

    localStorage.setItem('lang', lang);
    return loadTranslations(lang);
}

function formatTimestamp(dateString) {
    if (!dateString) return '';

    const currentLocale = localStorage.getItem('lang') || 'en';
    const date = new Date(dateString);

    // Use the language code directly as the BCP-47 locale; let the locale decide 12/24-hour format.
    const options = {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    };

    return date.toLocaleString(currentLocale, options);
}

export {
    t,
    locale,
    isLoading,
    initializeLocale,
    loadTranslations,
    formatTimestamp,
    availableLanguages,
    fetchAvailableLanguages,
};