import { writable, derived } from 'svelte/store';
import { api } from '../api';

// Downloads store
export const downloads = writable([]);
export const activeDownloads = writable([]);
export const isLoading = writable(false);

// Proxy stats store
export const proxyStats = writable({
    totalProxies: 0,
    availableProxies: 0,
    usedProxies: 0,
    successCount: 0,
    failCount: 0,
    currentProxy: "",
    currentStep: "",
    currentIndex: 0,
    totalAttempting: 0,
    status: "",
    lastError: "",
    activeDownloadCount: 0,
    status_message: ""
});

// Local stats store
export const localStats = writable({
    localDownloadCount: 0,
    localStatus: "",
    localCurrentFile: "",
    localProgress: 0,
    localWaitTime: 0,
    activeLocalDownloads: [],
});

// Derived store for working/completed downloads
export const workingDownloads = derived(downloads, ($downloads) => {
    return $downloads.filter(d => {
        const status = d.status?.toLowerCase?.() || "";
        return !(status === "done" || (status === "stopped" && d.progress >= 100));
    });
});

export const completedDownloads = derived(downloads, ($downloads) => {
    return $downloads.filter(d => {
        const status = d.status?.toLowerCase?.() || "";
        return status === "done" || (status === "stopped" && d.progress >= 100);
    }).sort((a, b) => {
        const aTime = new Date(a.finished_at || a.created_at || 0);
        const bTime = new Date(b.finished_at || b.created_at || 0);
        return bTime.getTime() - aTime.getTime();
    });
});

// Actions to update stores
export async function fetchDownloads() {
    isLoading.set(true);
    try {
        const data = await api.getHistory();
        downloads.set(data.history || []);
    } catch (error) {
        console.error('Failed to fetch downloads:', error);
    } finally {
        isLoading.set(false);
    }
}

export async function fetchProxyStatus() {
    try {
        const data = await api.getProxyStatus();
        proxyStats.update(s => ({
            ...s,
            totalProxies: data.total_proxies,
            availableProxies: data.available_proxies,
            usedProxies: data.used_proxies,
            successCount: data.success_count,
            failCount: data.fail_count,
            status_message: data.status_message,
        }));
    } catch (error) {
        console.error('Failed to fetch proxy status:', error);
    }
}

export async function fetchActiveDownloads() {
    try {
        const data = await api.getActiveDownloads();
        activeDownloads.set(data.downloads || []);
    } catch (error) {
        console.error('Failed to fetch active downloads:', error);
    }
}
