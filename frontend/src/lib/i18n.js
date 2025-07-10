import { writable, derived } from 'svelte/store';

const isLoading = writable(true);
const translations = writable({});
const locale = writable('en');

async function loadTranslations(lang) {
    isLoading.set(true);
    console.log(`[i18n] Attempting to load translations for: ${lang}`);
    try {
        const response = await fetch(`/api/locales/${lang}.json`);
        console.log(`[i18n] Response for ${lang}.json: ${response.status} ${response.statusText}, ok: ${response.ok}`);
        if (!response.ok) {
            throw new Error(`Could not load ${lang}.json (Status: ${response.status})`);
        }
        const data = await response.json();
        console.log(`[i18n] Loaded data for ${lang}.json:`, data);
        translations.set(data);
        locale.set(lang);
        console.log(`[i18n] Translations store after set:`, translations);
    } catch (error) {
        console.error('[i18n] Failed to load translations:', error);
        // Fallback to English if loading fails for the requested language
        if (lang !== 'en') {
            console.log('[i18n] Falling back to English translations.');
            await loadTranslations('en');
        } else {
            // If even English fails, set an empty object to prevent errors
            translations.set({});
            locale.set('en');
        }
    } finally {
        isLoading.set(false);
    }
}

const t = derived(translations, ($translations) => {
    return (key, vars = {}) => {
        let text = $translations[key];
        
        // Fallback for critical keys if translation is not found
        if (text === undefined) {
            switch (key) {
                case 'no_downloads_message':
                    text = 'No downloads yet. Please add a URL to download.';
                    break;
                case 'title':
                    text = 'OC-Proxy';
                    break;
                case 'table_header_file_name':
                    text = 'File Name';
                    break;
                case 'table_header_status':
                    text = 'Status';
                    break;
                case 'table_header_size':
                    text = 'Size';
                    break;
                case 'table_header_requested_at':
                    text = 'Requested At';
                    break;
                case 'table_header_actions':
                    text = 'Actions';
                    break;
                case 'url_placeholder':
                    text = 'Download URL';
                    break;
                case 'password_placeholder':
                    text = 'Password (optional)';
                    break;
                case 'add_download':
                    text = 'Add Download';
                    break;
                case 'pagination_previous':
                    text = 'Previous';
                    break;
                case 'pagination_next':
                    text = 'Next';
                    break;
                case 'pagination_page_info':
                    text = 'Page {currentPage} of {totalPages}';
                    break;
                case 'action_pause':
                    text = 'Pause';
                    break;
                case 'action_resume':
                    text = 'Resume';
                    break;
                case 'action_retry':
                    text = 'Retry';
                    break;
                case 'action_delete':
                    text = 'Delete';
                    break;
                case 'delete_confirm':
                    text = 'Are you sure you want to delete this download?';
                    break;
                default:
                    text = key; // Fallback to key if no specific fallback is defined
            }
        }

        if (text && typeof text === 'string' && vars) {
            for (const [varKey, value] of Object.entries(vars)) {
                text = text.replace(new RegExp(`{${varKey}}`, 'g'), value);
            }
        }
        console.log(`[i18n] Translating key: ${key}, result: ${text}`);
        return text;
    };
});

function initializeLocale() {
    const browserLang = navigator.language.split('-')[0];
    const supportedLangs = ['en', 'ko'];
    const lang = supportedLangs.includes(browserLang) ? browserLang : 'en';
    return loadTranslations(lang);
}

export { t, locale, isLoading, initializeLocale };
