import { writable, derived } from 'svelte/store';

const isLoading = writable(true);
const translations = writable({});
const locale = writable('en');

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

function initializeLocale() {
    const supportedLangs = ['en', 'ko'];
    const storedLang = localStorage.getItem('lang');
    if (storedLang && supportedLangs.includes(storedLang)) {
        return loadTranslations(storedLang);
    }
    const browserLang = navigator.language.split('-')[0];
    const lang = supportedLangs.includes(browserLang) ? browserLang : 'en';
    localStorage.setItem('lang', lang);
    return loadTranslations(lang);
}

function formatTimestamp(dateString) {
    if (!dateString) return '';
    
    const currentLocale = localStorage.getItem('lang') || 'en';
    const date = new Date(dateString);
    
    const localeCode = currentLocale === 'ko' ? 'ko-KR' : 'en-US';
    
    const options = {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: currentLocale !== 'ko'
    };
    
    return date.toLocaleString(localeCode, options);
}

export { t, locale, isLoading, initializeLocale, loadTranslations, formatTimestamp };