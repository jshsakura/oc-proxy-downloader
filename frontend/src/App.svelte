<script>
  import logo from "./assets/images/logo256.png";
  import SettingsModal from "./lib/SettingsModal.svelte";
  import PasswordModal from "./lib/PasswordModal.svelte";
  import { onMount } from "svelte";
  import { theme } from "./lib/theme.js";
  import {
    t,
    isLoading,
    initializeLocale,
    loadTranslations,
    formatTimestamp,
  } from "./lib/i18n.js";
  import DetailModal from "./lib/DetailModal.svelte";
  import PauseIcon from "./icons/PauseIcon.svelte";
  import StopIcon from "./icons/StopIcon.svelte";
  import ResumeIcon from "./icons/ResumeIcon.svelte";
  import RetryIcon from "./icons/RetryIcon.svelte";
  import DeleteIcon from "./icons/DeleteIcon.svelte";
  import ClipboardIcon from "./icons/ClipboardIcon.svelte";
  import LockIcon from "./icons/LockIcon.svelte";
  import UnlockIcon from "./icons/UnlockIcon.svelte";
  import FolderIcon from "./icons/FolderIcon.svelte";
  import InfoIcon from "./icons/InfoIcon.svelte";
  import LinkCopyIcon from "./icons/LinkCopyIcon.svelte";
  import DownloadIcon from "./icons/DownloadIcon.svelte";
  import SettingsIcon from "./icons/SettingsIcon.svelte";
  import { toastMessage, showToast, showToastMsg } from "./lib/toast.js";
  import ConfirmModal from "./lib/ConfirmModal.svelte";
  import ProxyGauge from "./lib/ProxyGauge.svelte";
  import LocalGauge from "./lib/LocalGauge.svelte";

  console.log(
    '%c ██████  ██████   ██████ ██████  ███████    ████    ██   ██████  ██████ ██     █████    ███     ██████  █████ ██████ █████████████  \n' +
      "██    ███         ██   ████   ████    ████ ██  ██  ██    ██   ████    ████     ██████   ███    ██    ████   ████   ████     ██   ██ \n" +
      "██    ████        ██████ ██████ ██    ██ ███    ████     ██   ████    ████  █  ████ ██  ███    ██    ███████████   ███████  ██████  \n" +
      "██    ███         ██     ██   ████    ████ ██    ██      ██   ████    ████ ███ ████  ██ ███    ██    ████   ████   ████     ██   ██ \n" +
      " ██████  ██████   ██     ██   ██ ███████    ██   ██      ██████  ██████  ███ ███ ██   ██████████████████     ███████ █████████   ██ \n" +
      "                                                                                                                                       \n" +
      "                                                                                                                                       ",
    "color: #474BDF; font-weight: bold; font-size: 12px;"
  );
  console.log(
    '%cBy Husband of Rebekah',
    "color: #bd93f9; font-weight: bold; font-size: 12px;"
  );

  let downloads = [];
  let url = "";
  let password = "";
  let ws;
  let currentPage = 1;
  let totalPages = 1;
  let isDownloadsLoading = false;
  let isAddingDownload = false;
  let activeDownloads = [];

  let showSettingsModal = false;
  let showPasswordModal = false;
  let showDetailModal = false;
  let currentSettings = {};
  let hasPassword = false;
  let selectedDownload = {};
  let downloadPath = "";
  let prevLang = null;
  let useProxy = false;
  let proxyAvailable = false;

  let proxyStats = {
    totalProxies: 0,
    availableProxies: 0,
    usedProxies: 0,
    successCount: 0,
    failCount: 0
  };

  let localStats = {
    localDownloadCount: 0,
    localStatus: "",
    localCurrentFile: "",
    localProgress: 0,
    localWaitTime: 0,
    activeLocalDownloads: [],
  };

  let downloadProxyInfo = {};
  let downloadWaitInfo = {};

  let showConfirm = false;
  let confirmMessage = "";
  let confirmAction = null;
  let confirmTitle = null;
  let confirmIcon = null;
  let confirmButtonText = null;
  let cancelButtonText = null;

  let isDark =
    typeof document !== "undefined" && document.body.classList.contains("dark");

  let currentTab = "working";

  function openConfirm({
    message,
    onConfirm,
    title = null,
    icon = null,
    confirmText = null,
    cancelText = null,
  }) {
    confirmMessage = message;
    confirmAction = () => {
      onConfirm && onConfirm();
      showConfirm = false;
    };
    confirmTitle = title;
    confirmIcon = icon;
    confirmButtonText = confirmText;
    cancelButtonText = cancelText;
    showConfirm = true;
  }

  const themeIcons = {
    light: "☀️",
    dark: "🌙",
    dracula: "🧛‍♂️",
    system: "🖥️",
  };

  onMount(async () => {
    await fetchSettings();
    if (currentSettings.language) {
      localStorage.setItem("lang", currentSettings.language);
      await loadTranslations(currentSettings.language);
      prevLang = currentSettings.language;
    } else {
      const lang = localStorage.getItem("lang");
      if (lang) {
        await loadTranslations(lang);
        prevLang = lang;
      } else {
        await initializeLocale();
        prevLang = localStorage.getItem("lang");
      }
    }
    fetchDownloads(currentPage);
    connectWebSocket();
    fetchActiveDownloads();
    fetchProxyStatus();
    checkProxyAvailability();

    const unsubscribe = t.subscribe((t_func) => {
      document.title = t_func("title");
    });
  });

  async function fetchSettings() {
    try {
      const response = await fetch("/api/settings");
      if (response.ok) {
        const settingsData = await response.json();
        currentSettings = settingsData;
        downloadPath = settingsData.download_path || "";
      } else {
        console.error("Failed to fetch settings");
      }
    } catch (error) {
      console.error("Error fetching settings:", error);
    }
  }

  async function fetchProxyStatus() {
    try {
      const response = await fetch('/api/proxy-status');
      if (response.ok) {
        const data = await response.json();
        proxyStats = {
          totalProxies: data.total_proxies,
          availableProxies: data.available_proxies,
          usedProxies: data.used_proxies,
          successCount: data.success_count,
          failCount: data.fail_count
        };
      }
    } catch (error) {
      console.error($t('proxy_status_fetch_failed'), error);
    }
  }

  async function checkProxyAvailability() {
    try {
      const response = await fetch('/api/proxies/available');
      if (response.ok) {
        const data = await response.json();
        proxyAvailable = data.available;
        if (!proxyAvailable && useProxy) {
          useProxy = false;
        }
      }
    } catch (error) {
      console.error($t('proxy_availability_check_failed'), error);
      proxyAvailable = false;
    }
  }

  function connectWebSocket() {
    console.log("Attempting to connect WebSocket...");
    const isHttps = window.location.protocol === "https:";
    const wsProtocol = isHttps ? "wss" : "ws";
    const wsUrl = `${wsProtocol}://${window.location.host}/ws/status`;
    console.log(`Protocol: ${window.location.protocol}, Using WebSocket protocol: ${wsProtocol}`);
    console.log("Connecting to WebSocket at:", wsUrl);
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("WebSocket connected!");
    };

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      console.log("WebSocket message received:", message);
      if (message.type === "status_update") {
        const updatedDownload = message.data;
        console.log("Updated download data:", updatedDownload);
        const index = downloads.findIndex((d) => d.id === updatedDownload.id);
        console.log("Found index:", index);
        if (index !== -1) {
          downloads = downloads.map((d, i) =>
            i === index ? updatedDownload : d
          );
        } else {
          downloads = [updatedDownload, ...downloads];
        }
        fetchProxyStatus();
        updateLocalStats(downloads);

        if (updatedDownload.status === "failed" && updatedDownload.error) {
          showToastMsg($t('download_failed_with_error', {error: updatedDownload.error}));
        }
        
        if (updatedDownload.status === "done") {
          showToastMsg($t('download_complete_with_filename', {filename: updatedDownload.file_name || $t('file')}));
          if (currentTab === "working") {
            setTimeout(() => {
              currentTab = "completed";
            }, 1500);
          }
        }
        
        if (["stopped", "done", "failed"].includes(updatedDownload.status)) {
          if (downloadWaitInfo[updatedDownload.id]) {
            delete downloadWaitInfo[updatedDownload.id];
            downloadWaitInfo = { ...downloadWaitInfo };
            console.log($t('wait_info_removed', {id: updatedDownload.id, status: updatedDownload.status}));
          }
        }
      } else if (message.type === "proxy_update") {
        console.log("Proxy status update:", message.data);
        fetchProxyStatus();
      } else if (message.type === "proxy_reset") {
        console.log("Proxy reset:", message.data);
        fetchProxyStatus();
        showToastMsg($t('proxy_reset_success'), "success");

        fetchActiveDownloads();
      } else if (message.type === "progress_update") {
        const progressData = message.data;
        console.log("Progress update received:", progressData);
        
        const index = downloads.findIndex((d) => d.id === progressData.id);
        console.log("Found download at index:", index, "for ID:", progressData.id);
        
        if (index !== -1) {
          console.log("Before update:", {
            downloaded_size: downloads[index].downloaded_size,
            total_size: downloads[index].total_size,
            progress: downloads[index].progress
          });
          
          downloads[index].downloaded_size = progressData.downloaded_size;
          downloads[index].total_size = progressData.total_size;
          downloads[index].progress = progressData.progress;
          
          console.log("After update:", {
            downloaded_size: downloads[index].downloaded_size,
            total_size: downloads[index].total_size,
            progress: downloads[index].progress
          });
          
          downloads = [...downloads];
        } else {
          console.log("Download not found in list. Current downloads:", downloads.map(d => ({ id: d.id, url: d.url })));
        }
      } else if (message.type === "proxy_trying") {
        console.log("Proxy trying:", message.data);
        
        proxyStats.currentProxy = message.data.proxy;
        proxyStats.currentStep = message.data.step;
        proxyStats.currentIndex = message.data.current;
        proxyStats.totalAttempting = message.data.total;
        proxyStats.status = "trying";
        proxyStats = { ...proxyStats };
        
        const matchingDownload = downloads.find(d => d.url === message.data.url);
        if (matchingDownload) {
          downloadProxyInfo[matchingDownload.id] = {
            proxy: message.data.proxy,
            step: message.data.step,
            current: message.data.current,
            total: message.data.total,
            status: "trying",
            timestamp: Date.now()
          };
          downloadProxyInfo = { ...downloadProxyInfo };
        }
        
      } else if (message.type === "proxy_success") {
        console.log("Proxy success:", message.data);
        
        proxyStats.currentProxy = message.data.proxy;
        proxyStats.currentStep = message.data.step;
        proxyStats.status = "success";
        proxyStats = { ...proxyStats };
        fetchProxyStatus();
        
        const matchingDownload = downloads.find(d => d.url === message.data.url);
        if (matchingDownload) {
          downloadProxyInfo[matchingDownload.id] = {
            ...downloadProxyInfo[matchingDownload.id],
            proxy: message.data.proxy,
            step: message.data.step,
            status: "success",
            timestamp: Date.now()
          };
          downloadProxyInfo = { ...downloadProxyInfo };
        }
        
      } else if (message.type === "proxy_failed") {
        console.log("Proxy failed:", message.data);
        
        proxyStats.currentProxy = message.data.proxy;
        proxyStats.currentStep = message.data.step;
        proxyStats.status = "failed";
        proxyStats.lastError = message.data.error;
        proxyStats = { ...proxyStats };
        fetchProxyStatus();
        
        const matchingDownload = downloads.find(d => d.url === message.data.url);
        if (matchingDownload) {
          downloadProxyInfo[matchingDownload.id] = {
            ...downloadProxyInfo[matchingDownload.id],
            proxy: message.data.proxy,
            step: message.data.step,
            status: "failed",
            error: message.data.error,
            timestamp: Date.now()
          };
          downloadProxyInfo = { ...downloadProxyInfo };
        }
      } else if (message.type === "wait_countdown") {
        console.log("Wait countdown:", message.data);
        
        const matchingDownload = downloads.find(d => d.url === message.data.url);
        if (matchingDownload) {
          downloadWaitInfo[matchingDownload.id] = {
            remaining_time: message.data.remaining_time,
            total_wait_time: message.data.total_wait_time,
            proxy_addr: message.data.proxy_addr,
            timestamp: Date.now()
          };
          downloadWaitInfo = { ...downloadWaitInfo };
          
          if (message.data.remaining_time <= 0) {
            setTimeout(() => {
              delete downloadWaitInfo[matchingDownload.id];
              downloadWaitInfo = { ...downloadWaitInfo };
            }, 2000);
          }
        }
      } else if (message.type === "filename_update") {
        console.log("Filename update received:", message.data);
        const index = downloads.findIndex((d) => d.id === message.data.id);
        if (index !== -1) {
          downloads[index].file_name = message.data.file_name;
          downloads = [...downloads];
          console.log(`Updated filename for download ${message.data.id}: ${message.data.file_name}`);
          updateLocalStats(downloads);
        }
      }
    };

    ws.onclose = () => {
      console.log("WebSocket disconnected. Attempting to reconnect...");
      setTimeout(connectWebSocket, 5000);
    };
  }

  async function fetchDownloads(page = 1) {
    console.log("=== fetchDownloads called ===");
    isDownloadsLoading = true;
    console.log("isDownloadsLoading set to:", isDownloadsLoading);
    try {
      const response = await fetch(`/api/history/`);
      console.log("History API response status:", response.status);
      if (response.ok) {
        const data = await response.json();
        console.log("History API response:", data);
        if (Array.isArray(data) && data.length > 0) {
          console.log("First download status:", data[0].status);
          console.log("All download statuses:", data.map(d => d.status));
        }
        downloads = data;
        currentPage = 1;
        totalPages = 1;
        
        updateLocalStats(data);
      } else {
        console.error("History API failed with status:", response.status);
        const errorText = await response.text();
        console.error("Error response:", errorText);
        downloads = [];
      }
    } catch (error) {
      console.error("Error fetching downloads:", error);
      downloads = [];
    } finally {
      isDownloadsLoading = false;
      console.log("isDownloadsLoading set to:", isDownloadsLoading);
      console.log("Final downloads state:", downloads);
      console.log("=== fetchDownloads completed ===");
    }
  }

  function updateLocalStats(downloadsData) {
    if (!downloadsData) return;
    
    const localDownloads = downloadsData.filter(d => !d.use_proxy);
    
    const activeLocalDownloads = localDownloads.filter(d => 
      ['downloading', 'pending'].includes(d.status?.toLowerCase())
    );
    
    const currentDownloading = activeLocalDownloads.find(d => d.status?.toLowerCase() === 'downloading');
    
    localStats.localDownloadCount = activeLocalDownloads.length;
    localStats.localCurrentFile = currentDownloading?.file_name || 
                                  activeLocalDownloads[0]?.file_name || "";
    
    if (currentDownloading) {
      localStats.localStatus = "downloading";
      if (currentDownloading.total_size > 0 && currentDownloading.downloaded_size >= 0) {
        localStats.localProgress = Math.round(
          (currentDownloading.downloaded_size / currentDownloading.total_size) * 100
        );
      } else {
        localStats.localProgress = 0;
      }
    } else if (activeLocalDownloads.length > 0) {
      localStats.localStatus = "waiting";
      localStats.localProgress = 0;
    } else {
      localStats.localStatus = "";
      localStats.localProgress = 0;
    }
    
    localStats.activeLocalDownloads = activeLocalDownloads.map(d => ({
      file_name: d.file_name,
      progress: d.total_size > 0 ? Math.round((d.downloaded_size / d.total_size) * 100) : 0,
      status: d.status
    }));
    
    localStats = { ...localStats };
  }

  async function addDownload() {
    if (!url) return;
    isAddingDownload = true;
    try {
      const response = await fetch("/api/download/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, password, use_proxy: useProxy }),
      });
      if (response.ok) {
        const newDownload = await response.json();
        if (newDownload.status === 'waiting' && newDownload.message_key) {
          showToastMsg($t(newDownload.message_key, newDownload.message_args));
        } else {
          showToastMsg($t("download_added_successfully"));
        }
        url = "";
        password = "";
        hasPassword = false;
        fetchDownloads(currentPage);
      } else {
        const errorData = await response.json();
        showToastMsg($t('add_download_failed', {detail: errorData.detail}));
      }
    } catch (error) {
      console.error("Error adding download:", error);
      showToastMsg($t('add_download_error'));
    } finally {
      isAddingDownload = false;
    }
  }

  async function fetchActiveDownloads() {
    try {
      const response = await fetch("/api/downloads/active");
      if (response.ok) {
        const data = await response.json();
        activeDownloads = data.active_downloads;
      }
    } catch (error) {
      console.error("Error fetching active downloads:", error);
    }
  }

  async function callApi(endpoint, downloadId = null, newStatus = null) {
    try {
      const response = await fetch(endpoint, { method: "POST" });
      if (response.ok && downloadId !== null && newStatus !== null) {
        const index = downloads.findIndex((d) => d.id === downloadId);
        if (index !== -1) {
          downloads[index].status = newStatus;
          downloads = [...downloads];
        }
      }
      await fetchActiveDownloads();
    } catch (error) {
      console.error(`Error calling ${endpoint}:`, error);
    }
  }

  async function deleteDownload(id) {
    openConfirm({
      message: $t("delete_confirm"),
      onConfirm: async () => {
        try {
          const response = await fetch(`/api/delete/${id}`, {
            method: "DELETE",
          });
          if (response.ok) {
            showToastMsg($t('download_deleted_success'));
            downloads = downloads.filter(download => download.id !== id);
          } else {
            const errorData = await response.json();
            showToastMsg($t('delete_failed_with_detail', {detail: errorData.detail}));
          }
        } catch (error) {
          console.error("Error deleting download:", error);
          showToastMsg($t('delete_error'));
        }
      },
      title: $t("confirm_delete_title"),
      icon: '<svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>',
      confirmText: $t("button_delete"),
      cancelText: $t("button_cancel"),
      isDeleteAction: true,
    });
  }

  function formatBytes(bytes, decimals = 2) {
    if (!bytes || bytes === 0) return "0 Bytes";
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
  }

  function getStatusTooltip(download) {
    const proxyInfo = downloadProxyInfo[download.id];
    
    if (download.status.toLowerCase() === "failed" && download.error) {
      if (proxyInfo && proxyInfo.error) {
        return $t('status_tooltip_failed_with_proxy', {error: download.error, proxy: proxyInfo.proxy, proxy_error: proxyInfo.error});
      }
      return download.error;
    }
    
    if (proxyInfo) {
      const statusIcon = {
        'trying': '⟳',
        'success': '✓', 
        'failed': '✗'
      };
      
      const icon = statusIcon[proxyInfo.status] || '●';
      let tooltip = `${icon} ${$t("proxy_tooltip_proxy")}: ${proxyInfo.proxy}\n${$t("proxy_tooltip_step")}: ${proxyInfo.step}`;
      
      if (proxyInfo.current && proxyInfo.total) {
        tooltip += `\n${$t("proxy_tooltip_progress")}: ${proxyInfo.current}/${proxyInfo.total}`;
      }
      
      if (proxyInfo.status === 'trying') {
        const timeSince = Math.floor((Date.now() - proxyInfo.timestamp) / 1000);
        tooltip += `\n${$t("proxy_tooltip_trying")} (${timeSince}${$t("proxy_tooltip_seconds")})`;
      }
      
      if (proxyInfo.error) {
        tooltip += `\n${$t("proxy_tooltip_error")}: ${proxyInfo.error}`;
      }
      
      return tooltip;
    }
    
    const statusTooltips = {
      'pending': $t("download_pending"),
      'proxying': $t("download_proxying"), 
      'downloading': $t("download_downloading"),
      'done': $t("download_done"),
      'stopped': $t("download_stopped"),
      'failed': $t("download_failed")
    };
    
    return statusTooltips[download.status.toLowerCase()] || download.status;
  }

  function formatDate(dateString) {
    if (!dateString) return "-";
    const currentLocale = localStorage.getItem('lang') || 'en';
    const date = new Date(dateString);
    const localeCode = currentLocale === 'ko' ? 'ko-KR' : 'en-US';
    
    if (currentLocale === 'ko') {
      return date.toLocaleDateString(localeCode, {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      });
    } else {
      return date.toLocaleDateString(localeCode, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
      });
    }
  }

  function formatFullDateTime(dateString) {
    return formatTimestamp(dateString) || "-";
  }

  function formatTime(dateString) {
    if (!dateString) return "-";
    const date = new Date(dateString);
    return (
      String(date.getHours()).padStart(2, "0") +
      ":" +
      String(date.getMinutes()).padStart(2, "0") +
      ":" +
      String(date.getSeconds()).padStart(2, "0")
    );
  }

  function getDownloadProgress(download) {
    if (download.progress !== undefined && download.progress !== null) {
      return Math.round(download.progress);
    }
    
    const downloaded = Number(
      download.downloaded_size ?? download.downloaded ?? 0
    );
    const total = Number(download.total_size ?? download.file_size ?? 0);
    if (total === 0 || download.status === "pending") return 0;
    if (download.status === "done") return 100;
    return Math.round((downloaded / total) * 100);
  }

  async function pasteFromClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      if (!text || text.trim() === "") {
        showToastMsg($t("clipboard_empty"));
        return;
      }
      url = text;
    } catch (err) {
      console.error("Failed to read clipboard contents: ", err);
      showToastMsg($t("clipboard_read_failed"));
    }
  }

  function openPasswordModal() {
    showPasswordModal = true;
  }

  function handlePasswordSet(event) {
    password = event.detail.password;
    hasPassword = !!password;
    showPasswordModal = false;
  }

  function openDetailModal(download) {
    selectedDownload = download;
    showDetailModal = true;
  }

  async function openFolderDialog() {
    try {
      const response = await fetch("/api/select_folder");
      if (response.ok) {
        const data = await response.json();
        if (data.path) {
          downloadPath = data.path;
          await fetch("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ download_path: downloadPath }),
          });
        }
      } else {
        console.error("Failed to open folder dialog");
      }
    } catch (error) {
      console.error("Error opening folder dialog:", error);
    }
  }

  async function copyDownloadLink(download) {
    const link = download.url;
    try {
      await navigator.clipboard.writeText(link);
      showToastMsg($t('clipboard_copy_success_with_link', {link}));
    } catch (e) {
      showToastMsg($t('clipboard_copy_failed'));
    }
  }

  async function redownload(download) {
    try {
      const response = await fetch("/api/download/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: download.url, 
          password: "",
          use_proxy: download.use_proxy || false
        }),
      });
      if (response.ok) {
        showToastMsg($t('redownload_requested'));
        fetchDownloads(currentPage);
        currentTab = "working";
      } else {
        const errorData = await response.json();
        showToastMsg($t('redownload_failed_with_detail', {detail: errorData.detail}));
      }
    } catch (error) {
      console.error("Error redownloading:", error);
      showToastMsg($t('redownload_error'));
    }
  }

  async function handleSettingsChanged(event) {
    console.log("[DEBUG] Settings changed:", event.detail);
    
    if (event.detail) {
      currentSettings = { ...event.detail };
      downloadPath = currentSettings.download_path || "";
    }
    
    const lang = localStorage.getItem("lang");
    if (lang && lang !== prevLang) {
      loadTranslations(lang);
      prevLang = lang;
    }
    
    await fetchSettings();
  }


  $: workingCount = downloads.filter(d => 
    ["pending", "downloading", "proxying", "stopped", "failed"].includes(d.status?.toLowerCase?.() || "")
  ).length;
  $: completedCount = downloads.filter(d => (d.status?.toLowerCase?.() || "") === "done").length;
  $: filteredDownloads = (() => {
    if (currentTab === "working") {
      return downloads.filter(d => 
        ["pending", "downloading", "proxying", "stopped", "failed"].includes(d.status?.toLowerCase?.() || "")
      );
    } else {
      return downloads.filter(d => (d.status?.toLowerCase?.() || "") === "done");
    }
  })();

  $: activeProxyDownloadCount = downloads.filter(d => 
    d.use_proxy && ["downloading", "proxying"].includes(d.status?.toLowerCase?.() || "")
  ).length;
