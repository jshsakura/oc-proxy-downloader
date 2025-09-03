<script>
  import logo from "./assets/images/logo256.png";
  import SettingsModal from "./lib/SettingsModal.svelte";
  import PasswordModal from "./lib/PasswordModal.svelte";
  import { onMount, onDestroy } from "svelte";
  import { theme } from "./lib/theme.js";
  import {
    t,
    isLoading,
    initializeLocale,
    loadTranslations,
    formatTimestamp,
  } from "./lib/i18n.js";
  import { needsLogin, authLoading, isAuthenticated, authRequired, authManager, authUser } from "./lib/auth.js";
  import LoginScreen from "./lib/LoginScreen.svelte";
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
  const itemsPerPage = 10;
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
    
    // 로그인이 필요하지 않거나 이미 인증된 경우에만 WebSocket 연결
    if (!$needsLogin || $isAuthenticated) {
      fetchDownloads(currentPage);
      connectWebSocket();
      fetchActiveDownloads();
      fetchProxyStatus();
      checkProxyAvailability();
    }

    const unsubscribe = t.subscribe((t_func) => {
      document.title = t_func("title");
    });
  });

  onDestroy(() => {
    // WebSocket 정리
    if (wsReconnectTimeout) {
      clearTimeout(wsReconnectTimeout);
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.close(1000, "Page unloading");
    }
  });

  function handleLoginSuccess() {
    // 로그인 성공 후 필요한 데이터 로드 및 WebSocket 연결
    fetchDownloads(currentPage);
    connectWebSocket();
    fetchActiveDownloads();
    fetchProxyStatus();
    checkProxyAvailability();
  }

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

  // WebSocket 재연결 관리 변수들
  let wsReconnectAttempts = 0;
  let wsReconnectTimeout = null;
  let wsMaxReconnectAttempts = 10;
  let wsReconnectDelay = 1000; // 시작 1초
  let wsMaxReconnectDelay = 60000; // 최대 60초

  function connectWebSocket() {
    // 기존 재연결 타이머가 있으면 취소
    if (wsReconnectTimeout) {
      clearTimeout(wsReconnectTimeout);
      wsReconnectTimeout = null;
    }

    console.log(`Attempting to connect WebSocket (attempt ${wsReconnectAttempts + 1})...`);
    const isHttps = window.location.protocol === "https:";
    const wsProtocol = isHttps ? "wss" : "ws";
    const wsUrl = `${wsProtocol}://${window.location.host}/ws/status`;
    console.log(`Protocol: ${window.location.protocol}, Using WebSocket protocol: ${wsProtocol}`);
    console.log("Connecting to WebSocket at:", wsUrl);
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("WebSocket connected!");
      // 연결 성공 시 재연결 카운터 리셋
      wsReconnectAttempts = 0;
      wsReconnectDelay = 1000;
    };

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "status_update") {
        const updatedDownload = message.data;
        console.log("Status update:", updatedDownload.id, "->", updatedDownload.status);
        const index = downloads.findIndex((d) => d.id === updatedDownload.id);
        if (index !== -1) {
          // 기존 항목 업데이트 - 상태 변화 감지를 위해 새 배열 생성
          downloads = downloads.map((d, i) =>
            i === index ? { ...d, ...updatedDownload } : d
          );
        } else {
          downloads = [updatedDownload, ...downloads];
          console.log("New download added:", updatedDownload.id);
        }
        // Svelte 반응성 강제 트리거
        downloads = [...downloads];
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
          
          // 불변성을 유지하면서 업데이트
          downloads = downloads.map((d, i) => 
            i === index 
              ? { ...d, 
                  downloaded_size: progressData.downloaded_size,
                  total_size: progressData.total_size,
                  progress: progressData.progress 
                }
              : d
          );
          
          console.log("After update:", {
            downloaded_size: downloads[index].downloaded_size,
            total_size: downloads[index].total_size,
            progress: downloads[index].progress
          });
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
        console.log("File info update:", message.data.id, message.data.file_name, message.data.file_size);
        const index = downloads.findIndex((d) => d.id === message.data.id);
        if (index !== -1) {
          // 불변성을 유지하면서 파일명과 파일 크기 업데이트
          downloads = downloads.map((d, i) => 
            i === index ? { 
              ...d, 
              file_name: message.data.file_name,
              file_size: message.data.file_size || d.file_size
            } : d
          );
          updateLocalStats(downloads);
        }
      }
    };

    ws.onclose = (event) => {
      console.log(`WebSocket disconnected (code: ${event.code}, reason: ${event.reason})`);
      
      // 최대 재시도 횟수를 초과한 경우
      if (wsReconnectAttempts >= wsMaxReconnectAttempts) {
        console.log(`WebSocket 최대 재연결 시도 횟수(${wsMaxReconnectAttempts})에 도달했습니다. 재연결을 중단합니다.`);
        return;
      }
      
      // 의도적인 종료(1000, 1001)가 아닌 경우에만 재연결 시도
      if (event.code !== 1000 && event.code !== 1001) {
        wsReconnectAttempts++;
        
        // exponential backoff with jitter
        const jitter = Math.random() * 1000; // 0-1초 랜덤 지연
        const delay = Math.min(wsReconnectDelay, wsMaxReconnectDelay) + jitter;
        
        console.log(`WebSocket 재연결 시도 ${wsReconnectAttempts}/${wsMaxReconnectAttempts} (${Math.round(delay/1000)}초 후)`);
        
        wsReconnectTimeout = setTimeout(() => {
          connectWebSocket();
        }, delay);
        
        // 다음 재시도를 위해 지연 시간 증가 (exponential backoff)
        wsReconnectDelay = Math.min(wsReconnectDelay * 2, wsMaxReconnectDelay);
      } else {
        console.log("WebSocket이 정상적으로 종료되었습니다. 재연결하지 않습니다.");
      }
    };

    ws.onerror = (error) => {
      console.log("WebSocket error occurred:", error);
    };
  }

  function reconnectWebSocket() {
    // 수동으로 WebSocket 재연결 (예: 설정 변경 후)
    if (ws) {
      ws.close(1000, "Manual reconnection");
    }
    wsReconnectAttempts = 0;
    wsReconnectDelay = 1000;
    connectWebSocket();
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

  async function callApi(endpoint, downloadId = null, expectedNewStatus = null) {
    try {
      const response = await fetch(endpoint, { method: "POST" });
      if (response.ok) {
        const responseData = await response.json();
        
        // 응답에서 대기 상태 메시지 확인
        if (responseData.status === 'waiting' && responseData.message_key) {
          showToastMsg($t(responseData.message_key, responseData.message_args));
          // 대기 상태로 UI 업데이트
          if (downloadId !== null) {
            const index = downloads.findIndex((d) => d.id === downloadId);
            if (index !== -1) {
              downloads[index].status = "pending";
              downloads = [...downloads];
            }
          }
        } else {
          // 서버 응답이 성공이면 WebSocket으로 실제 상태가 업데이트될 때까지 대기
          // 즉시 상태 변경하지 않고 실제 서버 상태를 기다림
          console.log(`API 호출 성공: ${endpoint}, WebSocket 상태 업데이트 대기 중...`);
          
          // 사용자 피드백을 위한 토스트 메시지
          if (endpoint.includes('/resume/')) {
            showToastMsg($t('resume_request_sent'), 'info');
          } else if (endpoint.includes('/pause/')) {
            showToastMsg($t('stop_request_sent'), 'info');
          } else if (endpoint.includes('/retry/')) {
            showToastMsg($t('retry_request_sent'), 'info');
          }
        }
        
        // WebSocket으로 실제 상태가 곧 업데이트될 예정이므로 추가 fetch는 필요 없음
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
    
    // 1fichier 자동 재시도 상태 체크
    if (download.status.toLowerCase() === "pending" && download.error && download.error.includes("1fichier 자동 재시도 중")) {
      return download.error + "\n3분마다 자동 재시도됩니다.";
    }
    
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

  // URL 유효성 검사 함수
  function isValidUrl(string) {
    try {
      const url = new URL(string);
      return url.protocol === 'http:' || url.protocol === 'https:';
    } catch (_) {
      return false;
    }
  }

  async function pasteFromClipboard() {
    try {
      const text = await navigator.clipboard.readText();
      if (!text || text.trim() === "") {
        showToastMsg($t("clipboard_empty"));
        return;
      }
      
      const trimmedText = text.trim();
      url = trimmedText;
      
      // URL이 유효하면 자동으로 다운로드 추가
      if (isValidUrl(trimmedText)) {
        showToastMsg($t("clipboard_url_auto_download"));
        await addDownload();
      } else {
        showToastMsg($t("clipboard_pasted"));
      }
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


  // Tab change handler to refresh data when switching tabs
  function onTabChange(newTab) {
    if (currentTab !== newTab) {
      currentTab = newTab;
      // Force data refresh when switching tabs
      fetchDownloads();
    }
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

  // 페이징 계산
  $: {
    totalPages = Math.ceil(filteredDownloads.length / itemsPerPage);
    if (currentPage > totalPages && totalPages > 0) {
      currentPage = totalPages;
    }
  }

  // 페이징된 다운로드
  $: paginatedDownloads = filteredDownloads.slice(
    (currentPage - 1) * itemsPerPage, 
    currentPage * itemsPerPage
  );

  // 페이징 함수
  function goToPage(page) {
    if (page >= 1 && page <= totalPages) {
      currentPage = page;
    }
  }

  // 탭이 변경될 때 페이지 리셋
  $: if (currentTab) {
    currentPage = 1;
  }

  $: activeProxyDownloadCount = downloads.filter(d => 
    d.use_proxy && ["downloading", "proxying"].includes(d.status?.toLowerCase?.() || "")
  ).length;
</script>

<main>
  {#if $authLoading || $isLoading}
    <div class="loading-container">
      <p>Loading...</p>
    </div>
  {:else if $needsLogin}
    <LoginScreen on:login={handleLoginSuccess} />
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
        <div class="proxy-and-download-container">
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
        </div>
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

    <div class="downloads-section">
      <div class="tabs-container">
        <div class="tabs">
          <button 
            class="tab" 
            class:active={currentTab === "working"}
            on:click={() => onTabChange("working")}
          >
            {$t("tab_working")} ({workingCount})
          </button>
          <button 
            class="tab" 
            class:active={currentTab === "completed"}
            on:click={() => onTabChange("completed")}
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
              <tr class="empty-row">
                <td colspan="7" class="no-downloads-message">
                  {currentTab === "working" ? $t("no_working_downloads") : $t("no_completed_downloads")}
                </td>
              </tr>
            {:else}
              {#each paginatedDownloads as download (download.id)}
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
                    {download.file_size || (download.total_size ? formatBytes(download.total_size) : "-")}
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
                      {#if ["downloading", "proxying", "pending"].includes(download.status?.toLowerCase())}
                        <button
                          class="button-icon"
                          title={$t("action_pause")}
                          on:click={() =>
                            callApi(
                              `/api/pause/${download.id}`,
                              download.id,
                              null
                            )}
                          aria-label={$t("action_pause")}
                        >
                          <StopIcon />
                        </button>
                      {:else if ["stopped"].includes(download.status?.toLowerCase())}
                        <button
                          class="button-icon"
                          title={$t("action_resume")}
                          on:click={() =>
                            callApi(
                              `/api/resume/${download.id}?use_proxy=${download.use_proxy}`,
                              download.id,
                              null
                            )}
                          aria-label={$t("action_resume")}
                        >
                          <ResumeIcon />
                        </button>
                      {/if}
                      {#if download.status?.toLowerCase() === "failed"}
                        <button
                          class="button-icon"
                          title={$t("action_retry")}
                          on:click={() =>
                            callApi(
                              `/api/retry/${download.id}`,
                              download.id,
                              null
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
    </div>
    
    <!-- 페이지네이션 - 항상 표시 -->
    <div class="pagination-footer">
      <div class="page-info">
        {#if totalPages > 1}
          <div>{$t("pagination_page_info", { currentPage, totalPages })}</div>
        {/if}
        <div class="items-info">
          {#if filteredDownloads.length > 0}
            {$t("pagination_items_info", { 
              total: filteredDownloads.length,
              start: (currentPage-1)*itemsPerPage + 1,
              end: Math.min(currentPage*itemsPerPage, filteredDownloads.length)
            })}
          {/if}
        </div>
      </div>
      {#if totalPages > 1}
        <div class="pagination-buttons">
          <button
            class="page-number-btn prev-next-btn"
            on:click={() => goToPage(currentPage - 1)}
            disabled={currentPage <= 1}
          >
            ‹
          </button>
          
          <!-- 페이지 번호 버튼들 -->
          {#each Array(Math.min(totalPages, 5)) as _, i}
            {@const pageNum = Math.max(1, currentPage - 2) + i}
            {#if pageNum <= totalPages}
              <button
                class="page-number-btn"
                class:active={currentPage === pageNum}
                on:click={() => goToPage(pageNum)}
              >
                {pageNum}
              </button>
            {/if}
          {/each}
          
          <button
            class="page-number-btn prev-next-btn"
            on:click={() => goToPage(currentPage + 1)}
            disabled={currentPage >= totalPages}
          >
            ›
          </button>
        </div>
      {/if}
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
    table-layout: fixed;
    width: 100%;
    min-width: 800px; /* 최소 너비 보장으로 모바일에서 스크롤 가능 */
  }
  
  table th {
    text-align: center;
  }
  
  /* 컬럼 너비 고정으로 빈 상태에서도 스크롤 보장 */
  table th:nth-child(1), table td:nth-child(1) { width: 25%; min-width: 150px; } /* 파일명 */
  table th:nth-child(2), table td:nth-child(2) { width: 10%; min-width: 80px; }  /* 상태 */
  table th:nth-child(3), table td:nth-child(3) { width: 10%; min-width: 72px; }  /* 크기 */
  table th:nth-child(4), table td:nth-child(4) { width: 15%; min-width: 90px; }  /* 진행률 */
  table th:nth-child(5), table td:nth-child(5) { width: 15%; min-width: 120px; } /* 요청일시 */
  table th:nth-child(6), table td:nth-child(6) { width: 10%; min-width: 80px; }  /* 프록시 */
  table th:nth-child(7), table td:nth-child(7) { width: 15%; min-width: 120px; } /* 액션 */
  
  table td {
    vertical-align: middle;
    height: 60px;
    padding: 12px 8px;
  }

  /* 파일명 컬럼 (첫 번째 컬럼)에 더 많은 좌측 여백 */
  table td:first-child,
  table th:first-child {
    padding-left: 2rem;
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
    height: 200px;
    min-height: 120px;
    max-height: 70vh;
    overflow: auto;
  }

  .table-container.empty-table table {
    height: 100%;
  }

  .table-container.empty-table .empty-row {
    height: 100%;
  }

  .table-container.empty-table .empty-row td {
    height: 100%;
    vertical-align: middle;
  }

  /* Downloads Section - 카드 제거 후 새로운 레이아웃 */
  .downloads-section {
    background-color: var(--background);
    padding: 0;
    margin: 0;
    border-radius: 8px;
  }

  .tabs-container {
    padding: 0 0 0.5rem 0;
    margin-bottom: 0;
  }

  .table-container {
    background-color: var(--card-background);
    border: 1px solid var(--card-border);
    border-radius: 0 8px 0 0;
    margin: 0;
    max-height: 70vh;
    overflow: auto;
  }

  /* Pagination Footer - 테이블 바로 밑에 붙이기 */
  .pagination-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 1.5rem;
    min-height: 60px;
    background-color: var(--card-background);
    border: 1px solid var(--card-border);
    border-top: none;
    border-radius: 0 0 8px 8px;
    margin: 0;
    gap: 1rem;
  }

  .pagination-buttons {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .page-number-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: 1px solid var(--card-border);
    background: var(--card-background);
    color: var(--text-primary);
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
    transition: all 0.2s ease;
  }

  .page-number-btn:hover:not(.active) {
    background: var(--bg-secondary);
    border-color: var(--primary-color);
  }

  .page-number-btn.active {
    background: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
  }

  .page-number-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    background: var(--card-border);
  }

  .prev-next-btn {
    font-size: 18px;
    font-weight: bold;
  }

  .page-info {
    color: var(--text-secondary);
    font-size: 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 4px;
    text-align: left;
  }

  .items-info {
    color: #6b7280;
    font-size: 0.85rem;
    font-weight: 400;
  }

  /* 테마별 페이지 번호 버튼 스타일 */
  :global(body.dark) .page-number-btn {
    background: #374151;
    border-color: #4b5563;
    color: #f3f4f6;
  }

  :global(body.dark) .page-number-btn:hover:not(.active) {
    background: #4b5563;
  }

  :global(body.dark) .page-number-btn:disabled {
    background: #4b5563;
  }

  :global(body.dracula) .page-number-btn {
    background: #44475a;
    border-color: #6272a4;
    color: #f8f8f2;
  }

  :global(body.dracula) .page-number-btn:hover:not(.active) {
    background: #6272a4;
  }

  :global(body.dracula) .page-number-btn:disabled {
    background: #6272a4;
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

  /* 1fichier 자동 재시도 상태 스타일 */
  .status-pending.interactive-status[title*="1fichier 자동 재시도"] {
    border: 1px solid var(--warning-color);
    background: linear-gradient(45deg, transparent 30%, var(--warning-color) 30%, var(--warning-color) 70%, transparent 70%);
    background-size: 10px 10px;
    animation: retry-pulse 3s ease-in-out infinite;
  }

  @keyframes retry-pulse {
    0%, 100% { 
      opacity: 1; 
      transform: scale(1); 
      background-position: 0 0;
    }
    50% { 
      opacity: 0.7; 
      transform: scale(1.02); 
      background-position: 5px 5px;
    }
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
    border: 1px solid var(--card-border);
    border-bottom: none;
    opacity: 0.7;
  }

  .tab:hover {
    color: var(--text-primary);
    background-color: rgba(var(--primary-color-rgb), 0.05);
    border-color: var(--card-border);
    border-bottom: none;
    opacity: 1;
  }

  .tab.active {
    color: var(--primary-color);
    font-weight: 600;
    background-color: var(--card-background);
    border-color: var(--card-border);
    border-bottom: 1px solid var(--card-background);
    box-shadow: 0 -1px 3px rgba(0, 0, 0, 0.03);
    z-index: 1;
    opacity: 1;
  }


  .tab.active:hover {
    color: var(--primary-color);
    background-color: var(--card-background);
  }

  .proxy-and-download-container {
    display: flex;
    align-items: center;
    gap: 1rem;
    width: 100%;
  }

  .proxy-toggle-container {
    display: flex;
    align-items: center;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .add-download-button {
    flex: 1;
    min-width: 0;
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
    z-index: 1;
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
    z-index: 50;
    pointer-events: none;
  }

  /* 라이트 테마에서 진행률 텍스트를 프라이머리 컬러로 변경 */
  :global(html:not(.dark):not(.dracula)) .progress-text {
    color: var(--primary-color);
    text-shadow: 
      0 0 2px rgba(255, 255, 255, 0.8),
      1px 1px 1px rgba(255, 255, 255, 0.6);
  }

  .gauge-container {
    display: flex;
    gap: 1rem;
    margin-bottom: 1.5rem;
  }

  .gauge-item {
    flex: 1;
    min-height: 100px;
  }

  /* 중간사이즈 이하에서는 위아래로 - 759px 이하 */
  @media (max-width: 759px) {
    .gauge-container {
      flex-direction: column;
      gap: 0.5rem;
    }
    
    .gauge-item {
      min-height: auto;
    }
  }

  /* Tablet/Desktop: 전체 한줄 배치 - 중간 사이즈까지 포함 */
  @media (min-width: 641px) {
    .download-form {
      flex-direction: row;
      align-items: center;
      gap: 0.75rem;
      flex-wrap: nowrap;
      width: 100%;
    }
  }

  /* 760px 이상에서는 게이지 가로로 배치 */
  @media (min-width: 760px) {
    .gauge-container {
      flex-direction: row;
      gap: 0.75rem;
    }

    .gauge-container > :global(.proxy-gauge),
    .gauge-container > :global(.local-gauge) {
      flex: 1;
      min-width: 0;
    }

    .main-input-group {
      flex: 1;
      min-width: 0;
      max-width: none;
    }

    .proxy-and-download-container {
      flex-direction: row;
      gap: 0.75rem;
      align-items: center;
      flex-shrink: 0;
      width: auto;
    }

    .proxy-toggle-container {
      flex-shrink: 0;
      width: 64px;
    }

    .add-download-button {
      flex-shrink: 0;
      width: 200px;
      min-width: 200px;
      max-width: 200px;
    }
  }

  /* Mobile: Compact Layout */
  /* Mobile only: 세로 배치 - 모바일에서만 위아래로 */
  @media (max-width: 640px) {
    .download-form {
      flex-direction: column;
      align-items: stretch;
      gap: 1rem;
      flex-wrap: wrap;
    }

    .main-input-group {
      width: 100%;
    }

    .proxy-and-download-container {
      gap: 0.75rem;
    }

    /* 모바일에서는 기본 설정 사용 (세로 배치) */

    /* ProxyGauge 모바일 최적화 */
    .gauge-container :global(.proxy-info) {
      gap: 0.25rem;
    }

    .gauge-container :global(.gauge-and-stats) {
      gap: 0.3rem;
    }

    .gauge-container :global(.proxy-stats) {
      gap: 0.25rem;
    }

    .gauge-container :global(.success-badge),
    .gauge-container :global(.fail-badge) {
      padding: 0.1rem 0.25rem;
      font-size: 0.6rem;
    }

    /* LocalGauge 모바일 최적화 */
    .gauge-container :global(.local-info) {
      align-items: center;
      gap: 0.5rem;
    }

    .gauge-container :global(.local-count) {
      font-size: 0.75rem;
    }
  }

  /* Authentication styles */
  .user-info {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    color: var(--text-secondary);
    font-size: 0.8rem;
    font-weight: 500;
    margin-right: 1rem;
    line-height: 1.2;
  }

  .user-greeting {
    color: var(--text-primary);
    font-size: 0.85rem;
  }

  .user-id {
    color: var(--text-secondary);
    font-size: 0.75rem;
    margin-top: 1px;
  }

  .logout-button {
    background: var(--button-secondary-background);
    color: var(--button-secondary-text);
    border: 1px solid var(--button-secondary-border);
    padding: 0.5rem 1rem;
    border-radius: 8px;
    font-size: 0.875rem;
    font-weight: 500;
    transition: all 0.2s ease;
    margin-right: 0.5rem;
  }

  .logout-button:hover:not(:disabled) {
    background: var(--button-secondary-background-hover);
    transform: translateY(-1px);
    box-shadow: var(--shadow-light);
  }
</style>