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
  import SearchIcon from "./icons/SearchIcon.svelte";
  import CheckCircleIcon from "./icons/CheckCircleIcon.svelte";
  import BarChartIcon from "./icons/BarChartIcon.svelte";
  import CloseIcon from "./icons/CloseIcon.svelte";
  import ChevronLeftIcon from "./icons/ChevronLeftIcon.svelte";
  import ChevronRightIcon from "./icons/ChevronRightIcon.svelte";
  import { Toaster, toast } from 'svelte-sonner';
  import ConfirmModal from "./lib/ConfirmModal.svelte";
  import AuditModal from "./lib/AuditModal.svelte";
  import ProxyGauge from "./lib/ProxyGauge.svelte";
  import LocalGauge from "./lib/LocalGauge.svelte";
  import Dashboard from "./lib/Dashboard.svelte";
  import HistoryPeriodControls from "./lib/HistoryPeriodControls.svelte";
  import { EventSourceManager } from "./EventSource.js";
  import Skeleton from "./lib/Skeleton.svelte";

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
  let eventSourceManager;
  let currentPage = 1;
  let totalPages = 1;
  let itemsPerPage = 10; // 기본값, 화면 크기에 따라 동적으로 변경
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

  // 링크 검수(audit) 진행 상태 — 헤더 버튼/토스트가 함께 참조.
  let auditRunning = false;
  let auditDone = 0;
  let auditTotal = 0;
  let showAuditModal = false;
  // 다중선택 모드 — 실패/정지 row 에 체크박스 컬럼 노출.
  let selectMode = false;
  let selectedIds = new Set();
  let showBulkDeleteConfirm = false;
  let pendingBulkDelete = []; // confirm 모달에서 사용

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

  // 디바운싱을 위한 타이머
  let activeDownloadsTimer = null;

  // SSE 업데이트 배칭 (requestAnimationFrame) — 상태 할당을 다음 프레임으로 지연
  let pendingStateUpdates = [];
  let batchRafId = null;

  function queueStateUpdate(updateFn) {
    pendingStateUpdates.push(updateFn);
    if (batchRafId === null) {
      batchRafId = requestAnimationFrame(() => {
        batchRafId = null;
        const updates = pendingStateUpdates;
        pendingStateUpdates = [];
        updates.forEach((fn) => {
          fn();
        });
      });
    }
  }

  // 대기시간 실시간 업데이트를 위한 타이머
  let waitTimeUpdateTimer = null;
  let currentTime = Date.now();

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
  let searchQuery = "";
  let searchExpanded = false;
  let searchInputEl;
  let searchTimeout;

  // Dashboard statistics state
  let dashboardPeriod = "30d";
  let dashboardStartDate = "";
  let dashboardEndDate = "";
  let dashboardStats = null;
  let dashboardHistory = [];
  let dashboardTotalPages = 0;
  let dashboardCurrentPage = 1;
  // dashboardExpanded 제거 — 대시보드는 항상 노출.
  let systemStats = null;
  let systemStatsInterval = null;

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

  onMount(async () => {
    itemsPerPage = calculateItemsPerPage();

    // 먼저 언어 설정부터 처리
    const lang = localStorage.getItem("lang");
    if (lang) {
      await loadTranslations(lang);
      prevLang = lang;
    } else {
      await initializeLocale();
      prevLang = localStorage.getItem("lang");
    }

    await fetchSettings();
    if (currentSettings.language && currentSettings.language !== prevLang) {
      localStorage.setItem("lang", currentSettings.language);
      await loadTranslations(currentSettings.language);
      prevLang = currentSettings.language;
    }

    // 로그인이 필요하지 않거나 이미 인증된 경우에만 EventSource 연결
    if (!$needsLogin || $isAuthenticated) {
      fetchDownloads(currentPage);
      connectEventSource();
      fetchActiveDownloads();
      fetchProxyStatus();
      checkProxyAvailability();

      // 대시보드는 항상 노출이라 마운트 시점에 즉시 초기 데이터 로드 + 시스템
      // 모니터링 폴링 시작. 이전엔 펼침 토글에서만 시작했지만 토글이 사라졌음.
      fetchDashboardStats();
      fetchDashboardHistory();
      fetchSystemStats();
      if (!systemStatsInterval) {
        systemStatsInterval = setInterval(fetchSystemStats, 5000);
      }
    }

    // 대기시간 실시간 업데이트 타이머 시작
    function startWaitTimeUpdateTimer() {
      waitTimeUpdateTimer = setInterval(() => {
        currentTime = Date.now();
      }, 1000);
    }
    startWaitTimeUpdateTimer();

    // 프록시 새로고침 이벤트 리스너 추가
    const handleProxyRefresh = () => {
      fetchProxyStatus();
      checkProxyAvailability();
    };
    document.addEventListener("proxy-refreshed", handleProxyRefresh);

    // 윈도우 리사이즈 이벤트 리스너 추가
    window.addEventListener("resize", handleResize);

    // 모바일에서의 페이지 백그라운드 복귀 시 조용한 업데이트 로직
    let lastVisibilityTime = Date.now();
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        const now = Date.now();
        const timeSinceLastVisible = now - lastVisibilityTime;

        // 5초 이상 백그라운드에 있었으면 업데이트
        if (timeSinceLastVisible > 5000) {
          syncDownloadsSilently();

          // EventSource 재연결 (연결이 끊어졌을 수도 있음)
          if (!eventSourceManager || !eventSourceManager.isConnected()) {
            reconnectEventSource();
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

    // 테이블 컬럼 리사이즈 기능 추가
    const cleanupResize = initTableColumnResize();

    // cleanup 함수를 onDestroy에 등록
    return () => {
      cleanupResize && cleanupResize();
      document.removeEventListener("proxy-refreshed", handleProxyRefresh);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("resize", handleResize);
    };
  });

  function initTableColumnResize() {
    let isResizing = false;
    let currentColumn = null;
    let startX = 0;
    let startWidth = 0;

    // 마우스 다운 이벤트 (리사이즈 시작)
    function handleMouseDown(e) {
      // 테이블 헤더의 :after 가상요소 영역인지 확인
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

    // 마우스 이동 이벤트 (리사이즈 중)
    function handleMouseMove(e) {
      if (!isResizing || !currentColumn) {
        // 리사이즈 중이 아닐 때 커서 변경
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

      // 헤더 자체 설정
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

    // 마우스 업 이벤트 (리사이즈 종료)
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

    // cleanup 함수 반환 (컴포넌트 제거 시 사용)
    return () => {
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }

  onDestroy(() => {
    // EventSource 정리
    if (eventSourceManager) {
      eventSourceManager.disconnect();
    }

    // 타이머 정리
    if (activeDownloadsTimer) {
      clearTimeout(activeDownloadsTimer);
    }
    if (waitTimeUpdateTimer) {
      clearInterval(waitTimeUpdateTimer);
    }
    if (activeDownloadsInterval) {
      clearInterval(activeDownloadsInterval);
    }
    if (batchRafId !== null) {
      cancelAnimationFrame(batchRafId);
      batchRafId = null;
      pendingStateUpdates = [];
    }
    if (systemStatsInterval) {
      clearInterval(systemStatsInterval);
      systemStatsInterval = null;
    }
  });

  function handleLoginSuccess() {
    // 로그인 성공 후 필요한 데이터 로드 및 EventSource 연결
    fetchDownloads(currentPage);
    connectEventSource();
    fetchActiveDownloads();
    fetchProxyStatus();
    checkProxyAvailability();
  }

  function handleResetProxyStatus() {
    // 프록시 상태를 idle로 리셋
    proxyStats = {
      ...proxyStats,
      status: "idle",
      currentProxy: "",
      currentStep: "",
      currentIndex: 0,
      totalAttempting: 0,
      status_message: ""
    };
    console.log("🔄 프록시 상태 리셋됨 (일괄 정지)");
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
          status_message: data.status_message,
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

  // Dashboard date helper: compute start/end YYYY-MM-DD from dashboardPeriod
  function getDashboardDateRange() {
    const today = new Date();
    const fmt = (d) => d.toISOString().slice(0, 10);
    const todayStr = fmt(today);

    switch (dashboardPeriod) {
      case "today":
        return { start: todayStr, end: todayStr };
      case "7d": {
        const d = new Date(today);
        d.setDate(d.getDate() - 7);
        return { start: fmt(d), end: todayStr };
      }
      case "30d": {
        const d = new Date(today);
        d.setDate(d.getDate() - 30);
        return { start: fmt(d), end: todayStr };
      }
      case "all":
        return { start: null, end: null };
      case "custom":
        return { start: dashboardStartDate, end: dashboardEndDate };
      default:
        return { start: null, end: null };
    }
  }

  async function fetchDashboardStats() {
    try {
      const { start, end } = getDashboardDateRange();
      let url = "/api/history/stats";
      const params = new URLSearchParams();
      if (start) params.set("start_date", start);
      if (end) params.set("end_date", end);
      if (params.toString()) url += "?" + params.toString();

      const response = await fetch(url);
      if (response.ok) {
        dashboardStats = await response.json();
      }
    } catch (error) {
      console.error("Error fetching dashboard stats:", error);
    }
  }

  async function fetchSystemStats() {
    try {
      const response = await fetch("/api/system/stats");
      if (response.ok) {
        systemStats = await response.json();
      }
    } catch (error) {
      console.error("Error fetching system stats:", error);
    }
  }

  async function fetchDashboardHistory() {
    try {
      const { start, end } = getDashboardDateRange();
      let url = "/api/history/period";
      const params = new URLSearchParams();
      if (start) params.set("start_date", start);
      if (end) params.set("end_date", end);
      params.set("page", String(dashboardCurrentPage));
      params.set("page_size", "50");
      url += "?" + params.toString();

      const response = await fetch(url);
      if (response.ok) {
        const data = await response.json();
        dashboardHistory = data.history || [];
        dashboardTotalPages = data.total_pages || 0;
      }
    } catch (error) {
      console.error("Error fetching dashboard history:", error);
    }
  }

  // Reactive: fetch dashboard data when period or page changes
  $: if (dashboardPeriod) {
    fetchDashboardStats();
    fetchDashboardHistory();
  }

  function connectEventSource() {
    if (!eventSourceManager) {
      eventSourceManager = new EventSourceManager();
    }

    eventSourceManager.connect((message) => {

      if (message.type === "status_update") {
        const updatedDownload = message.data;
        // 실패 메시지를 즉시 UI 에 반영 (백엔드는 message 로 보냄)
        if (
          updatedDownload?.status?.toLowerCase?.() === "failed" &&
          updatedDownload?.message &&
          !updatedDownload.error_message
        ) {
          updatedDownload.error_message = updatedDownload.message;
        }
        // ID 타입 통일 (숫자로 변환)
        const downloadId = Number.parseInt(updatedDownload.id, 10);

        // 상태 할당 배칭: 큐 실행 시점의 최신 downloads 기준으로 병합
        queueStateUpdate(() => {
          let proxyStatsChanged = false;
          const currentIndex = downloads.findIndex((d) => Number.parseInt(d.id, 10) === downloadId);

          if (currentIndex !== -1) {
            // 프록시 상태 리셋 처리 (stopped, failed, done 상태일 때)
            if (
              proxyStats.status === "trying" &&
              ["stopped", "failed", "done"].includes(updatedDownload.status?.toLowerCase())
            ) {
              const otherProxyDownloads = downloads.filter(
                (d) =>
                  Number.parseInt(d.id, 10) !== downloadId &&
                  (d.status === "parsing" || d.status === "downloading")
              );

              if (otherProxyDownloads.length === 0) {
                proxyStats.status = "idle";
                proxyStats.currentProxy = null;
                proxyStats.tryStartTime = null;
                proxyStatsChanged = true;
                console.log(`🔄 다운로드 ${downloadId} 상태 변경으로 인한 프록시 상태 리셋`);
              }
            }

            downloads = downloads.map((d, i) =>
              i === currentIndex ? { ...d, ...updatedDownload } : d
            );
            if (updatedDownload.status !== "waiting" && downloadWaitInfo[downloadId]) {
              delete downloadWaitInfo[downloadId];
              downloadWaitInfo = { ...downloadWaitInfo };
            }
            updateStats(downloads);
            if (proxyStatsChanged) {
              proxyStats = { ...proxyStats };
            }
          } else if (downloadId && !Number.isNaN(downloadId) && updatedDownload.url) {
            downloads = [updatedDownload, ...downloads];
            updateStats(downloads);
          } else {
            console.warn("❌ 잘못된 다운로드 데이터 무시:", updatedDownload);
          }
        });
      }

      // 배치 업데이트 처리
      if (message.type === "batch_status_update") {
        queueStateUpdate(() => {
          let hasChanges = false;
          let proxyStatsChanged = false;
          const newDownloads = [...downloads];

          message.data.forEach((updatedDownload) => {
            // 실패 메시지를 error_message 로도 매핑
            if (
              updatedDownload?.status?.toLowerCase?.() === "failed" &&
              updatedDownload?.message &&
              !updatedDownload.error_message
            ) {
              updatedDownload.error_message = updatedDownload.message;
            }
            const index = newDownloads.findIndex((d) => d.id === updatedDownload.id);
            if (index !== -1) {
              const oldDownload = newDownloads[index];
              newDownloads[index] = { ...newDownloads[index], ...updatedDownload };
              hasChanges = true;

              // 프록시 다운로드의 상태가 stopped, failed, done으로 변경되면 다른 진행 중인 프록시 다운로드가 없을 때만 프록시 상태 초기화
              if (
                oldDownload.use_proxy &&
                oldDownload.status !== updatedDownload.status &&
                ["stopped", "failed", "done"].includes(updatedDownload.status?.toLowerCase())
              ) {
                // 다른 활성 프록시 다운로드가 있는지 확인
                const otherActiveProxyDownloads = newDownloads.filter(
                  (d) =>
                    d.use_proxy &&
                    d.id !== updatedDownload.id &&
                    ["pending", "proxying", "parsing", "downloading"].includes(
                      d.status?.toLowerCase()
                    )
                );

                // 다른 활성 프록시 다운로드가 없을 때만 프록시 상태 초기화
                if (otherActiveProxyDownloads.length === 0) {
                  proxyStats.status = "";
                  proxyStats.currentProxy = "";
                  proxyStats.currentStep = "";
                  proxyStats.currentIndex = 0;
                  proxyStats.totalAttempting = 0;
                  proxyStatsChanged = true;
                  console.log(`[LOG] 마지막 프록시 다운로드 종료, 프록시 상태 초기화`);
                } else {
                  console.log(`[LOG] 다른 프록시 다운로드 진행 중 (${otherActiveProxyDownloads.length}개), 프록시 상태 유지`);
                }
              }
            } else {
              newDownloads.unshift(updatedDownload);
              hasChanges = true;
            }
          });

          if (hasChanges) {
            downloads = newDownloads;
            // 통계만 업데이트 (fetchActiveDownloads는 디바운싱으로 별도 처리)
            updateStats(downloads);
          }
          if (proxyStatsChanged) {
            proxyStats = { ...proxyStats };
          }
        });
      }

      // 프록시 메시지 처리
      if (message.type === "proxy_trying") {
        const { id, proxy, step, current, total, failed } = message.data;
        console.log(`[DEBUG] SSE proxy_trying 수신:`, message.data);
        proxyStats.currentProxy = proxy;
        proxyStats.currentStep = step;
        proxyStats.currentIndex = current;
        proxyStats.totalAttempting = total;
        // totalProxies는 전체 프록시 수이므로 변경하지 않음 (total은 현재 배치의 크기)
        // 실패 카운트 실시간 업데이트와 함께 사용 가능한 프록시도 차감 (1초 디바운싱)
        const prevFailCount = proxyStats.failCount || 0;
        const newFailCount = failed || 0;
        const failedDiff = newFailCount - prevFailCount;

        console.log(`[DEBUG] proxy_trying - 이전: ${prevFailCount}, 현재: ${newFailCount}, 차이: ${failedDiff}, 현재 잔여: ${proxyStats.availableProxies}`);

        proxyStats.failCount = newFailCount;

        // 실패 카운트 증가와 동시에 사용 가능한 프록시도 바로 차감
        if (failedDiff > 0 && proxyStats.availableProxies > 0) {
          const beforeAvailable = proxyStats.availableProxies;
          proxyStats.availableProxies = Math.max(0, proxyStats.availableProxies - failedDiff);
          console.log(`[DEBUG] 프록시 즉시 차감: ${failedDiff}개, ${beforeAvailable} -> ${proxyStats.availableProxies}`);
        }
        proxyStats.status = "trying";

        // 상태 할당 배칭
        queueStateUpdate(() => {
          proxyStats = { ...proxyStats };
          // 메인 그리드에서 해당 다운로드 상태도 업데이트 (빠지지 않도록)
          if (id) {
            const download = downloads.find(d => d.id === id);
            if (download) {
              const failedText = failed > 0 ? ` (실패: ${failed})` : '';
              download.proxy_message = `${step} - ${proxy} (${current}/${total})${failedText}`;
              downloads = [...downloads];
            }

            // 프록시 작업이 시작되면 대기 정보 제거
            if (downloadWaitInfo[id]) {
              delete downloadWaitInfo[id];
              downloadWaitInfo = { ...downloadWaitInfo };
              console.log(`🛑 프록시 작업 시작으로 인한 대기 정보 제거: ${id} (${step})`);
            }
          }
        });
      }



      if (message.type === "proxy_success") {
        const { id, proxy, step, message: msg } = message.data;
        proxyStats.currentProxy = proxy;
        proxyStats.currentStep = msg || step;
        proxyStats.status = "success";
        proxyStats.successCount++;

        // 상태 할당 배칭
        queueStateUpdate(() => {
          proxyStats = { ...proxyStats };

          // 메인 그리드에서 해당 다운로드 상태도 업데이트
          if (id) {
            const download = downloads.find(d => d.id === id);
            if (download) {
              download.proxy_message = `${proxy} - ${msg || step}`;
              downloads = [...downloads];
            }
          }
        });
      }

      if (message.type === "proxy_failed") {
        const { id, proxy, step, error, message: msg } = message.data;
        proxyStats.currentProxy = proxy || "";
        proxyStats.currentStep = msg || step;
        proxyStats.status = "failed";
        proxyStats.lastError = error || "";
        proxyStats.failCount++;

        // 상태 할당 배칭
        queueStateUpdate(() => {
          proxyStats = { ...proxyStats };

          // 메인 그리드에서 해당 다운로드 상태도 업데이트
          if (id) {
            const download = downloads.find(d => d.id === id);
            if (download) {
              download.proxy_message = msg || step;
              downloads = [...downloads];
            }
          }
        });
      }

      // 프록시 상태 초기화 처리
      if (message.type === "proxy_reset") {
        console.log("🔄 프록시 상태 초기화 메시지 수신:", message.data);
        proxyStats.status = "";
        proxyStats.currentProxy = "";
        proxyStats.currentStep = "";
        proxyStats.currentIndex = 0;
        proxyStats.totalAttempting = 0;
        // 상태 할당 배칭
        queueStateUpdate(() => {
          proxyStats = { ...proxyStats };
        });
        console.log("[LOG] 프록시 상태 강제 초기화 완료");
      }

      // 1fichier 대기시간 처리 (파싱 후 대기)
      // 백엔드는 status_update 로 status="waiting" 을 따로 한 번 보냄.
      // 여기서는 카운트다운 데이터(downloadWaitInfo)만 갱신해서 race
      // (status_update 와 waiting 메시지가 뒤섞일 때 status 가 강제로
      // 덮어써지는 문제) 를 방지.
      if (message.type === "waiting") {
        const { id, remaining, total } = message.data;
        downloadWaitInfo[id] = {
          remaining_time: remaining,
          total_time: total,
        };
        queueStateUpdate(() => {
          downloadWaitInfo = { ...downloadWaitInfo };
        });
      }

      // 대기 완료 처리
      if (message.type === "wait_countdown_complete") {
        const { id } = message.data;
        delete downloadWaitInfo[id];
        queueStateUpdate(() => {
          downloadWaitInfo = { ...downloadWaitInfo };
        });
      }

      // 다운로드 정지 시 대기 정보 제거
      if (message.type === "download_stopped") {
        const { id } = message.data;
        const waitInfoExists = !!downloadWaitInfo[id];
        let proxyStatsChanged = false;
        if (waitInfoExists) {
          delete downloadWaitInfo[id];
          console.log(`🛑 정지로 인한 대기 정보 제거: ${id}`);
        }

        // 프록시 상태 리셋 (다른 프록시 사용 중인 다운로드가 없을 때만)
        if (proxyStats.status === "trying") {
          const otherProxyDownloads = downloads.filter(d =>
            d.id !== id &&
            (d.status === "parsing" || d.status === "downloading")
          );

          if (otherProxyDownloads.length === 0) {
            proxyStats.status = "idle";
            proxyStats.currentProxy = null;
            proxyStats.tryStartTime = null;
            proxyStatsChanged = true;
            console.log(`🔄 마지막 프록시 다운로드 ${id} 중지로 인한 프록시 상태 리셋`);
          } else {
            console.log(`🔄 다른 프록시 다운로드 ${otherProxyDownloads.length}개 진행 중, 프록시 상태 유지`);
          }
        }

        if (waitInfoExists || proxyStatsChanged) {
          queueStateUpdate(() => {
            if (waitInfoExists) {
              downloadWaitInfo = { ...downloadWaitInfo };
            }
            if (proxyStatsChanged) {
              proxyStats = { ...proxyStats };
            }
          });
        }
      }

      // 파일명 업데이트 처리
      if (message.type === "filename_update") {
        console.log("📁 filename_update 메시지 수신:", message.data);
        const { id, filename, file_size } = message.data;
        queueStateUpdate(() => {
          const currentIndex = downloads.findIndex((d) => d.id === id);
          if (currentIndex !== -1) {
            downloads = downloads.map((d, i) => {
              if (i === currentIndex) {
                console.log(
                  `📁 파일명 업데이트: ID=${id}, ${d.filename} → ${filename}, 크기: ${file_size}`
                );
                return {
                  ...d,
                  filename: filename || d.filename,
                  file_size: file_size || d.file_size,
                };
              }
              return d;
            });
          }
        });
      }

      // SSE 테스트 메시지 처리
      if (message.type === "test_message") {
        console.log("🧪 SSE 테스트 메시지 수신:", message.data);
        alert($t("sse_connection_normal") + ": " + message.data.message);
      }

      if (message.type === "force_refresh") {
        console.log("🔄 Force refresh 요청 수신:", message.data);
        // 전체 다운로드 목록을 다시 불러오기
        fetchDownloads();
      }

      // 단건 probe 결과 — 행 갱신만 가볍게.
      if (message.type === "probe_result") {
        const { id, failure_kind, next_retry_at, kind, summary } = message.data;
        queueStateUpdate(() => {
          downloads = downloads.map((d) =>
            d.id === id
              ? { ...d, failure_kind, next_retry_at }
              : d
          );
        });
        if (kind === "alive") {
          toast.success($t("probe_alive_message"));
        } else if (kind === "dead") {
          toast.warning($t("probe_dead_message"));
        } else if (summary) {
          toast.info(summary);
        }
      }

      // 배치 audit 진행률 — 시작/단계/완료 단계 토스트.
      if (message.type === "audit_progress") {
        const { status, done, total, counts } = message.data;
        if (status === "start") {
          auditTotal = total;
          auditDone = 0;
          auditRunning = true;
          toast.info($t("audit_started", { total }));
        } else if (status === "step") {
          auditDone = done;
          auditTotal = total;
        } else if (status === "done") {
          auditRunning = false;
          auditDone = done;
          const alive = counts?.alive ?? 0;
          const dead = counts?.dead ?? 0;
          const other = total - alive - dead;
          toast.success($t("audit_done", { alive, dead, other }));
          fetchDownloads(); // 박제 해제된 항목들을 화면에 반영
        }
      }
    });
  }

  function reconnectEventSource() {
    if (eventSourceManager) {
      eventSourceManager.reconnect();
    }
  }

  // 조용한 백그라운드 동기화 (깜빡거림 없음) - 기존 fetchDownloads 사용
  async function syncDownloadsSilently() {
    try {
      const response = await fetch(`/api/history/`, { timeout: 10000 });

      if (response.ok) {
        const data = await response.json();
        const historyData = data.history || [];
        downloads = historyData;

        // 완료되거나 정지된 다운로드의 대기 정보 정리
        Object.keys(downloadWaitInfo).forEach(downloadId => {
          const id = parseInt(downloadId);
          const download = downloads.find(d => d.id === id);
          if (!download || download.status === 'stopped' || download.status === 'done' || download.status === 'failed') {
            delete downloadWaitInfo[downloadId];
          }
        });
        downloadWaitInfo = { ...downloadWaitInfo };
      }
    } catch (error) {
      console.error("Background sync failed:", error);
    }
  }

  async function fetchDownloads(page = 1, retryCount = 0) {
    isDownloadsLoading = true;

    try {
      const response = await fetch(`/api/history/`, { timeout: 10000 });

      if (response.ok) {
        const data = await response.json();
        const historyData = data.history || [];
        downloads = historyData;
        currentPage = 1;
        totalPages = 1;

        updateStats(historyData);
      } else {
        console.error("History API failed with status:", response.status);
        const errorText = await response.text();
        console.error("Error response:", errorText);

        // 재시도 로직
        if (
          retryCount < 2 &&
          (response.status >= 500 || response.status === 0)
        ) {
          console.log(`재시도 중.. (${retryCount + 1}/3)`);
          setTimeout(() => fetchDownloads(page, retryCount + 1), 2000);
          return;
        }
        downloads = [];
      }
    } catch (error) {
      console.error("Error fetching downloads:", error);

      // 네트워크 오류 시 재시도
      if (retryCount < 2) {
        console.log(`네트워크 오류 재시도 중.. (${retryCount + 1}/3)`);
        setTimeout(() => fetchDownloads(page, retryCount + 1), 2000);
        return;
      }
      downloads = [];
    } finally {
      if (retryCount === 0 || retryCount >= 2) {
        isDownloadsLoading = false;
      }
    }
  }

  function updateProxyStats(downloadsData) {
    if (!downloadsData || !Array.isArray(downloadsData)) return;

    const activeProxyDownloads = downloadsData.filter(
      (d) =>
        d.use_proxy &&
        ["downloading", "proxying"].includes(d.status?.toLowerCase?.() || "")
    );

    proxyStats.activeDownloadCount = activeProxyDownloads.length;
    proxyStats = { ...proxyStats };
  }

  // 전역 디바운싱을 위한 플래그
  let needsActiveDownloadsUpdate = false;
  let activeDownloadsInterval = null;

  // fetchActiveDownloads를 주기적으로 호출하는 인터벌 (5초마다 - 성능 최적화)
  onMount(() => {
    activeDownloadsInterval = setInterval(() => {
      if (needsActiveDownloadsUpdate) {
        fetchActiveDownloads();
        needsActiveDownloadsUpdate = false;
      }
    }, 5000);
  });


  // 통합된 통계 업데이트 함수
  function updateStats(downloadsData) {
    updateProxyStats(downloadsData);
    updateLocalStats(downloadsData);

    // 디바운싱 대신 플래그만 설정
    needsActiveDownloadsUpdate = true;
  }

  function updateLocalStats(downloadsData) {
    if (!downloadsData || !Array.isArray(downloadsData)) return;

    const localDownloads = downloadsData.filter((d) => !d.use_proxy);

    const activeLocalDownloads = localDownloads.filter((d) => {
      const status = d.status?.toLowerCase?.() || "";
      return !(
        status === "done" ||
        (status === "stopped" &&
          (d.progress >= 100 || getDownloadProgress(d) >= 100))
      );
    });

    const currentDownloading = activeLocalDownloads.find(
      (d) => d.status?.toLowerCase() === "downloading"
    );

    localStats.localDownloadCount = activeLocalDownloads.length;
    localStats.localCurrentFile =
      currentDownloading?.filename || activeLocalDownloads[0]?.filename || "";

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
      // 실제 진행 중인 상태만 확인: pending, parsing 등
      const activeStatusDownloads = activeLocalDownloads.filter(d => {
        const status = d.status?.toLowerCase() || "";
        return ["pending", "parsing"].includes(status);
      });

      if (activeStatusDownloads.length > 0) {
        localStats.localStatus = "waiting";
      } else {
        // failed, stopped 등은 진행중이 아니므로 idle
        localStats.localStatus = "";
      }
      localStats.localProgress = 0;
    } else {
      localStats.localStatus = "";
      localStats.localProgress = 0;
    }

    localStats.activeLocalDownloads = activeLocalDownloads.map((d) => ({
      filename: d.filename,
      progress:
        d.total_size > 0
          ? Math.round((d.downloaded_size / d.total_size) * 100)
          : 0,
      status: d.status,
    }));

    localStats = { ...localStats };
  }

  async function addDownload(isAutoDownload = false, skipValidation = false) {
    if (!url) return;
    
    // URL 기본 검증만 수행 (validate-url API 제거)
    
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
          toast.info($t(newDownload.message_key, newDownload.message_args));
        } else if (!isAutoDownload) {
          toast.success($t("download_added_successfully"));
        }
        url = "";
        password = "";
        hasPassword = false;
        fetchDownloads(); // 목록 즉시 새로고침
      } else {
        const errorData = await response.json();
        toast.error($t("add_download_failed", { detail: errorData.detail }));
      }
    } catch (error) {
      console.error("Error adding download:", error);
      toast.error($t("add_download_error"));
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

  async function startAudit(payload = null) {
    // payload 없이 호출되면 모달 열기 — 헤더 버튼 클릭 시.
    if (payload === null) {
      if (auditRunning) {
        toast.warning($t("audit_already_running"));
        return;
      }
      showAuditModal = true;
      return;
    }

    // 모달에서 'start' 이벤트로 받은 페이로드 그대로 전송.
    try {
      const response = await fetch("/api/downloads/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (response.status === 409) {
        toast.warning($t("audit_already_running"));
        return;
      }
      const data = await response.json();
      if (!data.started) {
        toast.info($t("audit_no_targets"));
        return;
      }
      // started=true 면 곧 SSE audit_progress(start) 가 들어와서 토스트가 뜬다.
    } catch (e) {
      console.error("audit 시작 실패:", e);
      toast.error(`audit error: ${e.message}`);
    }
  }

  function auditSelected() {
    if (selectedIds.size === 0) return;
    const ids = Array.from(selectedIds);
    startAudit({ ids });
  }

  function failedDownloadIds() {
    if (!Array.isArray(downloads)) return [];
    return downloads
      .filter((d) => {
        const status = d.status?.toLowerCase?.() || "";
        return status === "failed";
      })
      .map((d) => d.id)
      .filter((id) => id && !isNaN(parseInt(id)));
  }

  function deleteFailedDownloads() {
    const ids = failedDownloadIds();
    if (ids.length === 0) {
      toast.info($t("delete_failed_empty"));
      return;
    }

    openConfirm({
      title: $t("confirm_delete_title"),
      message: $t("delete_failed_confirm", { count: ids.length }),
      confirmText: $t("delete_failed_downloads"),
      cancelText: $t("button_cancel"),
      onConfirm: async () => {
        try {
          const response = await fetch("/api/downloads/bulk-delete", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ids }),
          });
          if (!response.ok) {
            let detail = response.statusText;
            try {
              const data = await response.json();
              detail = data.detail || detail;
            } catch (_) {}
            toast.error($t("bulk_delete_failed", { detail }));
            return;
          }
          const data = await response.json();
          toast.success($t("bulk_delete_success", { count: data.deleted_count }));
          fetchDownloads();
        } catch (e) {
          console.error("failed delete error:", e);
          toast.error(`failed delete error: ${e.message}`);
        }
      },
    });
  }

  async function bulkDeleteSelected() {
    if (selectedIds.size === 0) return;
    pendingBulkDelete = Array.from(selectedIds);
    showBulkDeleteConfirm = true;
  }

  async function performBulkDelete() {
    const ids = pendingBulkDelete;
    pendingBulkDelete = [];
    try {
      const response = await fetch("/api/downloads/bulk-delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
      if (!response.ok) {
        let detail = response.statusText;
        try {
          const data = await response.json();
          detail = data.detail || detail;
        } catch (_) {}
        toast.error($t("bulk_delete_failed", { detail }));
        return;
      }
      const data = await response.json();
      toast.success($t("bulk_delete_success", { count: data.deleted_count }));
      selectedIds = new Set();
      selectMode = false;
      fetchDownloads();
    } catch (e) {
      console.error("bulk delete error:", e);
      toast.error(`bulk delete error: ${e.message}`);
    }
  }

  function toggleSelect(id) {
    if (selectedIds.has(id)) selectedIds.delete(id);
    else selectedIds.add(id);
    selectedIds = new Set(selectedIds);
  }

  function exitSelectMode() {
    selectMode = false;
    selectedIds = new Set();
  }

  async function callApi(endpoint, downloadId = null) {
    try {
      const response = await fetch(endpoint, { method: "POST" });
      
      if (response.ok) {
        const responseData = await response.json();

        // 대기 상태 메시지 처리
        if (responseData.status === "waiting" && responseData.message_key) {
          toast.info($t(responseData.message_key, responseData.message_args));
          return;
        }

        // 성공 메시지 표시
        const action = endpoint.includes("/start/") ? "download" :
                     endpoint.includes("/pause/") ? "pause" :
                     endpoint.includes("/resume/") ? "resume" :
                     endpoint.includes("/retry/") ? "retry" :
                     endpoint.includes("/stop/") ? "stop" : "download";

        const messageKey = `${action}_request_sent`;
        toast.success($t(messageKey));
        
        console.log(`API 호출 성공: ${endpoint}`);
      } else {
        // 재시도 차단 사유는 별도 메시지로 분기 (영구 실패 / 로그인 필요)
        if (response.status === 409 && endpoint.includes("/retry/")) {
          let detail = "";
          try {
            const data = await response.json();
            detail = data.detail || "";
          } catch (_) { /* JSON 아님 — 폴백 메시지 사용 */ }
          if (detail === "retry_blocked_dead") {
            toast.error($t("retry_blocked_dead"));
            return;
          }
          if (detail === "retry_blocked_auth_required") {
            toast.error($t("retry_blocked_auth_required"));
            return;
          }
        }

        // 에러 메시지 표시
        const action = endpoint.includes("/stop/") ? $t("action_stop") :
                     endpoint.includes("/resume/") ? $t("action_resume_action") :
                     endpoint.includes("/retry/") ? $t("action_retry_action") : $t("action_work");

        toast.error(`${action} 요청에 실패했습니다.`);
        console.error(`API 호출 실패: ${endpoint}, 상태: ${response.status}`);
      }
    } catch (error) {
      const action = endpoint.includes("/stop/") ? $t("action_stop") :
                   endpoint.includes("/resume/") ? $t("action_resume_action") :
                   endpoint.includes("/retry/") ? $t("action_retry_action") : $t("action_work");
      
      toast.error($t("request_processing_error", {action}));
      console.error(`Error calling ${endpoint}:`, error);
    }
    
    // SSE가 자동으로 상태를 업데이트하므로 추가 fetch는 불필요
  }

  async function deleteDownload(id) {
    // ID 유효성 검사
    if (!id || isNaN(parseInt(id))) {
      console.error("❌ 잘못된 다운로드 ID:", id);
      toast.error($t("invalid_download_id"));
      return;
    }
    
    openConfirm({
      message: $t("delete_confirm"),
      onConfirm: async () => {
        try {
          const response = await fetch(`/api/delete/${id}`, {
            method: "DELETE",
          });
          if (response.ok) {
            toast.success($t("download_deleted_success"));
            downloads = Array.isArray(downloads) ? downloads.filter((download) => download.id !== id) : [];
          } else {
            const errorData = await response.json();
            toast.error(
              $t("delete_failed_with_detail", { detail: errorData.detail })
            );
          }
        } catch (error) {
          console.error("Error deleting download:", error);
          toast.error($t("delete_error"));
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

  // 대기시간 카운트다운 표기 — 항상 mm:ss 형식.
  // 60초 경계에서 단위가 점프(60초 → 1분 → 59초)하던 비일관성 제거.
  function formatWaitTime(seconds) {
    if (seconds == null || seconds < 0) return "0:00";
    const total = Math.max(0, Math.floor(seconds));
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
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

    // 1fichier 자동 재시도 상태 체크
    if (
      download.status.toLowerCase() === "pending" &&
      download.error_message &&
      download.error_message.includes($t("auto_retry_in_progress"))
    ) {
      return download.error_message + "\n3분마다 자동 재시도됩니다.";
    }

    if (download.status.toLowerCase() === "failed" && download.error_message) {
      if (proxyInfo && proxyInfo.error) {
        return $t("status_tooltip_failed_with_proxy", {
          error: download.error_message,
          proxy: proxyInfo.proxy,
          proxy_error: proxyInfo.error,
        });
      }
      return download.error_message;
    }

    if (proxyInfo) {
      const statusIcon = {
        trying: "🔄",
        success: "✅",
        failed: "❌",
      };

      const icon = statusIcon[proxyInfo.status] || "❓";
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
    };

    return statusTooltips[download.status.toLowerCase()] || download.status;
  }

  function formatDate(dateString) {
    if (!dateString) return "-";
    // Use the active language code as the BCP-47 locale for localized output.
    const currentLocale = localStorage.getItem("lang") || "en";
    const date = new Date(dateString);
    const today = new Date();

    // Same day: show time only
    if (date.toDateString() === today.toDateString()) {
      return date.toLocaleTimeString(currentLocale, {
        hour: "2-digit",
        minute: "2-digit",
      });
    }

    // Otherwise: short, localized date
    return date.toLocaleDateString(currentLocale, {
      month: "short",
      day: "numeric",
    });
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

  // URL 유효성 검증 함수
  function isValidUrl(string) {
    try {
      const url = new URL(string);
      return url.protocol === "http:" || url.protocol === "https:";
    } catch (_) {
      return false;
    }
  }

  // 모바일 기기 감지
  function isMobileDevice() {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
  }

  // 화면 크기에 따른 페이지 항목 수 계산
  function calculateItemsPerPage() {
    if (typeof window === 'undefined') return 10;

    const width = window.innerWidth;
    const height = window.innerHeight;

    // 모바일
    if (width < 768) {
      return Math.max(5, Math.floor(height / 80)); // 모바일은 항목 높이를 80px로 가정
    }
    // 태블릿
    else if (width < 1024) {
      return Math.max(8, Math.floor(height / 70)); // 태블릿은 항목 높이를 70px로 가정
    }
    // 데스크톱
    else {
      return Math.max(10, Math.floor(height / 60)); // 데스크톱은 항목 높이를 60px로 가정
    }
  }

  // 윈도우 리사이즈 핸들러
  function handleResize() {
    const newItemsPerPage = calculateItemsPerPage();
    if (newItemsPerPage !== itemsPerPage) {
      itemsPerPage = newItemsPerPage;
      // 현재 페이지가 유효한 범위를 벗어나면 조정
      totalPages = Math.ceil(filteredDownloads.length / itemsPerPage);
      if (currentPage > totalPages && totalPages > 0) {
        currentPage = totalPages;
      }
    }
  }

  async function pasteFromClipboard() {
    try {
      // 먼저 현대적인 clipboard API 시도
      if (navigator.clipboard && navigator.clipboard.readText) {
        const text = await navigator.clipboard.readText();
        if (!text || text.trim() === "") {
          toast.warning($t("clipboard_empty"));
          return;
        }

        const trimmedText = text.trim();
        url = trimmedText;

        // URL 형식이 유효한지 먼저 검사
        if (!isValidUrl(trimmedText)) {
          toast.info($t("clipboard_pasted"));
          return;
        }

        // 기본 URL 검증 후 자동으로 다운로드 추가
        toast.info($t("clipboard_url_auto_download"));
        await addDownload(true, true); // skipValidation = true
        return;
      }

      // clipboard API가 없으면 사용자에게 수동 붙여넣기 안내
      const isMobile = isMobileDevice();
      if (isMobile) {
        toast.info($t("clipboard_mobile_paste_guide"));
      } else {
        toast.info($t("clipboard_desktop_paste_guide"));
      }

    } catch (err) {
      console.error("Failed to read clipboard contents: ", err);

      const isMobile = isMobileDevice();

      // 권한 거부나 기타 오류 시 fallback
      if (err.name === 'NotAllowedError' || err.name === 'NotFoundError') {
        if (isMobile) {
          toast.info($t("clipboard_access_denied_mobile"));
        } else {
          toast.info($t("clipboard_access_denied_desktop"));
        }
      } else {
        toast.error($t("clipboard_read_failed"));
      }
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
      toast.success($t("clipboard_copy_success_with_link", { link }));
    } catch (e) {
      toast.error($t("clipboard_copy_failed"));
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
        toast.success($t("redownload_requested"));
        syncDownloadsSilently(); // 다시 다운로드 요청 시 조용한 업데이트
        currentTab = "working";
      } else {
        const errorData = await response.json();
        toast.error(
          $t("redownload_failed_with_detail", { detail: errorData.detail })
        );
      }
    } catch (error) {
      console.error("Error redownloading:", error);
      toast.error($t("redownload_error"));
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
      searchExpanded = false;
      // 탭 이동 시 선택 모드는 자동 해제 — 다른 탭의 id 가 섞이지 않게.
      if (selectMode || selectedIds.size > 0) {
        exitSelectMode();
      }
      // 검색어는 탭 전환 시에도 유지
      currentPage = 1; // 탭 전환 시 첫 페이지로 이동
      // 탭 전환 시 조용한 데이터 새로고침
      syncDownloadsSilently();
    }
  }

  // 검색 입력 핸들러 (클라이언트 사이드 필터링만)
  function handleSearchInput() {
    // 검색어가 변경되면 filteredDownloads가 자동으로 업데이트됨
    // API 호출 없이 클라이언트 사이드에서만 필터링
    currentPage = 1; // 검색 시 첫 페이지로 이동
  }

  // 검색어 지우기
  function clearSearch() {
    searchQuery = "";
    searchExpanded = false;
    currentPage = 1;
  }

  function openSearch() {
    searchExpanded = true;
    requestAnimationFrame(() => searchInputEl?.focus());
  }

  function closeSearch() {
    searchExpanded = false;
  }

  // (구) toggleDashboard — 대시보드는 항상 펼쳐져 있으므로 토글 제거.

  // 통합 필터링 및 카운팅 (한 번의 순회로 모든 계산 완료)
  let filteredDownloads = [];
  let workingCount = 0;
  let completedCount = 0;
  $: {
    if (!Array.isArray(downloads)) {
      workingCount = 0;
      completedCount = 0;
      filteredDownloads = [];
    } else {
      // 1단계: 검색 필터 적용
      let filtered = downloads;
      if (searchQuery && searchQuery.trim()) {
        const query = searchQuery.trim().toLowerCase();
        filtered = downloads.filter((d) => {
          const filename = d.filename?.toLowerCase() || "";
          const url = d.url?.toLowerCase() || "";
          return filename.includes(query) || url.includes(query);
        });
      }

      // 2단계: 한 번의 순회로 분류 (working/completed)
      const working = [];
      const completed = [];

      for (const d of filtered) {
        const status = d.status?.toLowerCase?.() || "";
        const isCompleted = status === "done" ||
          (status === "stopped" && (d.progress >= 100 || getDownloadProgress(d) >= 100));

        if (isCompleted) {
          completed.push(d);
        } else {
          working.push(d);
        }
      }

      workingCount = working.length;
      completedCount = completed.length;

      // 3단계: 현재 탭에 따라 정렬
      if (currentTab === "working") {
        filteredDownloads = working;
      } else {
        // 완료 탭: 최신순 정렬
        filteredDownloads = completed.sort((a, b) => {
          const aTime = new Date(a.finished_at || a.created_at || a.updated_at || 0);
          const bTime = new Date(b.finished_at || b.created_at || b.updated_at || 0);
          return bTime.getTime() - aTime.getTime();
        });
      }
    }
  }

  // 페이지 계산
  $: {
    totalPages = Math.ceil(filteredDownloads.length / itemsPerPage);
    if (currentPage > totalPages && totalPages > 0) {
      currentPage = totalPages;
    }
  }

  // 페이지별 다운로드
  $: paginatedDownloads = filteredDownloads.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );

  // 페이지 함수
  function goToPage(page) {
    if (page >= 1 && page <= totalPages) {
      currentPage = page;
    }
  }

  // 탭이 변경될 때 페이지 리셋
  $: if (currentTab) {
    currentPage = 1;
  }

  $: activeProxyDownloadCount = Array.isArray(downloads) ? downloads.filter(
    (d) =>
      d.use_proxy &&
      ["downloading", "proxying"].includes(d.status?.toLowerCase?.() || "")
  ).length : 0;
  $: failedDownloadCount = failedDownloadIds().length;
  $: dashboardSummaryTotal = dashboardStats?.total ?? downloads.length;
  $: dashboardSummarySuccessRate = dashboardStats?.success_rate ?? (downloads.length > 0
    ? (completedCount / downloads.length) * 100
    : 0);
  $: dashboardSummaryBytes = dashboardStats?.total_bytes ?? downloads.reduce(
    (total, download) => total + (download.total_size || 0),
    0
  );
</script>

<main>
  {#if $authLoading || $isLoading}
    <div class="skeleton-page">
      <!-- Header -->
      <div class="skeleton-header">
        <Skeleton width="38px" height="38px" circle={true} />
        <div class="skeleton-header-title">
          <Skeleton width="180px" height="26px" radius="6px" />
        </div>
        <Skeleton width="36px" height="36px" radius="8px" />
      </div>
      <!-- Form card -->
      <div class="skeleton-card">
        <Skeleton width="100%" height="42px" radius="8px" />
        <div class="skeleton-form-row">
          <Skeleton width="72px" height="36px" radius="20px" />
          <Skeleton width="140px" height="36px" radius="8px" />
        </div>
      </div>
      <!-- Live gauges -->
      <div class="skeleton-live-card">
        {#each Array(2) as _}
          <div class="skeleton-live-pane">
            <Skeleton width="55%" height="13px" radius="3px" />
            <Skeleton width="100%" height="56px" radius="8px" />
            <Skeleton width="80%" height="10px" radius="3px" />
          </div>
        {/each}
      </div>
      <!-- Monitor grid -->
      <div class="skeleton-monitor-grid">
        {#each Array(4) as _}
          <div class="skeleton-monitor-card">
            <Skeleton width="45%" height="11px" radius="3px" />
            <div class="skeleton-monitor-body">
              <Skeleton width="86px" height="86px" circle={true} />
              <Skeleton width="100%" height="44px" radius="4px" />
            </div>
          </div>
        {/each}
      </div>
      <!-- Tabs -->
      <div class="skeleton-tabs-row">
        <Skeleton width="90px" height="32px" radius="6px" />
        <Skeleton width="90px" height="32px" radius="6px" />
      </div>
      <!-- Table -->
      <div class="skeleton-table">
        <div class="skeleton-table-header">
          {#each Array(8) as _}
            <Skeleton width="70%" height="12px" radius="3px" />
          {/each}
        </div>
        {#each Array(5) as _}
          <div class="skeleton-table-row">
            <Skeleton width="85%" height="14px" radius="3px" />
            <Skeleton width="64px" height="22px" radius="10px" />
            <Skeleton width="52px" height="14px" radius="3px" />
            <Skeleton width="100%" height="8px" radius="4px" />
            <Skeleton width="52px" height="14px" radius="3px" />
            <Skeleton width="82px" height="14px" radius="3px" />
            <Skeleton width="44px" height="22px" radius="10px" />
            <Skeleton width="76px" height="28px" radius="6px" />
          </div>
        {/each}
      </div>
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
          on:click={() => (selectMode ? exitSelectMode() : (selectMode = true))}
          class="button-icon select-mode-button"
          class:active={selectMode}
          title={selectMode ? $t("select_mode_exit") : $t("select_mode_enter")}
          aria-label={selectMode ? $t("select_mode_exit") : $t("select_mode_enter")}
        >
          ☑
        </button>
        <button
          on:click={() => startAudit()}
          class="button-icon audit-button"
          class:is-running={auditRunning}
          disabled={auditRunning}
          title={auditRunning
            ? $t("action_audit_running") + ` (${auditDone}/${auditTotal})`
            : $t("action_audit")}
          aria-label={$t("action_audit")}
        >
          <InfoIcon />
        </button>
        <button
          on:click={deleteFailedDownloads}
          class="button-icon"
          disabled={failedDownloadCount === 0}
          title={$t("delete_failed_downloads")}
          aria-label={$t("delete_failed_downloads")}
        >
          <DeleteIcon />
        </button>
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
                  toast.success(
                    useProxy
                      ? $t("mode_switched_to_proxy")
                      : $t("mode_switched_to_local")
                  );
                } else {
                  toast.warning($t("proxy_unavailable_tooltip"));
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

    <!-- 통합 대시보드 — KPI/차트는 설정 "통계" 탭으로 이동. 메인은 라이브(프록시·로컬
         합본 카드) + 시스템 모니터링만. 조회 조건(기간) 은 그리드 헤더로 이동. -->
    <Dashboard {systemStats}>
      <!-- 프록시 + 로컬을 하나의 카드 안에서 두 분할로. 시각적으로 한 가족이
           되고, 카드 외곽선/그림자/모서리도 dashboard 카드와 같음. -->
      <div slot="gauges" class="live-card">
        <div class="live-pane live-pane-proxy">
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
            statusMessage={proxyStats.status_message || ""}
            on:resetProxyStatus={handleResetProxyStatus}
          />
        </div>
        <div class="live-pane live-pane-local">
          <LocalGauge
            localDownloadCount={localStats.localDownloadCount}
            localStatus={localStats.localStatus}
          />
        </div>
      </div>
    </Dashboard>

    <div class="downloads-section">
      <!-- 조회 조건(기간) — 그리드 위 별도 줄. PC 는 중앙 정렬, 모바일은 풀폭. -->
      <div class="grid-period-bar">
        <HistoryPeriodControls
          bind:period={dashboardPeriod}
          bind:startDate={dashboardStartDate}
          bind:endDate={dashboardEndDate}
          on:periodChange={(e) => {
            dashboardPeriod = e.detail;
            fetchDashboardStats();
            fetchDashboardHistory();
          }}
          on:customApply={() => {
            fetchDashboardStats();
            fetchDashboardHistory();
          }}
        />
      </div>

      <div class="tabs-container">
        <div class="tabs">
          <button
            class="tab"
            class:active={currentTab === "working"}
            on:click={() => onTabChange("working")}
            title={$t("tab_working")}
          >
            <span class="tab-icon"><DownloadIcon /></span>
            <span class="tab-label">{$t("tab_working")}</span>
            {#if workingCount > 0}
              <span class="tab-count">{workingCount}</span>
            {/if}
          </button>
          <button
            class="tab"
            class:active={currentTab === "completed"}
            on:click={() => onTabChange("completed")}
            title={$t("tab_completed")}
          >
            <span class="tab-icon"><CheckCircleIcon /></span>
            <span class="tab-label">{$t("tab_completed")}</span>
            {#if completedCount > 0}
              <span class="tab-count">{completedCount}</span>
            {/if}
          </button>
        </div>

        <!-- 검색 필터 -->
        <div class="search-actions" class:expanded={searchExpanded}>
            <button
              type="button"
              class="button-icon search-toggle-btn"
              on:click={openSearch}
              title={$t("search_placeholder")}
              aria-label={$t("search_placeholder")}
            >
              <SearchIcon />
            </button>
            <div class="search-container">
            <input
              type="text"
              class="search-input"
              placeholder={$t("search_placeholder")}
              bind:this={searchInputEl}
              bind:value={searchQuery}
              on:input={handleSearchInput}
              on:focus={() => (searchExpanded = true)}
            />
            {#if searchQuery && searchQuery.trim()}
              <button
                type="button"
                class="search-clear-btn"
                on:click={clearSearch}
                title="검색어 지우기"
                aria-label="검색어 지우기"
              >
                <CloseIcon />
              </button>
            {:else if searchExpanded}
              <button
                type="button"
                class="search-clear-btn search-collapse-btn"
                on:click={closeSearch}
                title="검색창 닫기"
                aria-label="검색창 닫기"
              >
                <CloseIcon />
              </button>
            {:else}
              <div class="search-icon">
                <SearchIcon />
              </div>
            {/if}
            </div>
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
              {#each Array(5) as _}
                <tr class="skeleton-row">
                  <td><Skeleton width="80%" height="14px" radius="3px" /></td>
                  <td class="center-align"><Skeleton width="64px" height="22px" radius="10px" /></td>
                  <td class="center-align"><Skeleton width="52px" height="14px" radius="3px" /></td>
                  <td class="center-align"><Skeleton width="100%" height="8px" radius="4px" /></td>
                  {#if currentTab !== "completed"}
                    <td class="center-align"><Skeleton width="52px" height="14px" radius="3px" /></td>
                  {/if}
                  <td class="center-align"><Skeleton width="82px" height="14px" radius="3px" /></td>
                  <td class="center-align"><Skeleton width="44px" height="22px" radius="10px" /></td>
                  <td class="center-align"><Skeleton width="76px" height="28px" radius="6px" /></td>
                </tr>
              {/each}
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
                <tr class:is-selected={selectMode && selectedIds.has(download.id)}>
                  <td
                    class="filename"
                    title={download.filename || $t("file_name_na")}
                  >
                    {#if selectMode}
                      <input
                        type="checkbox"
                        class="row-select"
                        checked={selectedIds.has(download.id)}
                        on:change={() => toggleSelect(download.id)}
                        aria-label="row {download.id}"
                      />
                    {/if}
                    <span class="filename-text"
                      >{download.filename || $t("file_name_na")}</span
                    >
                  </td>
                  <td class="center-align">
                    <span
                      class="status status-{download.status.toLowerCase()} interactive-status {download.use_proxy
                        ? 'proxy-status'
                        : 'local-status'}"
                      title={getStatusTooltip(download)}
                    >
                      {#if download.status.toLowerCase() === "waiting" && downloadWaitInfo[download.id] && downloadWaitInfo[download.id].remaining_time > 0}
                        <span class="wait-countdown">
                          {$t("download_waiting_time")} ({formatWaitTime(downloadWaitInfo[download.id].remaining_time)})
                          <span
                            class="wait-indicator wait-indicator-{download.status.toLowerCase()}"
                          ></span>
                        </span>
                      {:else if download.status.toLowerCase() === "downloading" && !download.progress}
                        <span class="wait-countdown">
                          {$t("download_downloading")}
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
                    {#if download.status.toLowerCase() === "failed" && download.failure_kind}
                      <!-- 실패 분류 칩: dead 는 빨강, auth/rate/cloudflare/proxy_blocked 는 주황, 일시류는 회색 -->
                      <span
                        class="kind-chip kind-chip-{download.failure_kind}"
                        title={download.error_message || $t("kind_" + download.failure_kind)}
                      >{$t("kind_" + download.failure_kind)}</span>
                    {/if}
                  </td>
                  <td class="center-align">
                    {download.total_size
                      ? formatBytes(download.total_size)
                      : download.file_size || "-"}
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
                      {:else if ["parsing", "downloading", "proxying", "pending", "waiting"].includes(download.status.toLowerCase())}
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
                    title={formatFullDateTime(download.created_at)}
                  >
                    {formatDate(download.created_at)}
                  </td>
                  <td class="proxy-toggle-cell">
                    <button
                      type="button"
                      class="grid-proxy-toggle {download.use_proxy
                        ? 'proxy'
                        : 'local'}"
                      disabled={!["stopped", "failed"].includes(download.status.toLowerCase())}
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
                            // 프론트엔드의 상태 업데이트
                            downloads = downloads.map((d) =>
                              d.id === download.id
                                ? { ...d, use_proxy: result.use_proxy }
                                : d
                            );
                          } else {
                            toast.error(
                              "프록시 모드 변경에 실패했습니다."
                            );
                          }
                        } catch (error) {
                          console.error("프록시 토글 오류:", error);
                          toast.error(
                            $t("proxy_mode_change_error")
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
                      {#if ["downloading", "proxying", "pending", "parsing", "waiting"].includes(download.status?.toLowerCase())}
                        <button
                          class="button-icon"
                          title={$t("action_pause")}
                          on:click={() => {
                            if (download.id && !isNaN(parseInt(download.id))) {
                              callApi(`/api/downloads/stop/${download.id}`)
                            } else {
                              console.error("❌ 잘못된 다운로드 ID:", download.id, download)
                            }
                          }}
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
                          on:click={() => callApi(`/api/downloads/start/${download.id}`)}
                          aria-label={download.progress > 0
                            ? $t("action_resume")
                            : $t("action_start")}
                        >
                          <ResumeIcon />
                        </button>
                      {/if}
                      {#if download.status?.toLowerCase() === "failed"}
                        {#if download.failure_kind === "dead" || download.failure_kind === "unknown_terminal"}
                          <!-- 원본이 사라진 파일 / 반복 실패 — 클릭 자체를 막아 의미 없는 재요청을 차단 -->
                          <button
                            class="button-icon is-disabled"
                            title={$t("retry_blocked_dead")}
                            on:click={() => toast.error($t("retry_blocked_dead"))}
                            aria-label={$t("retry_blocked_dead")}
                            aria-disabled="true"
                          >
                            <RetryIcon />
                          </button>
                        {:else if download.failure_kind === "auth_required"}
                          <button
                            class="button-icon is-warn"
                            title={$t("retry_blocked_auth_required")}
                            on:click={() => callApi(`/api/retry/${download.id}`)}
                            aria-label={$t("retry_blocked_auth_required")}
                          >
                            <RetryIcon />
                          </button>
                        {:else if download.next_retry_at && new Date(download.next_retry_at).getTime() > Date.now()}
                          <!-- cooldown 상태 — 강제 재시도는 허용 (서버에서 cooldown 만 초기화) -->
                          <button
                            class="button-icon is-cooldown"
                            title={$t("retry_cooldown", { when: new Date(download.next_retry_at).toLocaleTimeString() })}
                            on:click={() => callApi(`/api/retry/${download.id}`)}
                            aria-label={$t("retry_cooldown", { when: new Date(download.next_retry_at).toLocaleTimeString() })}
                          >
                            <RetryIcon />
                          </button>
                        {:else}
                          <button
                            class="button-icon"
                            title={download.failure_kind ? $t("kind_" + download.failure_kind) : $t("action_retry")}
                            on:click={() => callApi(`/api/retry/${download.id}`)}
                            aria-label={$t("action_retry")}
                          >
                            <RetryIcon />
                          </button>
                        {/if}
                        <!-- 단건 검수: 살아있는지 즉시 확인 (1fichier 만 의미) -->
                        {#if (download.original_url || download.url || "").includes("1fichier.com")}
                          <button
                            class="button-icon"
                            title={$t("action_audit")}
                            on:click={() => callApi(`/api/downloads/${download.id}/probe`, "POST")}
                            aria-label={$t("action_audit")}
                          >
                            <InfoIcon />
                          </button>
                        {/if}
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
          <!-- 데스크톱용 스마트 페이지네이션 -->
          <div class="pagination-desktop">
            <button
              class="page-number-btn prev-next-btn"
              on:click={() => goToPage(currentPage - 1)}
              disabled={currentPage <= 1}
            >
              <ChevronLeftIcon />
            </button>

            <!-- 스마트 페이지 번호 버튼들 -->
            {#if totalPages <= 7}
              <!-- 총 페이지가 7개 이하면 모두 표시 -->
              {#each Array(totalPages) as _, i}
                {@const pageNum = i + 1}
                <button
                  class="page-number-btn"
                  class:active={currentPage === pageNum}
                  on:click={() => goToPage(pageNum)}
                >
                  {pageNum}
                </button>
              {/each}
            {:else}
              <!-- 복잡한 페이지네이션 로직 -->
              {#if currentPage <= 4}
                <!-- 현재 페이지가 앞쪽에 있을 때: 1,2,3,4,5 ... 14 -->
                {#each [1,2,3,4,5] as pageNum}
                  <button
                    class="page-number-btn"
                    class:active={currentPage === pageNum}
                    on:click={() => goToPage(pageNum)}
                  >
                    {pageNum}
                  </button>
                {/each}
                <span class="page-dots">...</span>
                <button
                  class="page-number-btn"
                  on:click={() => goToPage(totalPages)}
                >
                  {totalPages}
                </button>
              {:else if currentPage >= totalPages - 3}
                <!-- 현재 페이지가 뒤쪽에 있을 때: 1 ... 10,11,12,13,14 -->
                <button
                  class="page-number-btn"
                  on:click={() => goToPage(1)}
                >
                  1
                </button>
                <span class="page-dots">...</span>
                {#each [totalPages-4, totalPages-3, totalPages-2, totalPages-1, totalPages] as pageNum}
                  <button
                    class="page-number-btn"
                    class:active={currentPage === pageNum}
                    on:click={() => goToPage(pageNum)}
                  >
                    {pageNum}
                  </button>
                {/each}
              {:else}
                <!-- 현재 페이지가 중간에 있을 때: 1 ... 7,8,9,10,11 ... 14 -->
                <button
                  class="page-number-btn"
                  on:click={() => goToPage(1)}
                >
                  1
                </button>
                <span class="page-dots">...</span>
                {#each [currentPage-2, currentPage-1, currentPage, currentPage+1, currentPage+2] as pageNum}
                  <button
                    class="page-number-btn"
                    class:active={currentPage === pageNum}
                    on:click={() => goToPage(pageNum)}
                  >
                    {pageNum}
                  </button>
                {/each}
                <span class="page-dots">...</span>
                <button
                  class="page-number-btn"
                  on:click={() => goToPage(totalPages)}
                >
                  {totalPages}
                </button>
              {/if}
            {/if}

            <button
              class="page-number-btn prev-next-btn"
              on:click={() => goToPage(currentPage + 1)}
              disabled={currentPage >= totalPages}
            >
              <ChevronRightIcon />
            </button>
          </div>

          <!-- 모바일용 스마트 페이지네이션 -->
          <div class="pagination-mobile">
            <div class="page-nav-container">
              <button
                class="page-nav-btn prev-btn"
                on:click={() => goToPage(currentPage - 1)}
                disabled={currentPage <= 1}
              >
                <ChevronLeftIcon />
                {$t("pagination_prev")}
              </button>
              <button
                class="page-nav-btn next-btn"
                on:click={() => goToPage(currentPage + 1)}
                disabled={currentPage >= totalPages}
              >
                {$t("pagination_next")}
                <ChevronRightIcon />
              </button>
            </div>

            <div class="page-numbers-mobile">
              {#if totalPages <= 7}
                <!-- 총 페이지가 7개 이하면 모두 표시 -->
                {#each Array(totalPages) as _, i}
                  {@const pageNum = i + 1}
                  <button
                    class="page-number-btn-mobile"
                    class:active={currentPage === pageNum}
                    on:click={() => goToPage(pageNum)}
                  >
                    {pageNum}
                  </button>
                {/each}
              {:else}
                <!-- 복잡한 페이지네이션 로직 -->
                {#if currentPage <= 4}
                  <!-- 현재 페이지가 앞쪽에 있을 때: 1,2,3,4,5 ... 14 -->
                  {#each [1,2,3,4,5] as pageNum}
                    <button
                      class="page-number-btn-mobile"
                      class:active={currentPage === pageNum}
                      on:click={() => goToPage(pageNum)}
                    >
                      {pageNum}
                    </button>
                  {/each}
                  <span class="page-dots-mobile">...</span>
                  <button
                    class="page-number-btn-mobile"
                    on:click={() => goToPage(totalPages)}
                  >
                    {totalPages}
                  </button>
                {:else if currentPage >= totalPages - 3}
                  <!-- 현재 페이지가 뒤쪽에 있을 때: 1 ... 10,11,12,13,14 -->
                  <button
                    class="page-number-btn-mobile"
                    on:click={() => goToPage(1)}
                  >
                    1
                  </button>
                  <span class="page-dots-mobile">...</span>
                  {#each [totalPages-4, totalPages-3, totalPages-2, totalPages-1, totalPages] as pageNum}
                    <button
                      class="page-number-btn-mobile"
                      class:active={currentPage === pageNum}
                      on:click={() => goToPage(pageNum)}
                    >
                      {pageNum}
                    </button>
                  {/each}
                {:else}
                  <!-- 현재 페이지가 중간에 있을 때: 1 ... 7,8,9,10,11 ... 14 -->
                  <button
                    class="page-number-btn-mobile"
                    on:click={() => goToPage(1)}
                  >
                    1
                  </button>
                  <span class="page-dots-mobile">...</span>
                  {#each [currentPage-2, currentPage-1, currentPage, currentPage+1, currentPage+2] as pageNum}
                    <button
                      class="page-number-btn-mobile"
                      class:active={currentPage === pageNum}
                      on:click={() => goToPage(pageNum)}
                    >
                      {pageNum}
                    </button>
                  {/each}
                  <span class="page-dots-mobile">...</span>
                  <button
                    class="page-number-btn-mobile"
                    on:click={() => goToPage(totalPages)}
                  >
                    {totalPages}
                  </button>
                {/if}
              {/if}
            </div>
          </div>
        </div>
      {/if}
      </div>
    </div>
  {/if}

  {#if !$isLoading}
    <SettingsModal
      showModal={showSettingsModal}
      {currentSettings}
      {dashboardStats}
      summaryTotal={dashboardSummaryTotal}
      summarySuccessRate={dashboardSummarySuccessRate}
      summaryWorking={workingCount}
      summaryBytes={dashboardSummaryBytes}
      bind:statsPeriod={dashboardPeriod}
      bind:statsStartDate={dashboardStartDate}
      bind:statsEndDate={dashboardEndDate}
      on:settingsChanged={handleSettingsChanged}
      on:proxyChanged={checkProxyAvailability}
      on:statsPeriodChange={() => { fetchDashboardStats(); fetchDashboardHistory(); }}
      on:close={() => (showSettingsModal = false)}
    />
  {/if}

  {#if showPasswordModal && !$isLoading}
    <PasswordModal
      bind:showModal={showPasswordModal}
      on:passwordSet={handlePasswordSet}
      on:close={() => (showPasswordModal = false)}
    />
  {/if}

  {#if showDetailModal && !$isLoading}
    <DetailModal
      bind:showModal={showDetailModal}
      download={selectedDownload}
      on:close={() => (showDetailModal = false)}
    />
  {/if}

  {#if selectMode && selectedIds.size > 0}
    <div class="bulk-action-bar">
      <span class="bulk-count">{$t("select_count", { count: selectedIds.size })}</span>
      <div class="bulk-actions">
        <button class="button button-secondary" on:click={auditSelected}>
          {$t("bulk_action_audit")}
        </button>
        <button class="button button-danger" on:click={bulkDeleteSelected}>
          {$t("bulk_action_delete")}
        </button>
        <button class="button button-secondary" on:click={exitSelectMode}>
          {$t("select_mode_exit")}
        </button>
      </div>
    </div>
  {/if}

  {#if !$isLoading}
    <ConfirmModal
      bind:showModal={showConfirm}
      message={confirmMessage}
      title={confirmTitle}
      icon={confirmIcon}
      confirmText={confirmButtonText}
      cancelText={cancelButtonText}
      on:confirm={confirmAction}
    />

    <AuditModal
      bind:showModal={showAuditModal}
      on:start={(e) => startAudit(e.detail)}
    />

    <ConfirmModal
      bind:showModal={showBulkDeleteConfirm}
      title={$t("bulk_action_delete")}
      message={$t("bulk_delete_confirm", { count: pendingBulkDelete.length })}
      confirmText={$t("bulk_action_delete")}
      isDeleteAction={true}
      on:confirm={performBulkDelete}
    />
  {/if}
</main>

<Toaster
  richColors
  position="bottom-center"
  expand={true}
  visibleToasts={3}
  closeButton={false}
  duration={3000}
  theme={$theme === 'light' ? 'light' : 'dark'}
  toastOptions={{
    class: `toast-${$theme}`,
    style: 'background: var(--card-background); color: var(--text-primary); border: 1px solid var(--card-border);'
  }}
/>