</script>

<main>
  {#if $isLoading}
    <div class="loading-container">
      <p>Loading...</p>
    </div>
  {:else}
    <div class="header">
      <button
        type="button"
        class="logo-button"
        on:click={() => (window.location.href = "/")}
        aria-label={$t("main_refresh_aria")}
      >
        <img src={logo} alt="Logo" class="logo" />
      </button>
      <h1>{$t("title")}</h1>
      <div class="header-actions">
        <button
          on:click={() => (showSettingsModal = true)}
          class="button-icon settings-button"
          aria-label={$t("settings_title")}
        >
          <SettingsIcon />
        </button>
      </div>
    </div>

    <div class="card">
      <form on:submit|preventDefault={addDownload} class="download-form">
        <div class="input-group main-input-group">
          <input
            class="input url-input"
            type="text"
            bind:value={url}
            placeholder={$t("url_placeholder")}
            required
          />
          <button
            type="button"
            class="button-icon clipboard-button"
            on:click={pasteFromClipboard}
            title={$t("clipboard_tooltip")}
            aria-label={$t("clipboard_tooltip")}
          >
            <ClipboardIcon />
          </button>
          <button
            type="button"
            class="button-icon password-toggle-button"
            on:click={openPasswordModal}
            title={$t("password_tooltip")}
            aria-label={$t("password_tooltip")}
          >
            {#if hasPassword}
              <UnlockIcon />
            {:else}
              <LockIcon />
            {/if}
          </button>
        </div>
        <div class="proxy-toggle-container">
          <button
            type="button"
            class="proxy-toggle-button {useProxy ? 'proxy' : 'local'} {!proxyAvailable ? 'disabled' : ''}"
            on:click={() => proxyAvailable && (useProxy = !useProxy)}
            disabled={!proxyAvailable}
            title={!proxyAvailable ? $t('proxy_unavailable_tooltip') : useProxy ? $t('proxy_mode_tooltip') : $t('local_mode_tooltip')}
            aria-label={!proxyAvailable ? $t('proxy_unavailable_tooltip') : useProxy ? $t('proxy_mode_tooltip') : $t('local_mode_tooltip')}
          >
            <div class="proxy-toggle-slider"></div>
            <div class="proxy-toggle-icons">
            </div>
          </button>
        </div>
        <button
          type="submit"
          class="button button-primary add-download-button"
          disabled={isAddingDownload}
        >
          {#if isAddingDownload}
            <div class="spinner"></div>
            {$t("adding_download")}
          {:else}
            <DownloadIcon />
            {$t("add_download")}
          {/if}
        </button>
      </form>
    </div>

    <div class="gauge-container">
      <div class="gauge-item">
        <ProxyGauge 
          totalProxies={proxyStats.totalProxies}
          availableProxies={proxyStats.availableProxies}
          usedProxies={proxyStats.usedProxies}
          successCount={proxyStats.successCount}
          failCount={proxyStats.failCount}
          currentProxy={proxyStats.currentProxy || ""}
          currentStep={proxyStats.currentStep || ""}
          status={proxyStats.status || ""}
          currentIndex={proxyStats.currentIndex || 0}
          totalAttempting={proxyStats.totalAttempting || 0}
          lastError={proxyStats.lastError || ""}
          activeDownloadCount={activeProxyDownloadCount}
        />
      </div>

      <div class="gauge-item">
        <LocalGauge 
          localDownloadCount={localStats.localDownloadCount}
          localStatus={localStats.localStatus}
          localCurrentFile={localStats.localCurrentFile}
          localProgress={localStats.localProgress}
          localWaitTime={localStats.localWaitTime}
          activeLocalDownloads={localStats.activeLocalDownloads}
        />
      </div>
    </div>

    <div class="card">
      <div class="tabs-container">
        <div class="tabs">
          <button 
            class="tab" 
            class:active={currentTab === "working"}
            on:click={() => currentTab = "working"}
          >
            {$t("tab_working")} ({workingCount})
          </button>
          <button 
            class="tab" 
            class:active={currentTab === "completed"}
            on:click={() => currentTab = "completed"}
          >
            {$t("tab_completed")} ({completedCount})
          </button>
        </div>
      </div>
      
      <div class="table-container" class:empty-table={filteredDownloads.length === 0}>
        <table>
          <thead>
            <tr>
              <th>{$t("table_header_file_name")}</th>
              <th class="center-align">{$t("table_header_status")}</th>
              <th class="center-align">{$t("table_header_size")}</th>
              <th class="center-align">{$t("table_header_progress")}</th>
              <th class="center-align">{$t("table_header_requested_date")}</th>
              <th class="center-align">{$t("table_header_proxy")}</th>
              <th class="center-align actions-header">{$t("table_header_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {#if isDownloadsLoading}
              <tr>
                <td colspan="7">
                  <div class="table-loading-container">
                    <div class="modal-spinner"></div>
                    <div class="modal-loading-text">{$t("loading")}</div>
                  </div>
                </td>
              </tr>
            {:else if filteredDownloads.length === 0}
              <tr>
                <td colspan="7" class="no-downloads-message">
                  {currentTab === "working" ? $t("no_working_downloads") : $t("no_completed_downloads")}
                </td>
              </tr>
            {:else}
              {#each filteredDownloads as download (download.id)}
                <tr>
                  <td class="filename" title={download.url}>
                    {download.file_name || $t("file_name_na")}
                  </td>
                  <td class="center-align">
                    <span
                      class="status status-{download.status.toLowerCase()} interactive-status"
                      title={getStatusTooltip(download)}
                    >
                      {#if downloadWaitInfo[download.id] && downloadWaitInfo[download.id].remaining_time > 0 && !["stopped", "done", "failed"].includes(download.status.toLowerCase())}
                        <span class="wait-countdown">
                          {$t("download_waiting")} ({downloadWaitInfo[download.id].remaining_time}{$t("time_seconds")})
                        </span>
                      {:else}
                        {$t(`download_${download.status.toLowerCase()}`)}
                        {#if downloadProxyInfo[download.id] && (download.status.toLowerCase() === 'downloading' || download.status.toLowerCase() === 'proxying')}
                          <span class="proxy-indicator"></span>
                        {/if}
                      {/if}
                    </span>
                  </td>
                  <td class="center-align">
                    {download.total_size
                      ? formatBytes(download.total_size)
                      : "-"}
                  </td>
                  <td class="center-align">
                    <div class="progress-container">
                      <div
                        class="progress-bar"
                        style="width: {getDownloadProgress(download)}%"
                      ></div>
                      <span class="progress-text">
                        {getDownloadProgress(download)}%
                      </span>
                    </div>
                  </td>
                  <td class="center-align" title={formatFullDateTime(download.requested_at)}>
                    {formatDate(download.requested_at)}
                  </td>
                  <td class="proxy-toggle-cell">
                    <button
                      type="button"
                      class="grid-proxy-toggle {download.use_proxy ? 'proxy' : 'local'}"
                      disabled={download.status.toLowerCase() !== "stopped"}
                      title={download.use_proxy ? $t('proxy_mode') : $t('local_mode')}
                      on:click={() => {
                        downloads = downloads.map((d) =>
                          d.id === download.id
                            ? { ...d, use_proxy: !d.use_proxy }
                            : d
                        );
                      }}
                      aria-label={download.use_proxy ? $t('proxy_mode') : $t('local_mode')}
                    >
                      <div class="grid-toggle-slider"></div>
                      <div class="grid-toggle-icons">
                      </div>
                    </button>
                  </td>
                  <td class="actions-cell">
                    {#if currentTab === "completed"}
                      <button
                        class="button-icon"
                        title={$t("redownload")}
                        on:click={() => redownload(download)}
                        aria-label={$t("redownload")}
                      >
                        <RetryIcon />
                      </button>
                      <button
                        class="button-icon"
                        title={$t("copy_download_link")}
                        on:click={() => copyDownloadLink(download)}
                        aria-label={$t("copy_download_link")}
                      >
                        <LinkCopyIcon />
                      </button>
                      <button
                        class="button-icon"
                        title={$t("action_details")}
                        on:click={() => openDetailModal(download)}
                        aria-label={$t("action_details")}
                      >
                        <InfoIcon />
                      </button>
                      <button
                        class="button-icon"
                        title={$t("action_delete")}
                        on:click={() => deleteDownload(download.id)}
                        aria-label={$t("action_delete")}
                      >
                        <DeleteIcon />
                      </button>
                    {:else}
                      {#if download.status
                        .toLowerCase()
                        .includes("downloading") || download.status
                          .toLowerCase()
                          .includes("proxying")}
                        <button
                          class="button-icon"
                          title={$t("action_pause")}
                          on:click={() =>
                            callApi(
                              `/api/pause/${download.id}`,
                              download.id,
                              "stopped"
                            )}
                          aria-label={$t("action_pause")}
                        >
                          <StopIcon />
                        </button>
                      {:else if (download.status
                        .toLowerCase()
                        .includes("pending") || download.status
                          .toLowerCase()
                          .includes("stopped")) && !download.status
                          .toLowerCase()
                          .includes("proxying")}
                        <button
                          class="button-icon"
                          title={$t("action_resume")}
                          on:click={() =>
                            callApi(
                              `/api/resume/${download.id}?use_proxy=${download.use_proxy}`,
                              download.id,
                              download.use_proxy ? "proxying" : "downloading"
                            )}
                          aria-label={$t("action_resume")}
                        >
                          <ResumeIcon />
                        </button>
                      {/if}
                      {#if download.status.toLowerCase().includes("failed")}
                        <button
                          class="button-icon"
                          title={$t("action_retry")}
                          on:click={() =>
                            callApi(
                              `/api/retry/${download.id}`,
                              download.id,
                              download.use_proxy ? "proxying" : "downloading"
                            )}
                          aria-label={$t("action_retry")}
                        >
                          <RetryIcon />
                        </button>
                      {/if}
                      <button
                        class="button-icon"
                        title={$t("copy_download_link")}
                        on:click={() => copyDownloadLink(download)}
                        aria-label={$t("copy_download_link")}
                      >
                        <LinkCopyIcon />
                      </button>
                      <button
                        class="button-icon"
                        title={$t("action_details")}
                        on:click={() => openDetailModal(download)}
                        aria-label={$t("action_details")}
                      >
                        <InfoIcon />
                      </button>
                      <button
                        class="button-icon"
                        title={$t("action_delete")}
                        on:click={() => deleteDownload(download.id)}
                        aria-label={$t("action_delete")}
                      >
                        <DeleteIcon />
                      </button>
                    {/if}
                  </td>
                </tr>
              {/each}
            {/if}
          </tbody>
        </table>
      </div>

      <div class="pagination">
        <span class="page-info">
          {$t("pagination_page_info", { currentPage, totalPages })}
        </span>
        <div class="pagination-buttons">
          <button
            class="button"
            on:click={() => fetchDownloads(currentPage - 1)}
            disabled={currentPage <= 1}
          >
            {$t("pagination_previous")}
          </button>
          <button
            class="button"
            on:click={() => fetchDownloads(currentPage + 1)}
            disabled={currentPage >= totalPages}
          >
            {$t("pagination_next")}
          </button>
        </div>
      </div>
    </div>
  {/if}

  <SettingsModal
    bind:showModal={showSettingsModal}
    {currentSettings}
    on:settingsChanged={handleSettingsChanged}
    on:proxyChanged={checkProxyAvailability}
    on:close={() => (showSettingsModal = false)}
  />

  {#if showPasswordModal}
    <PasswordModal
      bind:showModal={showPasswordModal}
      on:passwordSet={handlePasswordSet}
      on:close={() => (showPasswordModal = false)}
    />
  {/if}

  {#if showDetailModal}
    <DetailModal
      bind:showModal={showDetailModal}
      download={selectedDownload}
      on:close={() => (showDetailModal = false)}
    />
  {/if}

  <ConfirmModal
    bind:showModal={showConfirm}
    message={confirmMessage}
    title={confirmTitle}
    icon={confirmIcon}
    confirmText={confirmButtonText}
    cancelText={cancelButtonText}
    on:confirm={confirmAction}
  />
</main>

<style>
  .button-icon.danger,
  .button.danger {
    color: #fff;
    background: #e53935;
    border: none;
    transition: background 0.2s;
  }
  .button-icon.danger:hover,
  .button.danger:hover {
    background: #b71c1c;
  }
  .proxy-toggle-cell {
    text-align: center;
  }
  
  .proxy-toggle-cell .grid-proxy-toggle {
    margin: 0 auto;
    display: block;
  }
  table {
    table-layout: auto;
  }
  
  table th {
    text-align: center;
  }
  
  table th:nth-child(3),
  table td:nth-child(3) {
    width: 72px;
    min-width: 72px;
  }
  
  table th:nth-child(4),
  table td:nth-child(4) {
    width: 90px;
    min-width: 90px;
  }
  
  table td {
    vertical-align: middle;
    height: 60px;
    padding: 12px 8px;
  }
  
  .actions-cell {
    text-align: center;
  }
  
  .actions-cell .button-icon {
    display: inline-block;
    margin: 0 2px;
  }

  .table-container {
    height: auto;
    min-height: 200px;
  }

  .table-container.empty-table {
    height: fit-content;
    min-height: auto;
    max-height: none;
    overflow: hidden;
  }

  .interactive-status {
    position: relative;
    cursor: help;
    transition: all 0.2s ease;
  }

  .interactive-status:hover {
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
    z-index: 10;
  }

  .proxy-indicator {
    display: inline-block;
    margin-left: 6px;
    width: 10px;
    height: 10px;
    border: 2px solid transparent;
    border-top: 2px solid currentColor;
    border-right: 2px solid currentColor;
    border-radius: 50%;
    animation: spin 1s linear infinite;
    vertical-align: middle;
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  .status-proxying.interactive-status,
  .status-downloading.interactive-status {
    animation: pulse 2s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.8; transform: scale(1.02); }
  }

  .status-proxying.interactive-status {
    border: 1px solid var(--warning-color);
  }

  .status-downloading.interactive-status {
    border: 1px solid var(--primary-color);
  }

  .status-failed.interactive-status {
    border: 1px solid var(--danger-color);
  }

  .status-done.interactive-status {
    border: 1px solid var(--success-color);
  }
  
  .wait-countdown {
    color: var(--warning-color);
    font-weight: bold;
    animation: waitPulse 1.5s ease-in-out infinite;
  }
  
  @keyframes waitPulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
  }

  .tabs-container {
    margin: -1.5rem -1.5rem 0 -1.5rem;
    padding: 1rem 1.5rem 0 1.5rem;
    background: linear-gradient(135deg, var(--card-background) 0%, rgba(var(--primary-color-rgb), 0.02) 100%);
  }

  .tabs {
    display: flex;
    gap: 0.25rem;
  }

  .tab {
    background: rgba(0, 0, 0, 0.02);
    padding: 0.75rem 1.25rem;
    cursor: pointer;
    font-weight: 500;
    font-size: 0.875rem;
    transition: all 0.3s ease;
    color: var(--text-secondary);
    border-radius: 8px 8px 0 0;
    position: relative;
    border: 1px solid rgba(0, 0, 0, 0.1);
    border-bottom: none;
  }

  .tab:hover {
    color: var(--text-primary);
    background-color: rgba(var(--primary-color-rgb), 0.05);
    border-color: var(--card-border);
    border-bottom: none;
  }

  .tab.active {
    color: var(--primary-color);
    font-weight: 600;
    background-color: var(--card-background);
    border-color: var(--card-border);
    border-bottom: 1px solid var(--card-background);
    box-shadow: 0 -1px 3px rgba(0, 0, 0, 0.03);
    z-index: 1;
  }


  .tab.active:hover {
    color: var(--primary-color);
    background-color: var(--card-background);
  }

  .proxy-toggle-container {
    display: flex;
    align-items: center;
    white-space: nowrap;
  }

  .proxy-toggle-button {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 64px;
    height: 32px;
    border: 2px solid;
    border-radius: 16px;
    cursor: pointer;
    transition: all 0.3s ease;
    outline: none;
    overflow: hidden;
    padding: 2px;
  }

  .proxy-toggle-button.local {
    background-color: #81C784;
    border-color: #66BB6A;
  }

  .proxy-toggle-button.proxy {
    background-color: #FFB74D;
    border-color: #FFA726;
  }

  .proxy-toggle-button.disabled {
    background-color: #9E9E9E !important;
    border-color: #757575 !important;
    cursor: not-allowed !important;
    opacity: 0.6;
  }

  .proxy-toggle-button.disabled .proxy-toggle-slider {
    background-color: #BDBDBD !important;
  }

  .proxy-toggle-slider {
    position: absolute;
    top: 3px;
    left: 3px;
    width: 24px;
    height: 24px;
    background-color: white;
    border-radius: 50%;
    transition: transform 0.3s ease;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
    z-index: 2;
  }

  .proxy-toggle-button.proxy .proxy-toggle-slider {
    transform: translateX(32px);
  }

  .proxy-toggle-icons {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
    height: 100%;
    padding: 0 6px;
    position: relative;
    z-index: 1;
  }

  .toggle-icon {
    font-size: 14px;
    transition: opacity 0.3s ease;
  }

  .grid-proxy-toggle {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 48px;
    height: 24px;
    border: 2px solid;
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.3s ease;
    outline: none;
    overflow: hidden;
    padding: 1px;
  }

  .grid-proxy-toggle.local {
    background-color: #81C784;
    border-color: #66BB6A;
  }

  .grid-proxy-toggle.proxy {
    background-color: #FFB74D;
    border-color: #FFA726;
  }

  .grid-proxy-toggle:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .grid-toggle-slider {
    position: absolute;
    top: 2px;
    left: 2px;
    width: 18px;
    height: 18px;
    background-color: white;
    border-radius: 50%;
    transition: transform 0.3s ease;
    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
    z-index: 2;
  }

  .grid-proxy-toggle.proxy .grid-toggle-slider {
    transform: translateX(24px);
  }

  .grid-toggle-icons {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
    height: 100%;
    padding: 0 4px;
    position: relative;
    z-index: 1;
  }

  .grid-icon {
    font-size: 10px;
    transition: opacity 0.3s ease;
  }

  .progress-container {
    position: relative;
    width: calc(100% - 10px);
    min-width: 80px;
    margin: 0 auto;
    height: 24px;
    background-color: var(--card-border);
    border-radius: 12px;
    overflow: hidden;
  }

  .progress-bar {
    height: 100%;
    background-color: var(--success-color);
    border-radius: 10px;
    transition: width 0.3s ease-out;
    min-width: 0;
  }

  .progress-text {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 12px;
    font-weight: bold;
    color: #ffffff;
    text-shadow: 
      0 0 2px rgba(0, 0, 0, 0.3),
      1px 1px 1px rgba(0, 0, 0, 0.2);
    z-index: 2;
  }

  .gauge-container {
    display: flex;
    gap: 1rem;
    margin-bottom: 1rem;
  }

  .gauge-item {
    flex: 1;
    min-height: 100px;
  }

  @media (max-width: 1024px) {
    .gauge-container {
      flex-direction: column;
      gap: 0.5rem;
    }
    
    .gauge-item {
      min-height: auto;
    }
  }
</style>