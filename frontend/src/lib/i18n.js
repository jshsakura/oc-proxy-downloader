import { writable, derived } from 'svelte/store';

const isLoading = writable(true);
const translations = writable({});
const locale = writable('en');

async function loadTranslations(lang) {
    isLoading.set(true);
    try {
        // Try API first, with timeout
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 3000); // 3초 타임아웃
        
        const response = await fetch(`/api/locales/${lang}.json`, {
            signal: controller.signal
        });
        clearTimeout(timeoutId);
        
        if (!response.ok) {
            throw new Error(`Could not load ${lang}.json (Status: ${response.status})`);
        }
        const data = await response.json();
        translations.set(data);
        locale.set(lang);
        console.log(`[i18n] Loaded translations from API for: ${lang}`);
    } catch (error) {
        console.error('[i18n] API failed, using fallback translations:', error);
        // Fallback to embedded minimal translations
        const fallbackTranslations = {
            "title": lang === 'ko' ? "OC Proxy" : "OC Proxy",
            "add_download": lang === 'ko' ? "다운로드 추가" : "Add Download",
            "url_placeholder": lang === 'ko' ? "다운로드 URL" : "Download URL",
            "loading": lang === 'ko' ? "로딩 중..." : "Loading...",
            "table_header_file_name": lang === 'ko' ? "파일 이름" : "File Name",
            "table_header_status": lang === 'ko' ? "상태" : "Status",
            "table_header_actions": lang === 'ko' ? "작업" : "Actions",
            "action_pause": lang === 'ko' ? "일시정지" : "Pause",
            "action_resume": lang === 'ko' ? "재개" : "Resume",
            "action_retry": lang === 'ko' ? "재시도" : "Retry",
            "action_delete": lang === 'ko' ? "삭제" : "Delete",
            "settings_title": lang === 'ko' ? "설정" : "Settings",
            "close": lang === 'ko' ? "닫기" : "Close"
        };
        
        translations.set(fallbackTranslations);
        locale.set(lang);
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
                case 'download_proxying':
                    text = 'Proxying';
                    break;
                case 'clipboard_tooltip':
                    text = 'Paste from clipboard';
                    break;
                case 'clipboard_read_failed':
                    text = 'Failed to read clipboard';
                    break;
                case 'password_tooltip':
                    text = 'Set password';
                    break;
                case 'no_working_downloads':
                    text = 'No downloads in progress.';
                    break;
                case 'no_completed_downloads':
                    text = 'No completed downloads.';
                    break;
                case 'tab_working':
                    text = 'Working';
                    break;
                case 'tab_completed':
                    text = 'Completed';
                    break;
                case 'redownload':
                    text = 'Redownload';
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
        // console.log(`[i18n] Translating key: ${key}, result: ${text}`);
        return text;
    };
});

function initializeLocale() {
    const supportedLangs = ['en', 'ko'];
    // 1. localStorage에 lang이 있으면 그걸 우선 사용
    const storedLang = localStorage.getItem('lang');
    if (storedLang && supportedLangs.includes(storedLang)) {
        return loadTranslations(storedLang);
    }
    // 2. 없으면 브라우저 언어 사용
    const browserLang = navigator.language.split('-')[0];
    const lang = supportedLangs.includes(browserLang) ? browserLang : 'en';
    return loadTranslations(lang);
}

export { t, locale, isLoading, initializeLocale, loadTranslations };
