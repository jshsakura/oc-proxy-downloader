/**
 * API Service Layer for OC Proxy Downloader
 */

const API_BASE = '/api';

async function request(endpoint, options = {}) {
    const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`;
    
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };

    const mergedOptions = {
        ...defaultOptions,
        ...options,
        headers: {
            ...defaultOptions.headers,
            ...(options.headers || {}),
        },
    };

    try {
        const response = await fetch(url, mergedOptions);
        
        if (!response.ok) {
            let errorDetail = 'API Request Failed';
            try {
                const errorData = await response.json();
                errorDetail = errorData.detail || errorData.message || errorDetail;
            } catch (e) {
                errorDetail = await response.text() || errorDetail;
            }
            throw new Error(errorDetail);
        }

        // Return null for 204 No Content
        if (response.status === 204) return null;
        
        return await response.json();
    } catch (error) {
        console.error(`[API] Error on ${url}:`, error);
        throw error;
    }
}

export const api = {
    // Downloads
    getHistory: () => request('/history/'),
    getWorkingDownloads: (page = 1, pageSize = 50, search = '') => 
        request(`/downloads/working?page=${page}&page_size=${pageSize}${search ? `&search=${encodeURIComponent(search)}` : ''}`),
    getCompletedDownloads: (page = 1, pageSize = 50, search = '') => 
        request(`/downloads/completed?page=${page}&page_size=${pageSize}${search ? `&search=${encodeURIComponent(search)}` : ''}`),
    getActiveDownloads: () => request('/downloads/active'),
    addDownload: (url, password = '', useProxy = true) => 
        request('/download/', {
            method: 'POST',
            body: JSON.stringify({ url, password, use_proxy: useProxy })
        }),
    deleteDownload: (id) => request(`/delete/${id}`, { method: 'DELETE' }),
    toggleProxy: (id) => request(`/downloads/${id}/proxy-toggle`, { method: 'POST' }),
    
    // Commands
    startDownload: (id) => request(`/start/${id}`, { method: 'POST' }),
    pauseDownload: (id) => request(`/pause/${id}`, { method: 'POST' }),
    resumeDownload: (id) => request(`/resume/${id}`, { method: 'POST' }),
    retryDownload: (id) => request(`/retry/${id}`, { method: 'POST' }),
    stopDownload: (id) => request(`/stop/${id}`, { method: 'POST' }),
    
    // Settings
    getSettings: () => request('/settings'),
    saveSettings: (settings) => request('/settings', {
        method: 'POST',
        body: JSON.stringify(settings)
    }),
    selectFolder: () => request('/select_folder'),
    
    // Proxy
    getProxyStatus: () => request('/proxy-status'),
    checkProxyAvailability: () => request('/proxies/available'),
    getUserProxies: (page = 1, pageSize = 10) => 
        request(`/proxies/?page=${page}&page_size=${pageSize}`),
    addUserProxy: (address, description = '') => 
        request('/proxies/', {
            method: 'POST',
            body: JSON.stringify({ address, description })
        }),
    deleteUserProxy: (id) => request(`/proxies/${id}`, { method: 'DELETE' }),
    toggleUserProxy: (id) => request(`/proxies/${id}/toggle`, { method: 'PUT' }),
    refreshProxies: () => request('/proxies/refresh', { method: 'POST' }),
    
    // Auth
    login: (username, password) => request('/login', {
        method: 'POST',
        body: JSON.stringify({ username, password })
    }),
    logout: () => request('/logout', { method: 'POST' }),
    checkAuth: () => request('/auth-check'),
    
    // Locales
    getLocale: (lang) => request(`/locales/${lang}.json`),
    
    // History Period/Stats
    getHistoryStats: (start, end) => {
        const params = new URLSearchParams();
        if (start) params.set('start_date', start);
        if (end) params.set('end_date', end);
        return request(`/history/stats?${params.toString()}`);
    },
    getHistoryPeriod: (start, end, page = 1, pageSize = 50) => {
        const params = new URLSearchParams({ page, page_size: pageSize });
        if (start) params.set('start_date', start);
        if (end) params.set('end_date', end);
        return request(`/history/period?${params.toString()}`);
    }
};
