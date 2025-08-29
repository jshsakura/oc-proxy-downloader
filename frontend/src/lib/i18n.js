import { writable, derived } from 'svelte/store';

const isLoading = writable(true);
const translations = writable({});
const locale = writable('en');

async function loadTranslations(lang) {
    isLoading.set(true);
    try {
        // Try API first, with timeout using Promise.race
        const fetchPromise = fetch(`/api/locales/${lang}.json`);
        const timeoutPromise = new Promise((_, reject) => 
            setTimeout(() => reject(new Error('Request timeout')), 3000)
        );
        
        const response = await Promise.race([fetchPromise, timeoutPromise]);
        
        if (!response.ok) {
            throw new Error(`Could not load ${lang}.json (Status: ${response.status})`);
        }
        const data = await response.json();
        console.log(`[i18n] API data keys:`, Object.keys(data).filter(k => k.includes('local')));
        console.log(`[i18n] local_title:`, data.local_title);
        console.log(`[i18n] local_progress_text:`, data.local_progress_text);
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
            "settings_subtitle": lang === 'ko' ? "애플리케이션 설정" : "Application Settings",
            "close": lang === 'ko' ? "닫기" : "Close",
            // 다운로드 상태 라벨 추가 (다국어 지원)
            "download_pending": lang === 'ko' ? "대기 중..." : "Pending...",
            "download_downloading": lang === 'ko' ? "다운로드 중..." : "Downloading...",
            "download_proxying": lang === 'ko' ? "프록시 연결 중..." : "Connecting via proxy...",
            "download_done": lang === 'ko' ? "완료" : "Done",
            "download_failed": lang === 'ko' ? "실패" : "Failed",
            "download_stopped": lang === 'ko' ? "정지" : "Stopped",
            "download_paused": lang === 'ko' ? "일시정지" : "Paused",
            // 프록시 게이지 라벨들
            "proxy_title": lang === 'ko' ? "프록시" : "Proxy",
            "proxy_success": lang === 'ko' ? "성공" : "Success",
            "proxy_failed": lang === 'ko' ? "실패" : "Failed",
            "proxy_blacklisted": lang === 'ko' ? "블랙리스트" : "Blacklisted",
            "proxy_success_tooltip": lang === 'ko' ? "성공한 프록시: {count}개" : "Successful proxies: {count}",
            "proxy_failed_tooltip": lang === 'ko' ? "실패한 프록시: {count}개" : "Failed proxies: {count}",
            "proxy_blacklisted_tooltip": lang === 'ko' ? "블랙리스트 프록시: {count}개" : "Blacklisted proxies: {count}",
            "proxy_unused_tooltip": lang === 'ko' ? "미사용 프록시: {count}개" : "Unused proxies: {count}",
            "proxy_refresh": lang === 'ko' ? "프록시 새로고침" : "Refresh Proxies",
            // 로컬 다운로드 관련
            "local_title": lang === 'ko' ? "로컬" : "Local",
            "local_downloading": lang === 'ko' ? "다운로드 중..." : "Downloading...",
            "local_waiting": lang === 'ko' ? "대기 중..." : "Waiting...",
            "local_completed": lang === 'ko' ? "완료!" : "Completed!",
            "local_failed": lang === 'ko' ? "실패" : "Failed",
            "local_idle": lang === 'ko' ? "대기 중..." : "Idle...",
            "local_progress_text": lang === 'ko' ? "{count}개 진행 중" : "{count} in progress",
            "local_wait_time": lang === 'ko' ? "1fichier 대기 중... {time}초 남음" : "1fichier waiting... {time}s left",
            // 테이블 헤더
            "table_header_proxy": lang === 'ko' ? "프록시" : "Proxy",
            // 프록시 상태창 메시지
            "proxy_idle": lang === 'ko' ? "프록시 대기 중..." : "Proxy idle...",
            "proxy_downloading": lang === 'ko' ? "다운로드 진행 중..." : "Downloads in progress...",
            "proxy_multi_download": lang === 'ko' ? "{count}개 다운로드 진행 중" : "{count} downloads in progress",
            "proxy_refreshing": lang === 'ko' ? "새로고침 중..." : "Refreshing...",
            "proxy_clear_blacklist": lang === 'ko' ? "블랙리스트 해제" : "Clear Blacklist",
            "proxy_clear_blacklist_confirm": lang === 'ko' ? "블랙리스트를 모두 해제하시겠습니까?" : "Are you sure you want to clear all blacklisted proxies?",
            "proxy_refresh_failed": lang === 'ko' ? "프록시 새로고침에 실패했습니다. 서버를 확인해주세요." : "Failed to refresh proxies. Please check the server.",
            "proxy_refresh_error": lang === 'ko' ? "프록시 새로고침 중 오류가 발생했습니다" : "An error occurred while refreshing proxies",
            "proxy_blacklist_clear_failed": lang === 'ko' ? "블랙리스트 해제에 실패했습니다. 서버를 확인해주세요." : "Failed to clear blacklist. Please check the server.",
            "proxy_blacklist_clear_error": lang === 'ko' ? "블랙리스트 해제 중 오류가 발생했습니다" : "An error occurred while clearing blacklist",
            "proxy_multiple_downloads": lang === 'ko' ? "{count}개 다운로드 진행 중" : "{count} downloads in progress",
            "proxy_multiple_downloads_short": lang === 'ko' ? "{count}개 다운로드 진행 중" : "{count} downloads in progress",
            "proxy_recent": lang === 'ko' ? "최근" : "Recent",
            "proxy_link_parsing": lang === 'ko' ? "링크 파싱" : "Link parsing",
            // 툴팁 텍스트
            "proxy_tooltip_proxy": lang === 'ko' ? "프록시" : "Proxy",
            "proxy_tooltip_step": lang === 'ko' ? "단계" : "Step", 
            "proxy_tooltip_progress": lang === 'ko' ? "진행" : "Progress",
            "proxy_tooltip_trying": lang === 'ko' ? "시도 중..." : "Trying...",
            "proxy_tooltip_seconds": lang === 'ko' ? "초" : "s",
            "proxy_tooltip_error": lang === 'ko' ? "오류" : "Error",
            "proxy_in_progress": lang === 'ko' ? "중" : "in progress",
            "proxy_success_msg": lang === 'ko' ? "성공" : "success",
            "proxy_failed_msg": lang === 'ko' ? "실패" : "failed",
            "proxy_waiting": lang === 'ko' ? "프록시 대기 중" : "Waiting for proxy",
            "proxy_exhausted": lang === 'ko' ? "프록시 소진" : "Proxies exhausted",
            // 숫자 표시 형식
            "proxy_count_format": lang === 'ko' ? "{available}/{total}" : "{available}/{total}",
            "proxy_success_count": lang === 'ko' ? "성공 {count}" : "Success {count}",
            "proxy_failed_count": lang === 'ko' ? "실패 {count}" : "Failed {count}",
            "proxy_blacklisted_count": lang === 'ko' ? "블랙리스트 {count}" : "Blacklisted {count}",
            // 시작 버튼 및 대기 상태 관련
            "action_start": lang === 'ko' ? "시작" : "Start",
            "download_added_waiting": lang === 'ko' ? "다운로드가 대기열에 추가되었습니다" : "Download added to queue",
            "download_started": lang === 'ko' ? "다운로드를 시작했습니다" : "Download started",
            // 설정 모달 관련
            "settings_download_path": lang === 'ko' ? "다운로드 경로" : "Download Path",
            "settings_language": lang === 'ko' ? "언어" : "Language", 
            "settings_theme": lang === 'ko' ? "테마" : "Theme",
            "button_cancel": lang === 'ko' ? "취소" : "Cancel",
            "button_save": lang === 'ko' ? "저장" : "Save",
            "theme_light": lang === 'ko' ? "라이트" : "Light",
            "theme_dark": lang === 'ko' ? "다크" : "Dark",
            "theme_dracula": lang === 'ko' ? "드라큘라" : "Dracula",
            "theme_system": lang === 'ko' ? "시스템" : "System",
            "use_proxy": lang === 'ko' ? "프록시 사용" : "Use Proxy",
            // 추가된 번역들
            "download_added_successfully": lang === 'ko' ? "다운로드가 성공적으로 추가되었습니다" : "Download added successfully",
            "delete_confirm": lang === 'ko' ? "이 다운로드를 정말 삭제하시겠습니까?" : "Are you sure you want to delete this download?",
            "confirm_delete_title": lang === 'ko' ? "삭제 확인" : "Confirm Delete",
            "button_delete": lang === 'ko' ? "삭제" : "Delete",
            "clipboard_empty": lang === 'ko' ? "클립보드가 비어있습니다" : "Clipboard is empty",
            "clipboard_read_failed": lang === 'ko' ? "클립보드 읽기에 실패했습니다" : "Failed to read clipboard",
            "adding_download": lang === 'ko' ? "다운로드 추가 중..." : "Adding download...",
            "download_waiting": lang === 'ko' ? "대기중" : "Waiting",
            "time_seconds": lang === 'ko' ? "초" : "s",
            "tab_working": lang === 'ko' ? "진행 중" : "Working",
            "tab_completed": lang === 'ko' ? "완료됨" : "Completed",
            "table_header_size": lang === 'ko' ? "크기" : "Size",
            "table_header_progress": lang === 'ko' ? "진행률" : "Progress",
            "table_header_requested_date": lang === 'ko' ? "요청일시" : "Requested Date",
            "no_working_downloads": lang === 'ko' ? "진행 중인 다운로드가 없습니다." : "No downloads in progress.",
            "no_completed_downloads": lang === 'ko' ? "완료된 다운로드가 없습니다." : "No completed downloads.",
            "file_name_na": lang === 'ko' ? "N/A" : "N/A",
            "action_details": lang === 'ko' ? "상세정보" : "Details",
            "pagination_page_info": lang === 'ko' ? "{currentPage}/{totalPages} 페이지" : "Page {currentPage} of {totalPages}",
            "pagination_previous": lang === 'ko' ? "이전" : "Previous",
            "pagination_next": lang === 'ko' ? "다음" : "Next",
            "confirm_title": lang === 'ko' ? "확인" : "Confirm",
            "button_confirm": lang === 'ko' ? "확인" : "Confirm",
            "copy_success": lang === 'ko' ? "복사되었습니다" : "Copied to clipboard",
            "copy_failed": lang === 'ko' ? "복사에 실패했습니다" : "Failed to copy",
            "detail_modal_title": lang === 'ko' ? "다운로드 상세정보" : "Download Details",
            "detail_not_available": lang === 'ko' ? "N/A" : "N/A",
            "detail_original_url": lang === 'ko' ? "원본 URL" : "Original URL",
            "copy_url": lang === 'ko' ? "URL 복사" : "Copy URL",
            "detail_actual_file_url": lang === 'ko' ? "실제 파일 URL" : "Actual File URL",
            "detail_download_path": lang === 'ko' ? "다운로드 경로" : "Download Path",
            "detail_requested_at": lang === 'ko' ? "요청 시간" : "Requested At",
            "detail_status": lang === 'ko' ? "상태" : "Status",
            "detail_file_name": lang === 'ko' ? "파일 이름" : "File Name",
            "detail_total_size": lang === 'ko' ? "전체 크기" : "Total Size",
            "detail_downloaded_size": lang === 'ko' ? "다운로드된 크기" : "Downloaded Size",
            "detail_finished_at": lang === 'ko' ? "완료 시간" : "Finished At",
            "detail_error_message": lang === 'ko' ? "에러 메시지" : "Error Message",
            "detail_no_error": lang === 'ko' ? "에러 없음" : "No error",
            "copy_error": lang === 'ko' ? "에러 메시지 복사" : "Copy error message",
            "password_modal_title": lang === 'ko' ? "비밀번호 설정" : "Set Password",
            "password_placeholder": lang === 'ko' ? "비밀번호 (선택사항)" : "Password (optional)"
        };
        
        console.log(`[i18n] Using fallback - local_title:`, fallbackTranslations.local_title);
        console.log(`[i18n] Using fallback - local_progress_text:`, fallbackTranslations.local_progress_text);
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
                case 'download_pending':
                    text = 'Pending';
                    break;
                case 'download_downloading':
                    text = 'Downloading';
                    break;
                case 'download_done':
                    text = 'Done';
                    break;
                case 'download_failed':
                    text = 'Failed';
                    break;
                case 'download_stopped':
                    text = 'Stopped';
                    break;
                case 'download_paused':
                    text = 'Paused';
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
                case 'proxy_title':
                    text = 'Proxy';
                    break;
                case 'proxy_success':
                    text = 'Success';
                    break;
                case 'proxy_failed':
                    text = 'Failed';
                    break;
                case 'proxy_blacklisted':
                    text = 'Blacklisted';
                    break;
                case 'proxy_refresh':
                    text = 'Refresh Proxies';
                    break;
                case 'proxy_refreshing':
                    text = 'Refreshing...';
                    break;
                case 'proxy_clear_blacklist':
                    text = 'Clear Blacklist';
                    break;
                case 'proxy_waiting':
                    text = 'Waiting for proxy';
                    break;
                case 'proxy_exhausted':
                    text = 'Proxies exhausted';
                    break;
                case 'proxy_link_parsing':
                    text = 'Link parsing';
                    break;
                case 'proxy_downloading':
                    text = 'Download';
                    break;
                case 'proxy_in_progress':
                    text = 'in progress';
                    break;
                case 'proxy_success_msg':
                    text = 'success';
                    break;
                case 'proxy_failed_msg':
                    text = 'failed';
                    break;
                case 'proxy_recent':
                    text = 'Recent';
                    break;
                case 'proxy_count_format':
                    text = '{available}/{total}';
                    break;
                case 'proxy_success_count':
                    text = 'Success {count}';
                    break;
                case 'proxy_failed_count':
                    text = 'Failed {count}';
                    break;
                case 'proxy_blacklisted_count':
                    text = 'Blacklisted {count}';
                    break;
                case 'action_start':
                    text = 'Start';
                    break;
                case 'download_added_waiting':
                    text = 'Download added to queue';
                    break;
                case 'download_started':
                    text = 'Download started';
                    break;
                case 'download_waiting':
                    text = 'Waiting';
                    break;
                case 'time_seconds':
                    text = 's';
                    break;
                case 'settings_download_path':
                    text = 'Download Path';
                    break;
                case 'settings_language':
                    text = 'Language';
                    break;
                case 'settings_theme':
                    text = 'Theme';
                    break;
                case 'button_cancel':
                    text = 'Cancel';
                    break;
                case 'button_save':
                    text = 'Save';
                    break;
                case 'theme_light':
                    text = 'Light';
                    break;
                case 'theme_dark':
                    text = 'Dark';
                    break;
                case 'theme_dracula':
                    text = 'Dracula';
                    break;
                case 'theme_system':
                    text = 'System';
                    break;
                case 'use_proxy':
                    text = 'Use Proxy';
                    break;
                default:
                    text = key; // Fallback to key if no specific fallback is defined
            }
        }

        if (text && typeof text === 'string' && vars) {
            for (const [varKey, value] of Object.entries(vars)) {
                // 안전한 문자열 치환을 위해 정규식 대신 split/join 사용
                const placeholder = `{${varKey}}`;
                text = text.split(placeholder).join(value);
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

// Format timestamp according to current locale
function formatTimestamp(dateString) {
    if (!dateString) return '';
    
    const currentLocale = localStorage.getItem('lang') || 'en';
    const date = new Date(dateString);
    
    // Use the app's locale setting instead of browser locale
    const localeCode = currentLocale === 'ko' ? 'ko-KR' : 'en-US';
    
    if (currentLocale === 'ko') {
        return date.toLocaleString(localeCode, {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false // Korean uses 24-hour format
        });
    } else {
        return date.toLocaleString(localeCode, {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: true
        });
    }
}

export { t, locale, isLoading, initializeLocale, loadTranslations, formatTimestamp };
