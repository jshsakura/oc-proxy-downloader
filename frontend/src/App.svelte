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
  import {
    needsLogin,
    authLoading,
    isAuthenticated,
    authRequired,
    authManager,
    authUser,
  } from "./lib/auth.js";
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
  import NetworkIcon from "./icons/NetworkIcon.svelte";
  import InfoIcon from "./icons/InfoIcon.svelte";
  import LinkCopyIcon from "./icons/LinkCopyIcon.svelte";
  import DownloadIcon from "./icons/DownloadIcon.svelte";
  import SettingsIcon from "./icons/SettingsIcon.svelte";
  import { toastMessage, showToast, showToastMsg } from "./lib/toast.js";
  import ConfirmModal from "./lib/ConfirmModal.svelte";
  import ProxyGauge from "./lib/ProxyGauge.svelte";
  import LocalGauge from "./lib/LocalGauge.svelte";

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
    failCount: 0,
    currentProxy: "",
    currentStep: "",
    currentIndex: 0,
    totalAttempting: 0,
    status: "",
    lastError: "",
    activeDownloadCount: 0,
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

    // 프록시 새로고침 이벤트 리스너 추가
    const handleProxyRefresh = () => {
      fetchProxyStatus();
      checkProxyAvailability();
    };
    document.addEventListener("proxy-refreshed", handleProxyRefresh);

    // 모바일에서 앱 포그라운드 복귀 시 조용한 동기화
    let lastVisibilityTime = Date.now();
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        const now = Date.now();
        const timeSinceLastVisible = now - lastVisibilityTime;

        // 5초 이상 백그라운드에 있었다면 동기화
        if (timeSinceLastVisible > 5000) {
          console.log("[SYNC] 앱 포그라운드 복귀, 백그라운드 동기화 실행");
          syncDownloadsSilently();

          // WebSocket도 재연결 (연결이 끊어졌을 수 있음)
          if (!ws || ws.readyState !== WebSocket.OPEN) {
            console.log("[SYNC] WebSocket 재연결");
            reconnectWebSocket();
          }
        }
      } else {
        lastVisibilityTime = Date.now();
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    const unsubscribe = t.subscribe((t_func) => {
      document.title = t_func("title");
    });

    // 테이블 컬럼 리사이징 기능 추가
    const cleanupResize = initTableColumnResize();

    // cleanup 함수를 onDestroy에 등록
    return () => {
      cleanupResize && cleanupResize();
      document.removeEventListener("proxy-refreshed", handleProxyRefresh);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  });

  function initTableColumnResize() {
    let isResizing = false;
    let currentColumn = null;
    let startX = 0;
    let startWidth = 0;

    // 마우스 다운 이벤트 (리사이징 시작)
    function handleMouseDown(e) {
      // 테이블 헤더의 :after 가상 요소 영역인지 확인
      const th = e.target.closest("th");
      if (!th || !th.closest("table")) return;

      const rect = th.getBoundingClientRect();
      const isInResizeArea =
        e.clientX > rect.right - 10 && e.clientX <= rect.right;

      if (isInResizeArea && th.nextElementSibling) {
        isResizing = true;
        currentColumn = th;
        startX = e.clientX;
        startWidth = th.offsetWidth;
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        e.preventDefault();
        e.stopPropagation();
      }
    }

    // 마우스 이동 이벤트 (리사이징 중)
    function handleMouseMove(e) {
      if (!isResizing || !currentColumn) {
        // 리사이징 중이 아닐 때 커서 변경
        const th = e.target.closest("th");
        if (th && th.closest("table")) {
          const rect = th.getBoundingClientRect();
          const isInResizeArea =
            e.clientX > rect.right - 10 && e.clientX <= rect.right;
          document.body.style.cursor =
            isInResizeArea && th.nextElementSibling ? "col-resize" : "";
        }
        return;
      }

      const diff = e.clientX - startX;
      const newWidth = Math.max(50, startWidth + diff);

      // 헤더 너비 설정
      currentColumn.style.width = newWidth + "px";
      currentColumn.style.minWidth = newWidth + "px";
      currentColumn.style.maxWidth = newWidth + "px";

      // 같은 컬럼의 모든 td에도 동일한 너비 적용
      const columnIndex = Array.from(
        currentColumn.parentElement.children
      ).indexOf(currentColumn);
      const table = currentColumn.closest("table");
      const rows = table.querySelectorAll("tbody tr");
      rows.forEach((row) => {
        const td = row.children[columnIndex];
        if (td) {
          td.style.width = newWidth + "px";
          td.style.minWidth = newWidth + "px";
          td.style.maxWidth = newWidth + "px";
        }
      });

      e.preventDefault();
    }

    // 마우스 업 이벤트 (리사이징 종료)
    function handleMouseUp() {
      if (isResizing) {
        isResizing = false;
        currentColumn = null;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    }

    // 이벤트 리스너 등록
    document.addEventListener("mousedown", handleMouseDown);
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    // cleanup 함수 반환 (컴포넌트 해제 시 사용)
    return () => {
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }

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
      const response = await fetch("/api/proxy-status");
      if (response.ok) {
        const data = await response.json();
        proxyStats = {
          ...proxyStats,
          totalProxies: data.total_proxies,
          availableProxies: data.available_proxies,
          usedProxies: data.used_proxies,
          successCount: data.success_count,
          failCount: data.fail_count,
        };
      }
    } catch (error) {
      console.error($t("proxy_status_fetch_failed"), error);
    }
  }

  async function checkProxyAvailability() {
    try {
      const response = await fetch("/api/proxies/available");
      if (response.ok) {
        const data = await response.json();
        proxyAvailable = data.available;
        if (!proxyAvailable && useProxy) {
          useProxy = false;
        }
      }
    } catch (error) {
      console.error($t("proxy_availability_check_failed"), error);
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

    console.log(
      `Attempting to connect WebSocket (attempt ${wsReconnectAttempts + 1})...`
    );
    const isHttps = window.location.protocol === "https:";
    const wsProtocol = isHttps ? "wss" : "ws";
    const wsUrl = `${wsProtocol}://${window.location.host}/ws/status`;
    console.log(
      `Protocol: ${window.location.protocol}, Using WebSocket protocol: ${wsProtocol}`
    );
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

      // Ping 메시지 처리 (연결 유지용)
      if (message.type === "ping") {
        return;
      }

      if (message.type === "status_update") {
        const updatedDownload = message.data;
        console.log(
          "Status update:",
          updatedDownload.id,
          "->",
          updatedDownload.status
        );
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
          showToastMsg(
            $t("download_failed_with_error", { error: updatedDownload.error })
          );
        }

        if (updatedDownload.status === "done") {
          showToastMsg(
            $t("download_complete_with_filename", {
              filename: updatedDownload.file_name || $t("file"),
            })
          );
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
          }
        }
      } else if (message.type === "proxy_update") {
        fetchProxyStatus();
      } else if (message.type === "proxy_reset") {
        fetchProxyStatus();
        showToastMsg($t("proxy_reset_success"), "success");

        fetchActiveDownloads();
      } else if (message.type === "progress_update") {
        const progressData = message.data;

        const index = downloads.findIndex((d) => d.id === progressData.id);

        if (index !== -1) {
          // 불변성을 유지하면서 업데이트
          downloads = downloads.map((d, i) =>
            i === index
              ? {
                  ...d,
                  downloaded_size: progressData.downloaded_size,
                  total_size: progressData.total_size,
                  progress: progressData.progress,
                  download_speed:
                    progressData.download_speed ?? d.download_speed,
                  use_proxy: progressData.use_proxy ?? d.use_proxy,
                }
              : d
          );
        } else {
        }
      } else if (message.type === "proxy_trying") {
        proxyStats.currentProxy = message.data.proxy;
        proxyStats.currentStep = message.data.step;
        proxyStats.currentIndex = message.data.current;
        proxyStats.totalAttempting = message.data.total;
        proxyStats.status = "trying";
        proxyStats = { ...proxyStats };

        const matchingDownload = downloads.find(
          (d) => d.url === message.data.url
        );
        if (matchingDownload) {
          downloadProxyInfo[matchingDownload.id] = {
            proxy: message.data.proxy,
            step: message.data.step,
            current: message.data.current,
            total: message.data.total,
            status: "trying",
            timestamp: Date.now(),
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

        const matchingDownload = downloads.find(
          (d) => d.url === message.data.url
        );
        if (matchingDownload) {
          downloadProxyInfo[matchingDownload.id] = {
            ...downloadProxyInfo[matchingDownload.id],
            proxy: message.data.proxy,
            step: message.data.step,
            status: "success",
            timestamp: Date.now(),
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

        const matchingDownload = downloads.find(
          (d) => d.url === message.data.url
        );
        if (matchingDownload) {
          downloadProxyInfo[matchingDownload.id] = {
            ...downloadProxyInfo[matchingDownload.id],
            proxy: message.data.proxy,
            step: message.data.step,
            status: "failed",
            error: message.data.error,
            timestamp: Date.now(),
          };
          downloadProxyInfo = { ...downloadProxyInfo };
        }
      } else if (message.type === "wait_countdown") {
        const matchingDownload = downloads.find(
          (d) => d.url === message.data.url
        );
        if (matchingDownload) {
          downloadWaitInfo[matchingDownload.id] = {
            remaining_time: message.data.remaining_time,
            total_wait_time: message.data.total_wait_time,
            proxy_addr: message.data.proxy_addr,
            timestamp: Date.now(),
          };
          downloadWaitInfo = { ...downloadWaitInfo };

          if (message.data.remaining_time <= 0) {
            setTimeout(() => {
              delete downloadWaitInfo[matchingDownload.id];
              downloadWaitInfo = { ...downloadWaitInfo };
            }, 1000);
          }
        }
      } else if (message.type === "wait_countdown_complete") {
        console.log("Wait countdown complete:", message.data);

        // 해당 다운로드의 대기 정보 즉시 정리
        if (downloadWaitInfo[message.data.id]) {
          delete downloadWaitInfo[message.data.id];
          downloadWaitInfo = { ...downloadWaitInfo };
          console.log("Wait info cleared for download:", message.data.id);
        }
      } else if (message.type === "filename_update") {
        console.log(
          "File info update:",
          message.data.id,
          message.data.file_name,
          message.data.file_size
        );
        const index = downloads.findIndex((d) => d.id === message.data.id);
        if (index !== -1) {
          // 불변성을 유지하면서 파일명과 파일 크기 업데이트
          downloads = downloads.map((d, i) =>
            i === index
              ? {
                  ...d,
                  file_name: message.data.file_name,
                  file_size: message.data.file_size || d.file_size,
                }
              : d
          );
          updateLocalStats(downloads);
        }
      }
    };

    ws.onclose = (event) => {
      console.log(
        `WebSocket disconnected (code: ${event.code}, reason: ${event.reason})`
      );

      // 최대 재시도 횟수를 초과한 경우
      if (wsReconnectAttempts >= wsMaxReconnectAttempts) {
        console.log(
          `WebSocket 최대 재연결 시도 횟수(${wsMaxReconnectAttempts})에 도달했습니다. 재연결을 중단합니다.`
        );
        return;
      }

      // 의도적인 종료(1000, 1001)가 아닌 경우에만 재연결 시도
      if (event.code !== 1000 && event.code !== 1001) {
        wsReconnectAttempts++;

        // exponential backoff with jitter
        const jitter = Math.random() * 1000; // 0-1초 랜덤 지연
        const delay = Math.min(wsReconnectDelay, wsMaxReconnectDelay) + jitter;

        console.log(
          `WebSocket 재연결 시도 ${wsReconnectAttempts}/${wsMaxReconnectAttempts} (${Math.round(delay / 1000)}초 후)`
        );

        wsReconnectTimeout = setTimeout(() => {
          connectWebSocket();
        }, delay);

        // 다음 재시도를 위해 지연 시간 증가 (exponential backoff)
        wsReconnectDelay = Math.min(wsReconnectDelay * 2, wsMaxReconnectDelay);
      } else {
        console.log(
          "WebSocket이 정상적으로 종료되었습니다. 재연결하지 않습니다."
        );
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

  // 조용한 백그라운드 동기화 (깜빡거림 없음)
  async function syncDownloadsSilently() {
    try {
      const response = await fetch(`/api/history/`);
      if (response.ok) {
        const newData = await response.json();

        // 기존 데이터와 비교해서 실제 변경사항만 업데이트
        const hasChanges =
          JSON.stringify(downloads) !== JSON.stringify(newData);
        if (hasChanges) {
          console.log(
            "[SYNC] 백그라운드에서 데이터 변경 감지, 조용히 업데이트"
          );
          downloads = newData;
          // 로딩 상태 변경 없이 부드럽게 업데이트
        }
      }
    } catch (error) {
      console.log("[SYNC] 백그라운드 동기화 실패:", error);
    }
  }

  async function fetchDownloads(page = 1, retryCount = 0) {
    console.log("=== fetchDownloads called ===");
    isDownloadsLoading = true;
    console.log("isDownloadsLoading set to:", isDownloadsLoading);

    try {
      const response = await fetch(`/api/history/`, { timeout: 10000 });
      console.log("History API response status:", response.status);

      if (response.ok) {
        const data = await response.json();
        console.log("History API response:", data);
        if (Array.isArray(data) && data.length > 0) {
          console.log("First download status:", data[0].status);
          console.log(
            "All download statuses:",
            data.map((d) => d.status)
          );
        }
        downloads = data;
        currentPage = 1;
        totalPages = 1;

        updateLocalStats(data);
      } else {
        console.error("History API failed with status:", response.status);
        const errorText = await response.text();
        console.error("Error response:", errorText);

        // 재시도 로직
        if (
          retryCount < 2 &&
          (response.status >= 500 || response.status === 0)
        ) {
          console.log(`재시도 중... (${retryCount + 1}/3)`);
          setTimeout(() => fetchDownloads(page, retryCount + 1), 2000);
          return;
        }
        downloads = [];
      }
    } catch (error) {
      console.error("Error fetching downloads:", error);

      // 네트워크 오류 시 재시도
      if (retryCount < 2) {
        console.log(`네트워크 오류 재시도 중... (${retryCount + 1}/3)`);
        setTimeout(() => fetchDownloads(page, retryCount + 1), 2000);
        return;
      }
      downloads = [];
    } finally {
      if (retryCount === 0 || retryCount >= 2) {
        isDownloadsLoading = false;
        console.log("isDownloadsLoading set to:", isDownloadsLoading);
        console.log("Final downloads state:", downloads);
        console.log("=== fetchDownloads completed ===");
      }
    }
  }

  function updateLocalStats(downloadsData) {
    if (!downloadsData) return;

    const localDownloads = downloadsData.filter((d) => !d.use_proxy);

    const activeLocalDownloads = localDownloads;

    const currentDownloading = activeLocalDownloads.find(
      (d) => d.status?.toLowerCase() === "downloading"
    );

    localStats.localDownloadCount = activeLocalDownloads.length;
    localStats.localCurrentFile =
      currentDownloading?.file_name || activeLocalDownloads[0]?.file_name || "";

    if (currentDownloading) {
      localStats.localStatus = "downloading";
      if (
        currentDownloading.total_size > 0 &&
        currentDownloading.downloaded_size >= 0
      ) {
        localStats.localProgress = Math.round(
          (currentDownloading.downloaded_size / currentDownloading.total_size) *
            100
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

    localStats.activeLocalDownloads = activeLocalDownloads.map((d) => ({
      file_name: d.file_name,
      progress:
        d.total_size > 0
          ? Math.round((d.downloaded_size / d.total_size) * 100)
          : 0,
      status: d.status,
    }));

    localStats = { ...localStats };
  }

  async function addDownload(isAutoDownload = false) {
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
        if (newDownload.status === "waiting" && newDownload.message_key) {
          showToastMsg($t(newDownload.message_key, newDownload.message_args));
        } else if (!isAutoDownload) {
          showToastMsg($t("download_added_successfully"));
        }
        url = "";
        password = "";
        hasPassword = false;
        syncDownloadsSilently(); // 새 다운로드 추가 후 조용한 업데이트
      } else {
        const errorData = await response.json();
        showToastMsg($t("add_download_failed", { detail: errorData.detail }));
      }
    } catch (error) {
      console.error("Error adding download:", error);
      showToastMsg($t("add_download_error"));
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

  async function callApi(
    endpoint,
    downloadId = null,
    expectedNewStatus = null
  ) {
    try {
      const response = await fetch(endpoint, { method: "POST" });
      if (response.ok) {
        const responseData = await response.json();

        // 응답에서 대기 상태 메시지 확인
        if (responseData.status === "waiting" && responseData.message_key) {
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
          console.log(`API 호출 성공: ${endpoint}`);

          // 사용자 피드백을 위한 토스트 메시지 (응답 내용에 따라 구분)
          if (endpoint.includes("/resume/")) {
            // 응답에서 실제로 이어받기인지 새 다운로드인지 구분
            if (
              responseData &&
              responseData.message &&
              responseData.message.includes("resume")
            ) {
              showToastMsg($t("resume_request_sent"), "info");
            } else {
              showToastMsg(
                $t("download_request_sent") || "다운로드 요청을 보냈습니다.",
                "info"
              );
            }
          } else if (endpoint.includes("/pause/")) {
            // API 응답에서 success 확인 후 토스트 표시
            if (
              responseData &&
              (responseData.success || responseData.status === "stopped")
            ) {
              showToastMsg($t("stop_request_sent"), "success");
            } else {
              showToastMsg($t("stop_request_sent"), "info");
            }
          } else if (endpoint.includes("/retry/")) {
            showToastMsg($t("retry_request_sent"), "info");
          }

          // 즉시 상태 새로고침 (깜빡거림 없이)
          syncDownloadsSilently();
        }
      } else {
        // HTTP 응답이 실패인 경우
        const errorText = await response.text();
        console.error(
          `API 호출 실패: ${endpoint}, 상태: ${response.status}, 응답: ${errorText}`
        );

        if (endpoint.includes("/pause/")) {
          showToastMsg("정지 요청이 실패했습니다.", "error");
        } else if (endpoint.includes("/resume/")) {
          showToastMsg("재개 요청이 실패했습니다.", "error");
        } else if (endpoint.includes("/retry/")) {
          showToastMsg("재시도 요청이 실패했습니다.", "error");
        } else {
          showToastMsg(`요청이 실패했습니다 (${response.status})`, "error");
        }
      }
      await fetchActiveDownloads();
    } catch (error) {
      console.error(`Error calling ${endpoint}:`, error);
      // API 호출 실패 시 사용자에게 피드백 제공
      if (endpoint.includes("/pause/")) {
        showToastMsg("정지 요청 처리 중 오류가 발생했습니다.", "error");
      } else if (endpoint.includes("/resume/")) {
        showToastMsg("재개 요청 처리 중 오류가 발생했습니다.", "error");
      } else if (endpoint.includes("/retry/")) {
        showToastMsg("재시도 요청 처리 중 오류가 발생했습니다.", "error");
      } else {
        showToastMsg("요청 처리 중 오류가 발생했습니다.", "error");
      }
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
            showToastMsg($t("download_deleted_success"));
            downloads = downloads.filter((download) => download.id !== id);
          } else {
            const errorData = await response.json();
            showToastMsg(
              $t("delete_failed_with_detail", { detail: errorData.detail })
            );
          }
        } catch (error) {
          console.error("Error deleting download:", error);
          showToastMsg($t("delete_error"));
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

  function formatSpeed(bytesPerSecond) {
    if (!bytesPerSecond || bytesPerSecond === 0) return "0 B/s";
    const k = 1024;
    const sizes = ["B/s", "KB/s", "MB/s", "GB/s"];
    const i = Math.floor(Math.log(bytesPerSecond) / Math.log(k));
    const speed = (bytesPerSecond / Math.pow(k, i)).toFixed(i >= 2 ? 2 : 1);
    return speed + " " + sizes[i];
  }

  function getStatusTooltip(download) {
    const proxyInfo = downloadProxyInfo[download.id];

    // 1fichier 쿨다운 상태 체크
    if (download.status.toLowerCase() === "cooldown" && download.message) {
      return download.message;
    }

    // 1fichier 자동 재시도 상태 체크
    if (
      download.status.toLowerCase() === "pending" &&
      download.error &&
      download.error.includes("1fichier 자동 재시도 중")
    ) {
      return download.error + "\n3분마다 자동 재시도됩니다.";
    }

    if (download.status.toLowerCase() === "failed" && download.error) {
      if (proxyInfo && proxyInfo.error) {
        return $t("status_tooltip_failed_with_proxy", {
          error: download.error,
          proxy: proxyInfo.proxy,
          proxy_error: proxyInfo.error,
        });
      }
      return download.error;
    }

    if (proxyInfo) {
      const statusIcon = {
        trying: "⟳",
        success: "✓",
        failed: "✗",
      };

      const icon = statusIcon[proxyInfo.status] || "●";
      let tooltip = `${icon} ${$t("proxy_tooltip_proxy")}: ${proxyInfo.proxy}\n${$t("proxy_tooltip_step")}: ${proxyInfo.step}`;

      if (proxyInfo.current && proxyInfo.total) {
        tooltip += `\n${$t("proxy_tooltip_progress")}: ${proxyInfo.current}/${proxyInfo.total}`;
      }

      if (proxyInfo.status === "trying") {
        const timeSince = Math.floor((Date.now() - proxyInfo.timestamp) / 1000);
        tooltip += `\n${$t("proxy_tooltip_trying")} (${timeSince}${$t("proxy_tooltip_seconds")})`;
      }

      if (proxyInfo.error) {
        tooltip += `\n${$t("proxy_tooltip_error")}: ${proxyInfo.error}`;
      }

      return tooltip;
    }

    const statusTooltips = {
      pending: $t("download_pending"),
      parsing: $t("download_parsing"),
      proxying: $t("download_proxying"),
      downloading: $t("download_downloading"),
      done: $t("download_done"),
      stopped: $t("download_stopped"),
      failed: $t("download_failed"),
      cooldown: $t("download_cooldown"),
    };

    return statusTooltips[download.status.toLowerCase()] || download.status;
  }

  function formatDate(dateString) {
    if (!dateString) return "-";
    const currentLocale = localStorage.getItem("lang") || "en";
    const date = new Date(dateString);
    const today = new Date();

    // 오늘이면 시간만 표시
    if (date.toDateString() === today.toDateString()) {
      return date.toLocaleTimeString(
        currentLocale === "ko" ? "ko-KR" : "en-US",
        {
          hour: "2-digit",
          minute: "2-digit",
        }
      );
    }

    // 다른 날이면 간단한 날짜 형식
    if (currentLocale === "ko") {
      return `${date.getMonth() + 1}월 ${date.getDate()}일`;
    } else {
      return date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
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
      return Math.round(download.progress * 2) / 2; // 0.5% 단위로 반올림
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
      return url.protocol === "http:" || url.protocol === "https:";
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
        await addDownload(true);
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
      showToastMsg($t("clipboard_copy_success_with_link", { link }));
    } catch (e) {
      showToastMsg($t("clipboard_copy_failed"));
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
          use_proxy: download.use_proxy || false,
        }),
      });
      if (response.ok) {
        showToastMsg($t("redownload_requested"));
        syncDownloadsSilently(); // 재다운로드 요청 후 조용한 업데이트
        currentTab = "working";
      } else {
        const errorData = await response.json();
        showToastMsg(
          $t("redownload_failed_with_detail", { detail: errorData.detail })
        );
      }
    } catch (error) {
      console.error("Error redownloading:", error);
      showToastMsg($t("redownload_error"));
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
      // 탭 전환 시 조용한 데이터 새로고침
      syncDownloadsSilently();
    }
  }

  $: workingCount = downloads.filter((d) => {
    const status = d.status?.toLowerCase?.() || "";
    // stopped는 100% 완료된 경우 completed로 처리
    if (
      status === "stopped" &&
      (d.progress >= 100 || getDownloadProgress(d) >= 100)
    ) {
      return false; // working 탭에서 제외
    }
    return [
      "pending",
      "downloading",
      "proxying",
      "stopped",
      "failed",
      "cooldown",
    ].includes(status);
  }).length;

  $: completedCount = downloads.filter((d) => {
    const status = d.status?.toLowerCase?.() || "";
    // done 상태 또는 100% 완료된 stopped 상태
    return (
      status === "done" ||
      (status === "stopped" &&
        (d.progress >= 100 || getDownloadProgress(d) >= 100))
    );
  }).length;

  $: filteredDownloads = (() => {
    if (currentTab === "working") {
      return downloads.filter((d) => {
        const status = d.status?.toLowerCase?.() || "";
        // stopped는 100% 완료된 경우 working에서 제외
        if (
          status === "stopped" &&
          (d.progress >= 100 || getDownloadProgress(d) >= 100)
        ) {
          return false;
        }
        return [
          "pending",
          "downloading",
          "parsing",
          "proxying",
          "stopped",
          "failed",
          "cooldown",
        ].includes(status);
      });
    } else {
      // 완료 탭: done 상태 또는 100% 완료된 stopped 상태
      return downloads
        .filter((d) => {
          const status = d.status?.toLowerCase?.() || "";
          return (
            status === "done" ||
            (status === "stopped" &&
              (d.progress >= 100 || getDownloadProgress(d) >= 100))
          );
        })
        .sort((a, b) => {
          // completed_at이 있으면 그것으로, 없으면 updated_at으로 정렬 (최신순)
          const aTime = new Date(a.completed_at || a.updated_at || 0);
          const bTime = new Date(b.completed_at || b.updated_at || 0);
          return bTime.getTime() - aTime.getTime(); // 역순 정렬 (최신이 먼저)
        });
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

  $: activeProxyDownloadCount = downloads.filter(
    (d) =>
      d.use_proxy &&
      ["downloading", "proxying"].includes(d.status?.toLowerCase?.() || "")
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
      <form
        on:submit|preventDefault={() => addDownload()}
        class="download-form"
      >
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
              class="proxy-toggle-button {useProxy
                ? 'proxy'
                : 'local'} {!proxyAvailable ? 'disabled' : ''}"
              on:click={() => {
                if (proxyAvailable) {
                  useProxy = !useProxy;
                  showToastMsg(
                    useProxy
                      ? $t("mode_switched_to_proxy")
                      : $t("mode_switched_to_local"),
                    "success"
                  );
                } else {
                  showToastMsg($t("proxy_unavailable_tooltip"), "warning");
                }
              }}
              title={!proxyAvailable
                ? $t("proxy_unavailable_tooltip")
                : useProxy
                  ? $t("proxy_mode_tooltip")
                  : $t("local_mode_tooltip")}
              aria-label={!proxyAvailable
                ? $t("proxy_unavailable_tooltip")
                : useProxy
                  ? $t("proxy_mode_tooltip")
                  : $t("local_mode_tooltip")}
            >
              <div class="proxy-toggle-slider"></div>
              <div class="proxy-toggle-icons"></div>
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

      <div
        class="table-container"
        class:empty-table={filteredDownloads.length === 0}
      >
        <table>
          <thead>
            <tr>
              <th>{$t("table_header_file_name")}</th>
              <th class="center-align">{$t("table_header_status")}</th>
              <th class="center-align">{$t("table_header_size")}</th>
              <th class="center-align">{$t("table_header_progress")}</th>
              {#if currentTab !== "completed"}
                <th class="center-align">{$t("table_header_speed")}</th>
              {/if}
              <th class="center-align">{$t("table_header_requested_date")}</th>
              <th class="center-align">{$t("table_header_proxy")}</th>
              <th class="center-align actions-header"
                >{$t("table_header_actions")}</th
              >
            </tr>
          </thead>
          <tbody>
            {#if isDownloadsLoading}
              <tr>
                <td colspan={currentTab === "completed" ? 7 : 8}>
                  <div class="table-loading-container">
                    <div class="modal-spinner"></div>
                    <div class="modal-loading-text">{$t("loading")}</div>
                  </div>
                </td>
              </tr>
            {:else if filteredDownloads.length === 0}
              <tr class="empty-row">
                <td
                  colspan={currentTab === "completed" ? 7 : 8}
                  class="no-downloads-message"
                >
                  {currentTab === "working"
                    ? $t("no_working_downloads")
                    : $t("no_completed_downloads")}
                </td>
              </tr>
            {:else}
              {#each paginatedDownloads as download (download.id)}
                <tr>
                  <td
                    class="filename"
                    title={download.file_name || $t("file_name_na")}
                  >
                    <span class="filename-text"
                      >{download.file_name || $t("file_name_na")}</span
                    >
                  </td>
                  <td class="center-align">
                    <span
                      class="status status-{download.status.toLowerCase()} interactive-status {download.use_proxy
                        ? 'proxy-status'
                        : 'local-status'}"
                      title={getStatusTooltip(download)}
                    >
                      {#if download.status.toLowerCase() === "cooldown" && download.cooldown_remaining}
                        <span class="cooldown-countdown">
                          {$t("download_cooldown")} ({download.cooldown_remaining}{$t(
                            "time_seconds"
                          )})
                          <span class="cooldown-indicator"></span>
                        </span>
                      {:else if downloadWaitInfo[download.id] && downloadWaitInfo[download.id].remaining_time > 0 && !["stopped", "done", "failed"].includes(download.status.toLowerCase())}
                        <span class="wait-countdown">
                          {#if downloadWaitInfo[download.id].remaining_time >= 60}
                            {$t("download_waiting")} ({Math.floor(
                              downloadWaitInfo[download.id].remaining_time / 60
                            )}{$t("time_minutes")})
                          {:else}
                            {$t("download_waiting")} ({downloadWaitInfo[
                              download.id
                            ].remaining_time}{$t("time_seconds")})
                          {/if}
                          <span
                            class="wait-indicator wait-indicator-{download.status.toLowerCase()}"
                          ></span>
                        </span>
                      {:else}
                        {$t(`download_${download.status.toLowerCase()}`)}
                        {#if ["proxying", "parsing", "downloading"].includes(download.status.toLowerCase())}
                          <span
                            class="proxy-indicator proxy-indicator-{download.status.toLowerCase()}"
                          ></span>
                        {/if}
                      {/if}
                    </span>
                  </td>
                  <td class="center-align">
                    {download.file_size ||
                      (download.total_size
                        ? formatBytes(download.total_size)
                        : "-")}
                  </td>
                  <td class="center-align">
                    <div class="progress-container">
                      <div
                        class="progress-bar"
                        style="width: {currentTab === 'completed'
                          ? '100'
                          : getDownloadProgress(download)}%"
                      ></div>
                      <span class="progress-text">
                        {currentTab === "completed"
                          ? "100"
                          : getDownloadProgress(download)}%
                      </span>
                    </div>
                  </td>
                  {#if currentTab !== "completed"}
                    <td class="center-align speed-cell">
                      {#if download.download_speed && (download.status.toLowerCase() === "downloading" || download.status.toLowerCase() === "proxying" || download.status.toLowerCase() === "parsing")}
                        <span
                          class="speed-text {download.use_proxy
                            ? 'proxy-speed'
                            : 'local-speed'}"
                        >
                          {formatSpeed(download.download_speed)}
                        </span>
                      {:else if ["parsing", "downloading", "proxying", "pending", "waiting", "cooldown"].includes(download.status.toLowerCase())}
                        <span
                          class="speed-text parsing-indicator {download.use_proxy
                            ? 'proxy-loading'
                            : 'local-loading'}"
                        >
                          <span class="parsing-dots">•••</span>
                        </span>
                      {:else}
                        <span class="speed-text-empty">-</span>
                      {/if}
                    </td>
                  {/if}
                  <td
                    class="center-align"
                    title={formatFullDateTime(download.requested_at)}
                  >
                    {formatDate(download.requested_at)}
                  </td>
                  <td class="proxy-toggle-cell">
                    <button
                      type="button"
                      class="grid-proxy-toggle {download.use_proxy
                        ? 'proxy'
                        : 'local'}"
                      disabled={download.status.toLowerCase() !== "stopped"}
                      title={download.use_proxy
                        ? $t("proxy_mode")
                        : $t("local_mode")}
                      on:click={async () => {
                        try {
                          const response = await fetch(
                            `/api/downloads/${download.id}/proxy-toggle`,
                            {
                              method: "PUT",
                              headers: { "Content-Type": "application/json" },
                            }
                          );

                          if (response.ok) {
                            const result = await response.json();
                            // 프론트엔드 상태 업데이트
                            downloads = downloads.map((d) =>
                              d.id === download.id
                                ? { ...d, use_proxy: result.use_proxy }
                                : d
                            );
                          } else {
                            showToastMsg(
                              "프록시 모드 변경에 실패했습니다.",
                              "error"
                            );
                          }
                        } catch (error) {
                          console.error("프록시 토글 오류:", error);
                          showToastMsg(
                            "프록시 모드 변경 중 오류가 발생했습니다.",
                            "error"
                          );
                        }
                      }}
                      aria-label={download.use_proxy
                        ? $t("proxy_mode")
                        : $t("local_mode")}
                    >
                      <div class="grid-toggle-slider"></div>
                      <div class="grid-toggle-icons"></div>
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
                      {#if ["downloading", "proxying", "pending", "parsing", "cooldown"].includes(download.status?.toLowerCase())}
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
                          title={download.progress > 0
                            ? $t("action_resume")
                            : $t("action_start")}
                          on:click={() =>
                            callApi(
                              `/api/resume/${download.id}?use_proxy=${download.use_proxy}`,
                              download.id,
                              null
                            )}
                          aria-label={download.progress > 0
                            ? $t("action_resume")
                            : $t("action_start")}
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
              start: (currentPage - 1) * itemsPerPage + 1,
              end: Math.min(
                currentPage * itemsPerPage,
                filteredDownloads.length
              ),
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

{#if $showToast}
  <div class="toast">{$toastMessage}</div>
{/if}
