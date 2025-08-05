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

  console.log(
    "%c ██████  ██████   ██████ ██████  ███████    ████    ██   ██████  ██████ ██     █████    ███     ██████  █████ ██████ █████████████  \n" +
      "██    ███         ██   ████   ████    ████ ██  ██  ██    ██   ████    ████     ██████   ███    ██    ████   ████   ████     ██   ██ \n" +
      "██    ████        ██████ ██████ ██    ██ ███    ████     ██   ████    ████  █  ████ ██  ███    ██    ███████████   ███████  ██████  \n" +
      "██    ███         ██     ██   ████    ████ ██    ██      ██   ████    ████ ███ ████  ██ ███    ██    ████   ████   ████     ██   ██ \n" +
      " ██████  ██████   ██     ██   ██ ███████    ██   ██      ██████  ██████  ███ ███ ██   ██████████████████     ███████ █████████   ██ \n" +
      "                                                                                                                                       \n" +
      "                                                                                                                                       ",
    "color: #474BDF; font-weight: bold; font-size: 12px;"
  );
  console.log(
    "%cBy Husband of Rebekah",
    "color: #bd93f9; font-weight: bold; font-size: 12px;"
  );

  let downloads = []; // 다운로드 목록
  let url = "";
  let password = "";
  let ws;
  let currentPage = 1;
  let totalPages = 1;
  let isDownloadsLoading = false;
  let isAddingDownload = false; // 다운로드 추가 중 로딩 상태
  let activeDownloads = []; // 활성 다운로드 목록

  let showSettingsModal = false;
  let showPasswordModal = false;
  let showDetailModal = false;
  let currentSettings = {};
  let hasPassword = false; // To track if a password has been set
  let selectedDownload = {};
  let downloadPath = ""; // Declare downloadPath here
  let prevLang = null;
  let useProxy = true;

  // 프록시 상태 변수들
  let proxyStats = {
    totalProxies: 0,
    availableProxies: 0,
    usedProxies: 0,
    successCount: 0,
    failCount: 0
  };

  // 다운로드별 프록시 상태 추적
  let downloadProxyInfo = {}; // {downloadId: {proxy, step, current, total, error}}

  let showConfirm = false;
  let confirmMessage = "";
  let confirmAction = null;
  let confirmTitle = null;
  let confirmIcon = null;
  let confirmButtonText = null;
  let cancelButtonText = null;

  let isDark =
    typeof document !== "undefined" && document.body.classList.contains("dark");

  // 탭 관련 변수
  let currentTab = "working"; // "working", "completed"

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
    // 최초 진입 시 settings.language가 있으면 localStorage.lang을 덮어씀
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
    fetchActiveDownloads(); // 웹소켓 연결 후 활성 다운로드 목록 가져오기
    fetchProxyStatus(); // 프록시 상태 초기화

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
      console.error('프록시 상태 가져오기 실패:', error);
    }
  }

  function connectWebSocket() {
    console.log("Attempting to connect WebSocket...");
    const wsProtocol = window.location.protocol === "https" ? "wss" : "ws";
    const wsUrl = `${wsProtocol}://${window.location.host}/ws/status`;
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
          // Replace the item and create a new array reference to ensure reactivity
          downloads = downloads.map((d, i) =>
            i === index ? updatedDownload : d
          );
        } else {
          // If the download is new, add it to the beginning of the list
          downloads = [updatedDownload, ...downloads];
        }
        // 다운로드 상태가 변경될 때마다 프록시 상태도 업데이트
        fetchProxyStatus();

        // 실패 상태인 경우 토스트 메시지 표시
        if (updatedDownload.status === "failed" && updatedDownload.error) {
          showToastMsg(`다운로드 실패: ${updatedDownload.error}`);
        }
      } else if (message.type === "proxy_update") {
        // 프록시 상태 변경 알림
        console.log("Proxy status update:", message.data);
        fetchProxyStatus(); // 프록시 상태 다시 가져오기
      } else if (message.type === "proxy_reset") {
        // 프록시 리셋 알림
        console.log("Proxy reset:", message.data);
        fetchProxyStatus(); // 프록시 상태 다시 가져오기
        showToastMsg("프록시가 리셋되었습니다", "success");

        // 상태 업데이트 후 활성 다운로드 목록 갱신
        fetchActiveDownloads();
      } else if (message.type === "proxy_trying") {
        // 프록시 시도 중 상태
        console.log("Proxy trying:", message.data);
        
        // 전역 프록시 상태 업데이트
        proxyStats.currentProxy = message.data.proxy;
        proxyStats.currentStep = message.data.step;
        proxyStats.currentIndex = message.data.current;
        proxyStats.totalAttempting = message.data.total;
        proxyStats.status = "trying";
        proxyStats = { ...proxyStats }; // 반응성 트리거
        
        // URL별 프록시 정보 저장 (다운로드 ID 찾기)
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
        // 프록시 성공 상태
        console.log("Proxy success:", message.data);
        
        // 전역 프록시 상태 업데이트
        proxyStats.currentProxy = message.data.proxy;
        proxyStats.currentStep = message.data.step;
        proxyStats.status = "success";
        proxyStats = { ...proxyStats }; // 반응성 트리거
        fetchProxyStatus(); // 최신 통계 갱신
        
        // URL별 프록시 정보 업데이트
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
        // 프록시 실패 상태
        console.log("Proxy failed:", message.data);
        
        // 전역 프록시 상태 업데이트
        proxyStats.currentProxy = message.data.proxy;
        proxyStats.currentStep = message.data.step;
        proxyStats.status = "failed";
        proxyStats.lastError = message.data.error;
        proxyStats = { ...proxyStats }; // 반응성 트리거
        fetchProxyStatus(); // 최신 통계 갱신
        
        // URL별 프록시 정보 업데이트
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
        downloads = data; // 백엔드에서 배열을 직접 반환하므로 data.items가 아님
        currentPage = 1;
        totalPages = 1;
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
        url = "";
        password = ""; // Clear password after successful download
        hasPassword = false; // Reset password status
        showToastMsg($t("download_added_successfully"));
        fetchDownloads(currentPage); // 다운로드 추가 후 목록 갱신
      } else {
        const errorData = await response.json();
        showToastMsg(`다운로드 추가 실패: ${errorData.detail}`);
      }
    } catch (error) {
      console.error("Error adding download:", error);
      showToastMsg("다운로드 추가 중 오류가 발생했습니다.");
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
        // Optimistic UI update
        const index = downloads.findIndex((d) => d.id === downloadId);
        if (index !== -1) {
          downloads[index].status = newStatus;
          downloads = [...downloads]; // Trigger Svelte reactivity
        }
      }
      // API 호출 후 활성 다운로드 목록 갱신
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
            showToastMsg("다운로드가 삭제되었습니다.");
            fetchDownloads(currentPage);
          } else {
            const errorData = await response.json();
            showToastMsg(`삭제 실패: ${errorData.detail}`);
          }
        } catch (error) {
          console.error("Error deleting download:", error);
          showToastMsg("삭제 중 오류가 발생했습니다.");
        }
      },
      title: $t("confirm_delete_title"),
      icon: '<svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>',
      confirmText: $t("button_delete"),
      cancelText: $t("button_cancel"),
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
        return `실패: ${download.error}\n마지막 시도 프록시: ${proxyInfo.proxy}\n오류: ${proxyInfo.error}`;
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
      let tooltip = `${icon} 프록시: ${proxyInfo.proxy}\n단계: ${proxyInfo.step}`;
      
      if (proxyInfo.current && proxyInfo.total) {
        tooltip += `\n진행: ${proxyInfo.current}/${proxyInfo.total}`;
      }
      
      if (proxyInfo.status === 'trying') {
        const timeSince = Math.floor((Date.now() - proxyInfo.timestamp) / 1000);
        tooltip += `\n시도 중... (${timeSince}초)`;
      }
      
      if (proxyInfo.error) {
        tooltip += `\n오류: ${proxyInfo.error}`;
      }
      
      return tooltip;
    }
    
    // 기본 상태별 툴팁
    const statusTooltips = {
      'pending': '대기 중...',
      'proxying': '프록시 연결 중...',
      'downloading': '다운로드 중...',
      'done': '완료',
      'stopped': '정지',
      'failed': '실패'
    };
    
    return statusTooltips[download.status.toLowerCase()] || download.status;
  }

  function formatDate(dateString) {
    if (!dateString) return "-";
    const date = new Date(dateString);
    return (
      date.getFullYear() +
      "-" +
      String(date.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(date.getDate()).padStart(2, "0")
    );
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
    const downloaded = Number(
      download.downloaded_size ?? download.downloaded ?? 0
    );
    const total = Number(download.file_size ?? download.total_size ?? 0);
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
    hasPassword = !!password; // Set to true if password is not empty
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
          // Optionally, save the new download path to backend immediately
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
    const link = download.direct_link || download.url;
    try {
      await navigator.clipboard.writeText(link);
      showToastMsg(`클립보드에 [${link}] 이 복사되었습니다.`);
    } catch (e) {
      showToastMsg("클립보드 복사 실패");
    }
  }

  async function redownload(download) {
    // 완료된 다운로드를 다시 다운로드 요청
    try {
      const response = await fetch("/api/download/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          url: download.url, 
          password: "", // 기존 패스워드는 저장되지 않으므로 빈 값
          use_proxy: download.use_proxy || true
        }),
      });
      if (response.ok) {
        showToastMsg("재다운로드가 요청되었습니다.");
        fetchDownloads(currentPage);
        // 재다운로드 후 진행중 탭으로 이동
        currentTab = "working";
      } else {
        const errorData = await response.json();
        showToastMsg(`재다운로드 실패: ${errorData.detail}`);
      }
    } catch (error) {
      console.error("Error redownloading:", error);
      showToastMsg("재다운로드 중 오류가 발생했습니다.");
    }
  }

  function handleSettingsChanged() {
    // 이후엔 오직 localStorage.lang만 기준
    const lang = localStorage.getItem("lang");
    if (lang && lang !== prevLang) {
      loadTranslations(lang);
      prevLang = lang;
    }
  }


  // 탭별 개수 계산
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

  // 활성 다운로드 개수 계산 (ProxyGauge용)
  $: activeDownloadCount = downloads.filter(d => 
    ["downloading", "proxying"].includes(d.status?.toLowerCase?.() || "")
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
        aria-label="메인으로 새로고침"
      >
        <img src={logo} alt="Logo" class="logo" />
      </button>
      <h1>{$t("title")}</h1>
      <div class="header-actions">
        <button
          on:click={() => (showSettingsModal = true)}
          class="button-icon settings-button"
          aria-label="Settings"
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

    <!-- 프록시 게이지 -->
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
      activeDownloadCount={activeDownloadCount}
    />

    <!-- 탭 네비게이션 -->
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

    <div class="card">
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>{$t("table_header_file_name")}</th>
              <th>{$t("table_header_status")}</th>
              <th>{$t("table_header_size")}</th>
              <th>{$t("table_header_progress")}</th>
              <th class="center-align">{$t("table_header_requested_date")}</th>
              <th class="center-align">{$t("table_header_requested_time")}</th>
              <th>{$t("use_proxy_label")}</th>
              <th class="actions-header">{$t("table_header_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {#if isDownloadsLoading}
              <tr>
                <td colspan="8">
                  <div class="table-loading-container">
                    <div class="modal-spinner"></div>
                    <div class="modal-loading-text">{$t("loading")}</div>
                  </div>
                </td>
              </tr>
            {:else if filteredDownloads.length === 0}
              <tr>
                <td colspan="8" class="no-downloads-message">
                  {currentTab === "working" ? $t("no_working_downloads") : $t("no_completed_downloads")}
                </td>
              </tr>
            {:else}
              {#each filteredDownloads as download (download.id)}
                <tr>
                  <td class="filename" title={download.url}>
                    {download.file_name || $t("file_name_na")}
                  </td>
                  <td>
                    <span
                      class="status status-{download.status.toLowerCase()} interactive-status"
                      title={getStatusTooltip(download)}
                    >
                      {$t(`download_${download.status.toLowerCase()}`)}
                      {#if downloadProxyInfo[download.id] && (download.status.toLowerCase() === 'downloading' || download.status.toLowerCase() === 'proxying')}
                        <span class="proxy-indicator"></span>
                      {/if}
                    </span>
                  </td>
                  <td>
                    {download.total_size
                      ? formatBytes(download.total_size)
                      : "-"}
                  </td>
                  <td>
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
                  <td class="center-align">
                    {formatDate(download.requested_at)}
                  </td>
                  <td class="center-align">
                    {formatTime(download.requested_at)}
                  </td>
                  <td class="proxy-toggle-cell">
                    <label class="custom-checkbox-label">
                      <input
                        type="checkbox"
                        class="custom-checkbox"
                        bind:checked={download.use_proxy}
                        disabled={download.status.toLowerCase() !== "stopped"}
                        on:change={() => {
                          // 상태 변경 시 배열 갱신
                          downloads = downloads.map((d) =>
                            d.id === download.id
                              ? { ...d, use_proxy: download.use_proxy }
                              : d
                          );
                        }}
                      />
                      <span class="custom-checkbox-icon">
                        {#if download.use_proxy}
                          {#if isDark}
                            <svg
                              width="18"
                              height="18"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="#81c784"
                              stroke-width="3"
                              stroke-linecap="round"
                              stroke-linejoin="round"
                            >
                              <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                          {:else}
                            <svg
                              width="18"
                              height="18"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="#388e3c"
                              stroke-width="3"
                              stroke-linecap="round"
                              stroke-linejoin="round"
                            >
                              <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                          {/if}
                        {:else}
                          <svg
                            width="18"
                            height="18"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="none"
                            stroke-width="0"
                          >
                            <rect
                              x="4"
                              y="4"
                              width="16"
                              height="16"
                              rx="4"
                              fill="none"
                              stroke="none"
                            />
                          </svg>
                        {/if}
                      </span>
                    </label>
                  </td>
                  <td class="actions">
                    {#if currentTab === "completed"}
                      <!-- 완료 탭에서는 재다운로드 버튼만 표시 -->
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
                        title="다운로드 링크 복사"
                        on:click={() => copyDownloadLink(download)}
                        aria-label="다운로드 링크 복사"
                      >
                        <LinkCopyIcon />
                      </button>
                      <button
                        class="button-icon"
                        title={$t("action_details")}
                        on:click={() => openDetailModal(download)}
                      >
                        <InfoIcon />
                      </button>
                      <button
                        class="button-icon"
                        title={$t("action_delete")}
                        on:click={() => deleteDownload(download.id)}
                      >
                        <DeleteIcon />
                      </button>
                    {:else}
                      <!-- 현재작업/전체 탭에서는 기존 버튼들 표시 -->
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
                        >
                          <RetryIcon />
                        </button>
                      {/if}
                      <button
                        class="button-icon"
                        title="다운로드 링크 복사"
                        on:click={() => copyDownloadLink(download)}
                        aria-label="다운로드 링크 복사"
                      >
                        <LinkCopyIcon />
                      </button>
                      <button
                        class="button-icon"
                        title={$t("action_details")}
                        on:click={() => openDetailModal(download)}
                      >
                        <InfoIcon />
                      </button>
                      <button
                        class="button-icon"
                        title={$t("action_delete")}
                        on:click={() => deleteDownload(download.id)}
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
  .custom-checkbox-label {
    display: flex;
    align-items: center;
    cursor: pointer;
    user-select: none;
    justify-content: center;
  }
  .custom-checkbox {
    display: none;
  }
  .custom-checkbox-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 6px;
    background: var(--card-background, #f5f5f5);
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
    border: 2px solid #bdbdbd;
    transition:
      background 0.2s,
      border 0.2s,
      box-shadow 0.2s;
    vertical-align: middle;
    position: relative;
    top: 2px;
  }
  .custom-checkbox-label:hover .custom-checkbox-icon {
    box-shadow: 0 0 0 2px #90caf9;
    border-color: #42a5f5;
  }
  :global(body.dark) .custom-checkbox-icon {
    background: #23272f;
    border-color: #555;
  }
  .custom-checkbox:checked + .custom-checkbox-icon {
    background: #81c784;
    border-color: #388e3c;
  }
  :global(body.dark) .custom-checkbox:checked + .custom-checkbox-icon {
    background: #388e3c;
    border-color: #81c784;
  }
  .custom-checkbox:disabled + .custom-checkbox-icon {
    opacity: 0.4;
    cursor: not-allowed;
    background: #e0e0e0;
    border-color: #bdbdbd;
  }
  :global(body.dark) .custom-checkbox:disabled + .custom-checkbox-icon {
    background: #333;
    border-color: #444;
  }
  table th {
    text-align: center;
  }

  /* 인터랙티브 상태 라벨 스타일 */
  .interactive-status {
    position: relative;
    cursor: help;
    transition: all 0.2s ease;
  }

  .interactive-status:hover {
    transform: scale(1.05);
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

  /* 상태별 특별한 스타일 */
  .status-proxying.interactive-status,
  .status-downloading.interactive-status {
    animation: pulse 2s ease-in-out infinite;
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.8; transform: scale(1.02); }
  }

  /* 상태별 테두리 색상 */
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

  /* 탭 스타일 */
  .tabs-container {
    margin-bottom: 1.5rem;
  }

  .tabs {
    display: flex;
    background-color: var(--card-background);
    border: 1px solid var(--card-border);
    border-radius: 10px;
    padding: 4px;
    box-shadow: var(--shadow-light);
  }

  .tab {
    flex: 1;
    background: none;
    border: none;
    padding: 0.75rem 1rem;
    border-radius: 8px;
    cursor: pointer;
    font-weight: 500;
    font-size: 0.9rem;
    transition: all 0.2s ease;
    color: var(--text-secondary);
  }

  .tab:hover {
    background-color: var(--button-secondary-background-hover);
    color: var(--text-primary);
  }

  .tab.active {
    background-color: var(--primary-color);
    color: white;
    font-weight: 600;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  }

  .tab.active:hover {
    background-color: var(--primary-color);
  }
</style>
