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
    fetchAvailableLanguages,
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
  import Checkbox from "./lib/Checkbox.svelte";

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

  // Server-side pagination model:
  //   - gridDownloads: the items currently rendered in the grid (one server page).
  //   - activeDownloads: the small live list (in-progress only) powering gauges
  //     and proxy/local stats.
  // There is no single "all downloads" array on the client anymore.
  let gridDownloads = [];
  let activeDownloads = [];
  let url = "";
  let password = "";
  let eventSourceManager;
  let currentPage = 1;
  let totalPages = 1;
  let itemsPerPage = 10; // Default; changes dynamically with screen size
  let isDownloadsLoading = false;
  let isAddingDownload = false;
  // Server-reported total count for the currently active tab — used by
  // pagination text and the dashboard fallback.
  let currentTabTotalCount = 0;

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

  // Link audit progress state — referenced by the header button/toasts.
  let auditRunning = false;
  let auditDone = 0;
  let auditTotal = 0;
  let showAuditModal = false;
  // Rows currently being audited — used to show a per-row loading spinner.
  let auditingIds = new Set();
  // Multi-select — checkboxes are always visible in the leading table column.
  let selectedIds = new Set();
  let showBulkDeleteConfirm = false;
  let pendingBulkDelete = []; // Used by the confirm modal

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

  // Timer for debouncing
  let activeDownloadsTimer = null;
  // Tab badge counts come from the server (/api/history/stats), not from a local sweep.
  let workingCount = 0;
  let completedCount = 0;
  // Debounce timer for the grid fetch (currentTab/page/search/period change).
  let _gridFetchTimer = null;
  // First-pending timestamp for the grid fetch, so a continuous event storm
  // can't postpone the fetch forever AND can't fire more than once per maxWait.
  let _gridFetchFirstPending = 0;
  // Debounce timer for the tab count fetch.
  let _tabCountsFetchTimer = null;
  // Hard floor between grid reloads — a safety net so nothing (duplicate events,
  // fail-cycling, a missed guard) can ever reload the visible list faster than
  // this. 150ms debounce still coalesces normal bursts; this just caps the worst
  // case so the page can never visibly jerk multiple times a second.
  const GRID_FETCH_MAX_WAIT_MS = 2000;

  // Batch SSE updates (requestAnimationFrame) — defer state assignment to the next frame
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

  // Timer for real-time wait-time updates
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
  // Removed dashboardExpanded — the dashboard is always shown.
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

    // Always load the language list so the settings dropdown is populated, even
    // for returning users who skip initializeLocale (fire-and-forget).
    fetchAvailableLanguages();

    // Load translations (UI text) first so the app shell renders promptly.
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

    // Connect EventSource only when login is not required or already authenticated
    if (!$needsLogin || $isAuthenticated) {
      fetchGridPage();
      fetchTabCounts();
      fetchActiveDownloads();
      connectEventSource();
      fetchProxyStatus();
      checkProxyAvailability();

      // Dashboard stats/history load via the debounced reactive
      // (scheduleDashboardFetch), so they are NOT fetched explicitly here —
      // that avoids duplicate history requests on load.
      fetchSystemStats();
      if (!systemStatsInterval) {
        systemStatsInterval = setInterval(fetchSystemStats, 5000);
      }
    }

    // Start the real-time wait-time update timer
    function startWaitTimeUpdateTimer() {
      waitTimeUpdateTimer = setInterval(() => {
        currentTime = Date.now();
      }, 1000);
    }
    startWaitTimeUpdateTimer();

    // Add the proxy-refresh event listener
    const handleProxyRefresh = () => {
      fetchProxyStatus();
      checkProxyAvailability();
    };
    document.addEventListener("proxy-refreshed", handleProxyRefresh);

    // Add the window resize event listener
    window.addEventListener("resize", handleResize);

    // Quiet-update logic when the page returns from background on mobile
    let lastVisibilityTime = Date.now();
    const handleVisibilityChange = () => {
      if (!document.hidden) {
        const now = Date.now();
        const timeSinceLastVisible = now - lastVisibilityTime;

        // Update if it was in the background for more than 5 seconds
        if (timeSinceLastVisible > 5000) {
          syncDownloadsSilently();

          // Reconnect EventSource (the connection may have dropped)
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

    // Add the table column resize feature
    const cleanupResize = initTableColumnResize();

    // Register the cleanup function with onDestroy
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

    // Mouse-down event (start of resize)
    function handleMouseDown(e) {
      // Check whether it is in the table header's :after pseudo-element area
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

    // Mouse-move event (during resize)
    function handleMouseMove(e) {
      if (!isResizing || !currentColumn) {
        // Change the cursor when not resizing
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

      // Set the header itself
      currentColumn.style.width = newWidth + "px";
      currentColumn.style.minWidth = newWidth + "px";
      currentColumn.style.maxWidth = newWidth + "px";

      // Apply the same width to every td in the same column
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

    // Mouse-up event (end of resize)
    function handleMouseUp() {
      if (isResizing) {
        isResizing = false;
        currentColumn = null;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    }

    // Register event listeners
    document.addEventListener("mousedown", handleMouseDown);
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    // Return the cleanup function (used when the component is destroyed)
    return () => {
      document.removeEventListener("mousedown", handleMouseDown);
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }

  onDestroy(() => {
    // Clean up EventSource
    if (eventSourceManager) {
      eventSourceManager.disconnect();
    }

    // Clean up timers
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
    // After successful login, load the needed data and connect EventSource
    fetchGridPage();
    fetchTabCounts();
    fetchActiveDownloads();
    connectEventSource();
    fetchProxyStatus();
    checkProxyAvailability();

    // System monitoring was gated behind auth in onMount, so a first-time login
    // (no token yet at mount) never started it — the usage skeleton stayed until
    // a manual refresh. Kick it off (and its interval) here too.
    fetchSystemStats();
    if (!systemStatsInterval) {
      systemStatsInterval = setInterval(fetchSystemStats, 5000);
    }
  }

  function handleResetProxyStatus() {
    // Reset the proxy status to idle
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
    // Use the LOCAL date, not toISOString() (UTC). requested_at is stored in
    // local time, so a UTC date made "today" resolve to yesterday during the
    // local morning (e.g. KST 00:00–09:00), surfacing yesterday's items.
    const fmt = (d) => {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      return `${y}-${m}-${dd}`;
    };
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

  // Debounced dashboard fetch. Two components are bound to dashboardPeriod, so on
  // mount the value can change several times as they initialize — without debounce
  // each change re-fired stats+history for a different range, flooding the backend.
  let _dashboardFetchTimer = null;
  function scheduleDashboardFetch() {
    if (_dashboardFetchTimer) clearTimeout(_dashboardFetchTimer);
    _dashboardFetchTimer = setTimeout(() => {
      fetchDashboardStats();
      fetchDashboardHistory();
    }, 150);
  }

  // Re-fetch when the period or the custom date range changes (coalesced).
  $: {
    dashboardPeriod;
    dashboardStartDate;
    dashboardEndDate;
    dashboardCurrentPage;
    if (dashboardPeriod) scheduleDashboardFetch();
  }

  // Status considered "active" (lives in the activeDownloads list).
  // Matches the backend /downloads/active filter (parsing/downloading/waiting/failed/pending).
  function isActiveStatus(status) {
    const s = (status || "").toLowerCase();
    return (
      s === "pending" ||
      s === "parsing" ||
      s === "proxying" ||
      s === "downloading" ||
      s === "waiting" ||
      s === "failed"
    );
  }

  // "done" sits in the completed tab; everything else (active/failed/stopped) is "working".
  function isCompletedStatus(status) {
    return (status || "").toLowerCase() === "done";
  }

  function connectEventSource() {
    if (!eventSourceManager) {
      eventSourceManager = new EventSourceManager();
    }

    eventSourceManager.connect((message) => {

      if (message.type === "status_update") {
        const updatedDownload = message.data;
        // Reflect the failure message in the UI immediately (the backend sends it as message)
        if (
          updatedDownload?.status?.toLowerCase?.() === "failed" &&
          updatedDownload?.message &&
          !updatedDownload.error_message
        ) {
          updatedDownload.error_message = updatedDownload.message;
        }
        // Normalize the ID type (convert to number)
        const downloadId = Number.parseInt(updatedDownload.id, 10);
        if (!downloadId || Number.isNaN(downloadId)) {
          console.warn("❌ 잘못된 다운로드 데이터 무시:", updatedDownload);
          return;
        }

        // Batch the state assignment against the latest snapshots at queue-run time.
        queueStateUpdate(() => {
          let proxyStatsChanged = false;

          // Patch the row in the grid (if it is on the currently-visible page).
          const gridIndex = gridDownloads.findIndex(
            (d) => Number.parseInt(d.id, 10) === downloadId,
          );
          // Pre-patch status, so we can tell an in-place sub-status change
          // (e.g. downloading→stopped, still in the working tab) from a real
          // working↔completed tab crossing (see the refetch guard below).
          const prevGridStatus =
            gridIndex !== -1 ? gridDownloads[gridIndex].status : null;
          if (gridIndex !== -1) {
            gridDownloads = gridDownloads.map((d, i) =>
              i === gridIndex ? { ...d, ...updatedDownload } : d,
            );
          }

          // Patch / add / remove the row in the active list.
          const activeIndex = activeDownloads.findIndex(
            (d) => Number.parseInt(d.id, 10) === downloadId,
          );
          const prevActiveStatus =
            activeIndex !== -1 ? activeDownloads[activeIndex].status : null;
          const stillActive = isActiveStatus(updatedDownload.status);

          if (activeIndex !== -1) {
            // Handle proxy-status reset when an active proxy item leaves the active set.
            if (
              proxyStats.status === "trying" &&
              ["stopped", "failed", "done"].includes(
                updatedDownload.status?.toLowerCase(),
              )
            ) {
              const otherProxyDownloads = activeDownloads.filter(
                (d) =>
                  Number.parseInt(d.id, 10) !== downloadId &&
                  (d.status === "parsing" || d.status === "downloading"),
              );

              if (otherProxyDownloads.length === 0) {
                proxyStats.status = "idle";
                proxyStats.currentProxy = null;
                proxyStats.tryStartTime = null;
                proxyStatsChanged = true;
                console.log(
                  `🔄 다운로드 ${downloadId} 상태 변경으로 인한 프록시 상태 리셋`,
                );
              }
            }

            if (stillActive) {
              activeDownloads = activeDownloads.map((d, i) =>
                i === activeIndex ? { ...d, ...updatedDownload } : d,
              );
            } else {
              activeDownloads = activeDownloads.filter(
                (_, i) => i !== activeIndex,
              );
            }
            updateStats(activeDownloads);
          } else if (stillActive) {
            // The item just became active from off-page — resync the live list rather than guess.
            fetchActiveDownloads();
          }

          // Only clear the wait countdown when the download genuinely leaves the wait
          // (started downloading / finished / failed / stopped). A stray "parsing" /
          // "proxying" status_update mid-wait must NOT wipe an active countdown.
          if (
            ["downloading", "done", "failed", "stopped"].includes(
              (updatedDownload.status || "").toLowerCase(),
            ) &&
            downloadWaitInfo[downloadId]
          ) {
            delete downloadWaitInfo[downloadId];
            downloadWaitInfo = { ...downloadWaitInfo };
          }

          // Refetch the grid ONLY when an item actually crosses the
          // working↔completed tab boundary (which changes which tab it belongs
          // to), or when it isn't on the visible page at all (a new/off-page item
          // that may now belong here). A sub-status change that stays within the
          // working tab (downloading→stopped/paused/failed, or a progress tick) is
          // already reflected by the in-place patch above — refetching the whole
          // grid there replaced the entire list and made it visibly jerk on every
          // stop/pause press and on each progress update.
          const prevStatus = prevGridStatus ?? prevActiveStatus;
          const crossedTabBoundary =
            prevStatus != null &&
            isCompletedStatus(prevStatus) !== isCompletedStatus(updatedDownload.status);
          // An off-grid item we've never seen (prevStatus null) only deserves a
          // grid pull if it's actually arriving — an *incoming* status (pending/
          // parsing/downloading/...). A terminal status (failed/stopped/done) for
          // an unknown id is a duplicate or late event for something off-page, and
          // firing on it caused a per-second grid reload during fail-cycling
          // (DataNodes node outage → many parse→download→failed in a row, plus
          // duplicate failed events). Those must NOT refetch.
          const newStatus = (updatedDownload.status || "").toLowerCase();
          const isIncoming =
            newStatus === "pending" || newStatus === "parsing" ||
            newStatus === "proxying" || newStatus === "downloading" ||
            newStatus === "waiting";
          const isNewIncoming = gridIndex === -1 && prevStatus == null && isIncoming;
          if (crossedTabBoundary || isNewIncoming) {
            scheduleGridFetch();
            scheduleTabCountsFetch();
          }

          if (proxyStatsChanged) {
            proxyStats = { ...proxyStats };
          }
        });
      }

      // Handle batch updates
      if (message.type === "batch_status_update") {
        queueStateUpdate(() => {
          let gridChanged = false;
          let activeChanged = false;
          let proxyStatsChanged = false;
          let crossedTabBoundary = false;
          const nextGrid = [...gridDownloads];
          let nextActive = [...activeDownloads];

          message.data.forEach((updatedDownload) => {
            // Also map the failure message to error_message
            if (
              updatedDownload?.status?.toLowerCase?.() === "failed" &&
              updatedDownload?.message &&
              !updatedDownload.error_message
            ) {
              updatedDownload.error_message = updatedDownload.message;
            }

            // Patch the grid in place when the row is currently visible.
            const gridIdx = nextGrid.findIndex((d) => d.id === updatedDownload.id);
            if (gridIdx !== -1) {
              const oldStatus = nextGrid[gridIdx].status;
              nextGrid[gridIdx] = { ...nextGrid[gridIdx], ...updatedDownload };
              gridChanged = true;
              if (
                isCompletedStatus(oldStatus) !==
                isCompletedStatus(updatedDownload.status)
              ) {
                crossedTabBoundary = true;
              }
            } else {
              // Off-page row: only force a grid refetch if it actually crossed the
              // working↔completed boundary (detected from its active-list status)
              // or it's newly arriving with an incoming status (surface it). A
              // known off-page item ticking progress, or a terminal/duplicate
              // event for an unknown id, must NOT refetch — that reloaded the whole
              // grid on every batch and made the list jerk.
              const activeOld = nextActive.find((d) => d.id === updatedDownload.id);
              const s = (updatedDownload.status || "").toLowerCase();
              const incoming =
                s === "pending" || s === "parsing" || s === "proxying" ||
                s === "downloading" || s === "waiting";
              if (activeOld == null) {
                if (incoming) crossedTabBoundary = true;
              } else if (
                isCompletedStatus(activeOld.status) !== isCompletedStatus(s)
              ) {
                crossedTabBoundary = true;
              }
            }

            // Patch / remove the row in the active list.
            const activeIdx = nextActive.findIndex(
              (d) => d.id === updatedDownload.id,
            );
            const stillActive = isActiveStatus(updatedDownload.status);
            if (activeIdx !== -1) {
              const oldDownload = nextActive[activeIdx];

              // When a proxy download leaves the active set, maybe reset proxy state.
              if (
                oldDownload.use_proxy &&
                oldDownload.status !== updatedDownload.status &&
                ["stopped", "failed", "done"].includes(
                  updatedDownload.status?.toLowerCase(),
                )
              ) {
                const otherActiveProxyDownloads = nextActive.filter(
                  (d) =>
                    d.use_proxy &&
                    d.id !== updatedDownload.id &&
                    ["pending", "proxying", "parsing", "downloading"].includes(
                      d.status?.toLowerCase(),
                    ),
                );

                if (otherActiveProxyDownloads.length === 0) {
                  proxyStats.status = "";
                  proxyStats.currentProxy = "";
                  proxyStats.currentStep = "";
                  proxyStats.currentIndex = 0;
                  proxyStats.totalAttempting = 0;
                  proxyStatsChanged = true;
                  console.log(`[LOG] 마지막 프록시 다운로드 종료, 프록시 상태 초기화`);
                } else {
                  console.log(
                    `[LOG] 다른 프록시 다운로드 진행 중 (${otherActiveProxyDownloads.length}개), 프록시 상태 유지`,
                  );
                }
              }

              if (stillActive) {
                nextActive[activeIdx] = { ...oldDownload, ...updatedDownload };
              } else {
                nextActive = nextActive.filter((_, i) => i !== activeIdx);
              }
              activeChanged = true;
            } else if (stillActive) {
              // New active item — schedule a resync to pick it up authoritatively.
              crossedTabBoundary = true;
            }
          });

          if (gridChanged) {
            gridDownloads = nextGrid;
          }
          if (activeChanged) {
            activeDownloads = nextActive;
            updateStats(activeDownloads);
          }
          if (proxyStatsChanged) {
            proxyStats = { ...proxyStats };
          }
          if (crossedTabBoundary) {
            scheduleGridFetch();
            scheduleTabCountsFetch();
            // Also resync the active list when items appeared/disappeared off-grid.
            fetchActiveDownloads();
          }
        });
      }

      // Handle proxy messages
      if (message.type === "proxy_trying") {
        const { id, proxy, step, current, total, failed } = message.data;
        console.log(`[DEBUG] SSE proxy_trying 수신:`, message.data);
        proxyStats.currentProxy = proxy;
        proxyStats.currentStep = step;
        proxyStats.currentIndex = current;
        proxyStats.totalAttempting = total;
        // totalProxies is the total number of proxies, so do not change it (total is the size of the current batch)
        // Along with the real-time fail-count update, also decrement available proxies (1-second debounce)
        const prevFailCount = proxyStats.failCount || 0;
        const newFailCount = failed || 0;
        const failedDiff = newFailCount - prevFailCount;

        console.log(`[DEBUG] proxy_trying - 이전: ${prevFailCount}, 현재: ${newFailCount}, 차이: ${failedDiff}, 현재 잔여: ${proxyStats.availableProxies}`);

        proxyStats.failCount = newFailCount;

        // As the fail count increases, immediately decrement available proxies too
        if (failedDiff > 0 && proxyStats.availableProxies > 0) {
          const beforeAvailable = proxyStats.availableProxies;
          proxyStats.availableProxies = Math.max(0, proxyStats.availableProxies - failedDiff);
          console.log(`[DEBUG] 프록시 즉시 차감: ${failedDiff}개, ${beforeAvailable} -> ${proxyStats.availableProxies}`);
        }
        proxyStats.status = "trying";

        // Batch the state assignment
        queueStateUpdate(() => {
          proxyStats = { ...proxyStats };
          // Also update that download's status in the main grid (so it is not missed)
          if (id) {
            const failedText = failed > 0 ? $t("proxy_failed_count_suffix", { count: failed }) : '';
            const proxyMessage = `${step} - ${proxy} (${current}/${total})${failedText}`;
            gridDownloads = gridDownloads.map((d) =>
              d.id === id ? { ...d, proxy_message: proxyMessage } : d,
            );
            activeDownloads = activeDownloads.map((d) =>
              d.id === id ? { ...d, proxy_message: proxyMessage } : d,
            );

            // Remove the wait info once the proxy task starts
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

        // Batch the state assignment
        queueStateUpdate(() => {
          proxyStats = { ...proxyStats };

          // Also update that download's status in the main grid
          if (id) {
            const proxyMessage = `${proxy} - ${msg || step}`;
            gridDownloads = gridDownloads.map((d) =>
              d.id === id ? { ...d, proxy_message: proxyMessage } : d,
            );
            activeDownloads = activeDownloads.map((d) =>
              d.id === id ? { ...d, proxy_message: proxyMessage } : d,
            );
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

        // Batch the state assignment
        queueStateUpdate(() => {
          proxyStats = { ...proxyStats };

          // Also update that download's status in the main grid
          if (id) {
            const proxyMessage = msg || step;
            gridDownloads = gridDownloads.map((d) =>
              d.id === id ? { ...d, proxy_message: proxyMessage } : d,
            );
            activeDownloads = activeDownloads.map((d) =>
              d.id === id ? { ...d, proxy_message: proxyMessage } : d,
            );
          }
        });
      }

      // Handle proxy-status reset
      if (message.type === "proxy_reset") {
        console.log("🔄 프록시 상태 초기화 메시지 수신:", message.data);
        proxyStats.status = "";
        proxyStats.currentProxy = "";
        proxyStats.currentStep = "";
        proxyStats.currentIndex = 0;
        proxyStats.totalAttempting = 0;
        // Batch the state assignment
        queueStateUpdate(() => {
          proxyStats = { ...proxyStats };
        });
        console.log("[LOG] 프록시 상태 강제 초기화 완료");
      }

      // Handle the 1fichier wait time (waiting after parsing).
      // The backend sends status="waiting" once separately via status_update.
      // Here we update only the countdown data (downloadWaitInfo) to prevent a race
      // (the problem where status gets force-overwritten when status_update and
      // waiting messages interleave).
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

      // Handle wait completion
      if (message.type === "wait_countdown_complete") {
        const { id } = message.data;
        delete downloadWaitInfo[id];
        queueStateUpdate(() => {
          downloadWaitInfo = { ...downloadWaitInfo };
        });
      }

      // Remove the wait info when a download is stopped
      if (message.type === "download_stopped") {
        const { id } = message.data;
        const waitInfoExists = !!downloadWaitInfo[id];
        let proxyStatsChanged = false;
        if (waitInfoExists) {
          delete downloadWaitInfo[id];
          console.log(`🛑 정지로 인한 대기 정보 제거: ${id}`);
        }

        // Reset the proxy status (only when no other download is using a proxy)
        if (proxyStats.status === "trying") {
          const otherProxyDownloads = activeDownloads.filter(d =>
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

      // Handle filename updates
      if (message.type === "filename_update") {
        console.log("📁 filename_update 메시지 수신:", message.data);
        const { id, filename, file_size } = message.data;
        queueStateUpdate(() => {
          gridDownloads = gridDownloads.map((d) =>
            d.id === id
              ? {
                  ...d,
                  filename: filename || d.filename,
                  file_size: file_size || d.file_size,
                }
              : d,
          );
          activeDownloads = activeDownloads.map((d) =>
            d.id === id
              ? {
                  ...d,
                  filename: filename || d.filename,
                  file_size: file_size || d.file_size,
                }
              : d,
          );
        });
      }

      // Handle SSE test messages
      if (message.type === "test_message") {
        console.log("🧪 SSE 테스트 메시지 수신:", message.data);
        alert($t("sse_connection_normal") + ": " + message.data.message);
      }

      if (message.type === "force_refresh") {
        console.log("🔄 Force refresh 요청 수신:", message.data);
        // Reload the visible page + live list + tab counts.
        fetchGridPage();
        fetchActiveDownloads();
        fetchTabCounts();
      }

      // Single probe result — just a light row update.
      if (message.type === "probe_result") {
        const { id, failure_kind, next_retry_at, kind, summary } = message.data;
        queueStateUpdate(() => {
          gridDownloads = gridDownloads.map((d) =>
            d.id === id ? { ...d, failure_kind, next_retry_at } : d,
          );
          activeDownloads = activeDownloads.map((d) =>
            d.id === id ? { ...d, failure_kind, next_retry_at } : d,
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

      // Batch audit progress — toasts for the start/step/done stages.
      if (message.type === "audit_progress") {
        const { status, done, total, counts, item } = message.data;
        if (status === "start") {
          auditTotal = total;
          auditDone = 0;
          auditRunning = true;
          toast.info($t("audit_started", { total }));
        } else if (status === "step") {
          auditDone = done;
          auditTotal = total;
          // Update the audited row in place and clear its spinner — no full reload.
          if (item && item.id != null) {
            queueStateUpdate(() => {
              gridDownloads = gridDownloads.map((d) =>
                d.id === item.id
                  ? { ...d, failure_kind: item.failure_kind, next_retry_at: item.next_retry_at }
                  : d,
              );
              activeDownloads = activeDownloads.map((d) =>
                d.id === item.id
                  ? { ...d, failure_kind: item.failure_kind, next_retry_at: item.next_retry_at }
                  : d,
              );
            });
            if (auditingIds.has(item.id)) {
              auditingIds.delete(item.id);
              auditingIds = new Set(auditingIds);
            }
          }
        } else if (status === "done") {
          auditRunning = false;
          auditDone = done;
          auditingIds = new Set(); // clear any remaining spinners
          const alive = counts?.alive ?? 0;
          const dead = counts?.dead ?? 0;
          const other = total - alive - dead;
          toast.success($t("audit_done", { alive, dead, other }));
        }
      }
    });
  }

  function reconnectEventSource() {
    if (eventSourceManager) {
      eventSourceManager.reconnect();
    }
  }

  // Quiet background sync (no flicker) — re-fetch the visible grid page and
  // the live active list. No client-side "all rows" array anymore.
  async function syncDownloadsSilently() {
    await Promise.all([
      fetchGridPage({ silent: true }),
      fetchActiveDownloads(),
      fetchTabCounts(),
    ]);

    // Clean up wait info for items that finished while we were away.
    Object.keys(downloadWaitInfo).forEach((downloadId) => {
      const id = parseInt(downloadId);
      const stillActive = activeDownloads.find((d) => d.id === id);
      if (!stillActive) {
        delete downloadWaitInfo[downloadId];
      }
    });
    downloadWaitInfo = { ...downloadWaitInfo };
  }

  // Fetch one page of the grid for the current tab, search, and period range.
  // `{ silent: true }` skips the loading skeleton — used by background syncs.
  async function fetchGridPage({ silent = false } = {}) {
    if (!silent) {
      isDownloadsLoading = true;
    }

    const endpoint =
      currentTab === "completed"
        ? "/api/downloads/completed"
        : "/api/downloads/working";
    const params = new URLSearchParams();
    params.set("page", String(currentPage));
    params.set("page_size", String(itemsPerPage));
    if (searchQuery && searchQuery.trim()) {
      params.set("search", searchQuery.trim());
    }
    const { start, end } = getDashboardDateRange();
    if (start) params.set("start_date", start);
    if (end) params.set("end_date", end);

    try {
      const response = await fetch(`${endpoint}?${params.toString()}`);
      if (response.ok) {
        const data = await response.json();
        gridDownloads = Array.isArray(data.downloads) ? data.downloads : [];
        totalPages = data.total_pages || 0;
        currentTabTotalCount = data.total_count || 0;
        // Server is authoritative for totalPages; snap back if currentPage is now stale.
        if (currentPage > totalPages && totalPages > 0) {
          currentPage = totalPages;
        }
      } else {
        console.error("Grid fetch failed with status:", response.status);
        gridDownloads = [];
        totalPages = 0;
        currentTabTotalCount = 0;
      }
    } catch (error) {
      console.error("Error fetching grid page:", error);
      gridDownloads = [];
      totalPages = 0;
      currentTabTotalCount = 0;
    } finally {
      if (!silent) {
        isDownloadsLoading = false;
      }
    }
  }

  // Coalesce rapid changes (tab/page/search/period/SSE) into one fetch. Debounces
  // 150ms after the last request, but never waits longer than GRID_FETCH_MAX_WAIT_MS
  // from the first pending request — so a continuous event storm both can't starve
  // the fetch and can't reload the list more than once per maxWait window.
  function scheduleGridFetch() {
    const now = Date.now();
    if (!_gridFetchFirstPending) _gridFetchFirstPending = now;
    const elapsed = now - _gridFetchFirstPending;
    const delay = Math.max(0, Math.min(150, GRID_FETCH_MAX_WAIT_MS - elapsed));
    if (_gridFetchTimer) clearTimeout(_gridFetchTimer);
    _gridFetchTimer = setTimeout(() => {
      _gridFetchFirstPending = 0;
      fetchGridPage();
    }, delay);
  }

  // Fetch the small live list (in-progress items) for gauges + proxy/local stats.
  async function fetchActiveDownloads() {
    try {
      const response = await fetch("/api/downloads/active");
      if (response.ok) {
        const data = await response.json();
        activeDownloads = Array.isArray(data.downloads) ? data.downloads : [];
        updateStats(activeDownloads);
      }
    } catch (error) {
      console.error("Error fetching active downloads:", error);
    }
  }

  // Pull both tab badge counts in a single request — /history/stats already
  // exposes status_counts and honors the period range.
  async function fetchTabCounts() {
    const params = new URLSearchParams();
    const { start, end } = getDashboardDateRange();
    if (start) params.set("start_date", start);
    if (end) params.set("end_date", end);

    const qs = params.toString();
    const url = qs ? `/api/history/stats?${qs}` : "/api/history/stats";

    try {
      const response = await fetch(url);
      if (response.ok) {
        const data = await response.json();
        const statusCounts = data.by_status || {};
        const done = statusCounts.done || 0;
        let working = 0;
        for (const [key, value] of Object.entries(statusCounts)) {
          if (key !== "done") working += value || 0;
        }
        workingCount = working;
        completedCount = done;
      }
    } catch (error) {
      console.error("Error fetching tab counts:", error);
    }
  }

  function scheduleTabCountsFetch() {
    if (_tabCountsFetchTimer) clearTimeout(_tabCountsFetchTimer);
    _tabCountsFetchTimer = setTimeout(() => {
      fetchTabCounts();
    }, 150);
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

  // Flag for global debouncing
  let needsActiveDownloadsUpdate = false;
  let activeDownloadsInterval = null;

  // Interval that calls fetchActiveDownloads periodically (every 5 seconds - performance optimization)
  onMount(() => {
    activeDownloadsInterval = setInterval(() => {
      if (needsActiveDownloadsUpdate) {
        fetchActiveDownloads();
        needsActiveDownloadsUpdate = false;
      }
    }, 5000);
  });


  // Unified stats-update function
  function updateStats(downloadsData) {
    updateProxyStats(downloadsData);
    updateLocalStats(downloadsData);

    // Just set a flag instead of debouncing
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
      // Check only states that are actually in progress: pending, parsing, etc.
      const activeStatusDownloads = activeLocalDownloads.filter(d => {
        const status = d.status?.toLowerCase() || "";
        return ["pending", "parsing"].includes(status);
      });

      if (activeStatusDownloads.length > 0) {
        localStats.localStatus = "waiting";
      } else {
        // failed, stopped, etc. are not in progress, so idle
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
    
    // Perform only basic URL validation (validate-url API removed)
    
    isAddingDownload = true;
    try {
      const response = await fetch("/api/download/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, password, use_proxy: useProxy }),
      });
      if (response.ok) {
        const newDownload = await response.json();
        if (newDownload.already_completed) {
          // Same file was already downloaded and is still on disk — quietly say
          // so instead of starting a redundant download.
          toast.info($t(newDownload.message_key, newDownload.message_args));
        } else if (newDownload.status === "waiting" && newDownload.message_key) {
          toast.info($t(newDownload.message_key, newDownload.message_args));
        } else if (!isAutoDownload) {
          toast.success($t("download_added_successfully"));
        }
        url = "";
        password = "";
        hasPassword = false;
        // Refresh the list immediately — visible page, live list, and badge counts.
        fetchGridPage();
        fetchActiveDownloads();
        fetchTabCounts();
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

  async function startAudit(payload = null) {
    // If called without a payload, open the modal — on header-button click.
    if (payload === null) {
      if (auditRunning) {
        toast.warning($t("audit_already_running"));
        return;
      }
      showAuditModal = true;
      return;
    }

    // Send exactly the payload received from the modal's 'start' event.
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
      // If started=true, an SSE audit_progress(start) arrives shortly and shows a toast.
    } catch (e) {
      console.error("audit 시작 실패:", e);
      toast.error(`audit error: ${e.message}`);
    }
  }

  function auditSelected() {
    if (selectedIds.size === 0) return;
    const ids = Array.from(selectedIds);
    // Mark these rows as auditing so each shows a loading spinner until its
    // result arrives via the audit_progress 'step' SSE.
    auditingIds = new Set(ids);
    startAudit({ ids });
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
      // Refresh visible grid + live list + tab counts.
      fetchGridPage();
      fetchActiveDownloads();
      fetchTabCounts();
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

  function clearSelection() {
    selectedIds = new Set();
  }

  // Select-all toggles every currently-rendered row. When all visible rows are
  // already selected it clears them, otherwise it selects them all.
  function toggleSelectAll(rows) {
    const ids = (Array.isArray(rows) ? rows : []).map((d) => d.id);
    const allSelected = ids.length > 0 && ids.every((id) => selectedIds.has(id));
    if (allSelected) {
      const next = new Set(selectedIds);
      ids.forEach((id) => next.delete(id));
      selectedIds = next;
    } else {
      selectedIds = new Set([...selectedIds, ...ids]);
    }
  }

  async function callApi(endpoint, downloadId = null) {
    try {
      const response = await fetch(endpoint, { method: "POST" });
      
      if (response.ok) {
        const responseData = await response.json();

        // Handle the waiting-status message
        if (responseData.status === "waiting" && responseData.message_key) {
          toast.info($t(responseData.message_key, responseData.message_args));
          return;
        }

        // Show the success message
        const action = endpoint.includes("/start/") ? "download" :
                     endpoint.includes("/pause/") ? "pause" :
                     endpoint.includes("/resume/") ? "resume" :
                     endpoint.includes("/retry/") ? "retry" :
                     endpoint.includes("/stop/") ? "stop" : "download";

        const messageKey = `${action}_request_sent`;
        toast.success($t(messageKey));
        
        console.log(`API 호출 성공: ${endpoint}`);
      } else {
        // Branch the retry-blocked reason into a separate message (permanent failure / login required)
        if (response.status === 409 && endpoint.includes("/retry/")) {
          let detail = "";
          try {
            const data = await response.json();
            detail = data.detail || "";
          } catch (_) { /* Not JSON — use the fallback message */ }
          if (detail === "retry_blocked_dead") {
            toast.error($t("retry_blocked_dead"));
            return;
          }
          if (detail === "retry_blocked_auth_required") {
            toast.error($t("retry_blocked_auth_required"));
            return;
          }
        }

        // Show the error message
        const action = endpoint.includes("/stop/") ? $t("action_stop") :
                     endpoint.includes("/resume/") ? $t("action_resume_action") :
                     endpoint.includes("/retry/") ? $t("action_retry_action") : $t("action_work");

        toast.error($t("action_request_failed", { action }));
        console.error(`API 호출 실패: ${endpoint}, 상태: ${response.status}`);
      }
    } catch (error) {
      const action = endpoint.includes("/stop/") ? $t("action_stop") :
                   endpoint.includes("/resume/") ? $t("action_resume_action") :
                   endpoint.includes("/retry/") ? $t("action_retry_action") : $t("action_work");
      
      toast.error($t("request_processing_error", {action}));
      console.error(`Error calling ${endpoint}:`, error);
    }
    
    // SSE updates the status automatically, so no extra fetch is needed
  }

  async function deleteDownload(id) {
    // Validate the ID
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
            // Optimistically drop from both grid and active lists; refresh badge counts.
            gridDownloads = gridDownloads.filter((d) => d.id !== id);
            activeDownloads = activeDownloads.filter((d) => d.id !== id);
            scheduleTabCountsFetch();
            scheduleGridFetch();
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

  // Wait-time countdown formatting — always mm:ss.
  // Removes the inconsistency where the unit jumped at the 60-second boundary (60s → 1min → 59s).
  function formatWaitTime(seconds) {
    if (seconds == null || seconds < 0) return "0:00";
    const total = Math.max(0, Math.floor(seconds));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    // Long quota waits (1fichier free limit) can be hours — show H:MM:SS so the
    // countdown reads as a real recovery time instead of e.g. "240:30".
    if (h > 0) {
      return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
    }
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

  // A name like "1fichier:<id>" / "mega:<id>" is a temporary URL-derived
  // placeholder (the real name arrives after parsing/decryption), not a filename.
  function isPlaceholderName(name) {
    return !name || /^(1fichier|mega):/i.test(name.trim());
  }

  // What to show in the filename cell. When the real name hasn't been fetched
  // yet (placeholder like `1fichier:<id>`), reflect *why* via the download
  // status so "queued / fetching / failed / done-but-unresolved" are
  // distinguishable instead of a single ambiguous "없음".
  function displayFileName(download) {
    const name = download?.filename;
    if (name && !isPlaceholderName(name)) return name;
    const st = (download?.status || "").toLowerCase();
    if (st === "pending") return $t("file_name_queued");
    if (["parsing", "proxying", "downloading", "waiting"].includes(st))
      return $t("file_name_fetching");
    if (st === "failed" || st === "stopped") return $t("file_name_failed");
    if (st === "done") return $t("file_name_unresolved");
    // Unknown status — fall back to the id portion if present, else N/A.
    const m = (name || "").trim().match(/^(?:1fichier|mega):(.+)$/i);
    return m ? m[1] : $t("file_name_na");
  }

  // Tooltip: the real name, or the host:id when only a placeholder exists.
  function fileNameTitle(download) {
    const name = download?.filename;
    if (name && !isPlaceholderName(name)) return name;
    const m = (name || "").trim().match(/^(1fichier|mega):(.+)$/i);
    return m ? `${m[1]}: ${m[2]}` : displayFileName(download);
  }

  function getStatusTooltip(download) {
    const proxyInfo = downloadProxyInfo[download.id];

    // Check the 1fichier auto-retry state
    if (
      download.status.toLowerCase() === "pending" &&
      download.error_message &&
      download.error_message.includes($t("auto_retry_in_progress"))
    ) {
      return download.error_message + "\n" + $t("auto_retry_interval_notice");
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
      return Math.round(download.progress * 2) / 2; // Round to the nearest 0.5%
    }

    const downloaded = Number(
      download.downloaded_size ?? download.downloaded ?? 0
    );
    const total = Number(download.total_size ?? download.file_size ?? 0);
    if (total === 0 || download.status === "pending") return 0;
    if (download.status === "done") return 100;
    return Math.round((downloaded / total) * 100);
  }

  // URL validation function
  function isValidUrl(string) {
    try {
      const url = new URL(string);
      return url.protocol === "http:" || url.protocol === "https:";
    } catch (_) {
      return false;
    }
  }

  // Mobile device detection
  function isMobileDevice() {
    return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
  }

  // Calculate the number of items per page based on screen size
  function calculateItemsPerPage() {
    if (typeof window === 'undefined') return 10;

    const width = window.innerWidth;
    const height = window.innerHeight;

    // Mobile
    if (width < 768) {
      return Math.max(5, Math.floor(height / 80)); // On mobile, assume an item height of 80px
    }
    // Tablet
    else if (width < 1024) {
      return Math.max(8, Math.floor(height / 70)); // On tablet, assume an item height of 70px
    }
    // Desktop
    else {
      return Math.max(10, Math.floor(height / 60)); // On desktop, assume an item height of 60px
    }
  }

  // Window resize handler
  function handleResize() {
    const newItemsPerPage = calculateItemsPerPage();
    if (newItemsPerPage !== itemsPerPage) {
      itemsPerPage = newItemsPerPage;
      // Re-fetch with the new page size; server is authoritative for totalPages.
      scheduleGridFetch();
    }
  }

  async function pasteFromClipboard() {
    try {
      // First try the modern clipboard API
      if (navigator.clipboard && navigator.clipboard.readText) {
        const text = await navigator.clipboard.readText();
        if (!text || text.trim() === "") {
          toast.warning($t("clipboard_empty"));
          return;
        }

        const trimmedText = text.trim();
        url = trimmedText;

        // First check whether the URL format is valid
        if (!isValidUrl(trimmedText)) {
          toast.info($t("clipboard_pasted"));
          return;
        }

        // After basic URL validation, add the download automatically
        toast.info($t("clipboard_url_auto_download"));
        await addDownload(true, true); // skipValidation = true
        return;
      }

      // If there is no clipboard API, guide the user to paste manually
      const isMobile = isMobileDevice();
      if (isMobile) {
        toast.info($t("clipboard_mobile_paste_guide"));
      } else {
        toast.info($t("clipboard_desktop_paste_guide"));
      }

    } catch (err) {
      console.error("Failed to read clipboard contents: ", err);

      const isMobile = isMobileDevice();

      // Fallback on permission denial or other errors
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
        syncDownloadsSilently(); // Quiet update on re-download request
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
      // Selection auto-clears when switching tabs — so ids from another tab don't mix in.
      if (selectedIds.size > 0) {
        clearSelection();
      }
      // The search query is kept across tab switches
      currentPage = 1; // Move to the first page on tab switch
      // Quiet data refresh on tab switch
      syncDownloadsSilently();
    }
  }

  // Search input handler (client-side filtering only)
  function handleSearchInput() {
    // The grid reactive coalesces a fetch with the new search term.
    currentPage = 1; // Move to the first page on search
  }

  // Clear the search query
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

  // (old) toggleDashboard — the dashboard is always expanded, so the toggle was removed.

  // Re-fetch the visible grid whenever a relevant parameter changes (coalesced).
  // The grid renders gridDownloads directly — one server page at a time.
  $: {
    currentTab;
    currentPage;
    searchQuery;
    dashboardPeriod;
    dashboardStartDate;
    dashboardEndDate;
    itemsPerPage;
    scheduleGridFetch();
  }

  // Tab counts come from /history/stats, honoring the active period.
  $: {
    dashboardPeriod;
    dashboardStartDate;
    dashboardEndDate;
    scheduleTabCountsFetch();
  }

  // Page navigation — server is authoritative for totalPages.
  function goToPage(page) {
    if (page >= 1 && page <= totalPages) {
      currentPage = page;
    }
  }

  // Reset the page when the tab changes
  $: if (currentTab) {
    currentPage = 1;
  }

  // Live proxy gauge count comes from the active list, not the full history.
  $: activeProxyDownloadCount = activeDownloads.filter(
    (d) =>
      d.use_proxy &&
      ["downloading", "proxying"].includes(d.status?.toLowerCase?.() || ""),
  ).length;

  // Select-all reflects the currently-rendered rows (the visible grid page).
  $: someVisibleSelected =
    gridDownloads.some((d) => selectedIds.has(d.id));
  $: allVisibleSelected =
    gridDownloads.length > 0 &&
    gridDownloads.every((d) => selectedIds.has(d.id));

  // Dashboard summary cards rely on the server-side stats response;
  // fall back to 0 when the stats haven't loaded yet (no client-side total).
  $: dashboardSummaryTotal = dashboardStats?.total ?? 0;
  $: dashboardSummarySuccessRate = dashboardStats?.success_rate ?? 0;
  $: dashboardSummaryBytes = dashboardStats?.total_bytes ?? 0;
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

    <!-- Unified dashboard — KPI/charts moved to the settings "Stats" tab. The main view
         has only live (combined proxy/local card) + system monitoring. The query condition
         (period) is moved to the grid header. -->
    <Dashboard {systemStats}>
      <!-- Proxy + local as two splits within a single card. Visually they become one
           family, and the card outline/shadow/corners match the dashboard card. -->
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
      <!-- Query condition (period) — a separate row above the grid. Centered on desktop, full-width on mobile. -->
      <div class="grid-period-bar">
        <HistoryPeriodControls
          bind:period={dashboardPeriod}
          bind:startDate={dashboardStartDate}
          bind:endDate={dashboardEndDate}
          on:periodChange={(e) => {
            dashboardPeriod = e.detail;
          }}
          on:customApply={() => scheduleDashboardFetch()}
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

        <!-- Search filter -->
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
                title={$t("search_clear")}
                aria-label={$t("search_clear")}
              >
                <CloseIcon />
              </button>
            {:else if searchExpanded}
              <button
                type="button"
                class="search-clear-btn search-collapse-btn"
                on:click={closeSearch}
                title={$t("search_close")}
                aria-label={$t("search_close")}
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
        class:empty-table={gridDownloads.length === 0}
      >
        <table>
          <thead>
            <tr>
              <th class="select-col">
                <Checkbox
                  checked={allVisibleSelected}
                  indeterminate={someVisibleSelected && !allVisibleSelected}
                  ariaLabel={$t("select_count", { count: selectedIds.size })}
                  on:change={() => toggleSelectAll(gridDownloads)}
                />
              </th>
              <th>{$t("table_header_file_name")}</th>
              <th class="center-align">{$t("table_header_status")}</th>
              <th class="center-align col-size">{$t("table_header_size")}</th>
              <th class="center-align">{$t("table_header_progress")}</th>
              {#if currentTab !== "completed"}
                <th class="center-align col-speed">{$t("table_header_speed")}</th>
              {/if}
              <th class="center-align col-date">{$t("table_header_requested_date")}</th>
              <th class="center-align col-proxy">{$t("table_header_proxy")}</th>
              <th class="center-align actions-header"
                >{$t("table_header_actions")}</th
              >
            </tr>
          </thead>
          <tbody>
            {#if isDownloadsLoading}
              {#each Array(5) as _}
                <tr class="skeleton-row">
                  <td class="select-col"><Skeleton width="18px" height="18px" radius="5px" /></td>
                  <td><Skeleton width="80%" height="14px" radius="3px" /></td>
                  <td class="center-align"><Skeleton width="64px" height="22px" radius="10px" /></td>
                  <td class="center-align col-size"><Skeleton width="52px" height="14px" radius="3px" /></td>
                  <td class="center-align"><Skeleton width="100%" height="8px" radius="4px" /></td>
                  {#if currentTab !== "completed"}
                    <td class="center-align col-speed"><Skeleton width="52px" height="14px" radius="3px" /></td>
                  {/if}
                  <td class="center-align col-date"><Skeleton width="82px" height="14px" radius="3px" /></td>
                  <td class="center-align col-proxy"><Skeleton width="44px" height="22px" radius="10px" /></td>
                  <td class="center-align"><Skeleton width="76px" height="28px" radius="6px" /></td>
                </tr>
              {/each}
            {:else if gridDownloads.length === 0}
              <tr class="empty-row">
                <td
                  colspan={currentTab === "completed" ? 8 : 9}
                  class="no-downloads-message"
                >
                  {currentTab === "working"
                    ? $t("no_working_downloads")
                    : $t("no_completed_downloads")}
                </td>
              </tr>
            {:else}
              {#each gridDownloads as download (download.id)}
                <tr class:is-selected={selectedIds.has(download.id)}>
                  <td class="select-col">
                    <Checkbox
                      checked={selectedIds.has(download.id)}
                      ariaLabel="row {download.id}"
                      on:change={() => toggleSelect(download.id)}
                    />
                  </td>
                  <td
                    class="filename"
                    title={fileNameTitle(download)}
                  >
                    <span class="filename-text"
                      >{displayFileName(download)}</span
                    >
                  </td>
                  <td class="center-align">
                    <span
                      class="status status-{download.status.toLowerCase()} interactive-status {download.use_proxy
                        ? 'proxy-status'
                        : 'local-status'}"
                      title={getStatusTooltip(download)}
                    >
                      {#if auditingIds.has(download.id)}
                        <span class="audit-loading">
                          <span class="row-audit-spinner"></span>
                          {$t("action_audit_running")}
                        </span>
                      {:else if downloadWaitInfo[download.id] && downloadWaitInfo[download.id].remaining_time > 0 && ["waiting", "parsing", "proxying", "pending"].includes(download.status.toLowerCase())}
                        <!-- An active 1fichier wait countdown — show it even if the
                             status field is still 'parsing'/'proxying' (events race). -->
                        <span class="wait-countdown">
                          {$t("download_waiting_time")} ({formatWaitTime(downloadWaitInfo[download.id].remaining_time)})
                          <span class="wait-indicator wait-indicator-waiting"></span>
                        </span>
                      {:else if download.status.toLowerCase() === "downloading" && !download.progress}
                        <span class="wait-countdown">
                          {$t("download_downloading")}
                          <span
                            class="wait-indicator wait-indicator-{download.status.toLowerCase()}"
                          ></span>
                        </span>
                      {:else if download.status.toLowerCase() === "failed" && download.failure_kind}
                        <!-- Retry-pending failures are still part of the queue
                             (auto-retry on cooldown). Read as "재시도 대기" + countdown
                             so they don't look terminal. The specific kind stays
                             visible in the detail modal / tooltip. -->
                        {#if download.next_retry_at && new Date(download.next_retry_at).getTime() > currentTime}
                          {$t("download_retry_pending")}
                          <span class="wait-countdown">({formatWaitTime((new Date(download.next_retry_at).getTime() - currentTime) / 1000)})</span>
                        {:else}
                          {$t("kind_" + download.failure_kind)}
                        {/if}
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
                  <td class="center-align col-size">
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
                    <td class="center-align speed-cell col-speed">
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
                    class="center-align col-date"
                    title={formatFullDateTime(download.created_at)}
                  >
                    {formatDate(download.created_at)}
                  </td>
                  <td class="proxy-toggle-cell col-proxy">
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
                            // Update the frontend state (grid + live list).
                            gridDownloads = gridDownloads.map((d) =>
                              d.id === download.id
                                ? { ...d, use_proxy: result.use_proxy }
                                : d,
                            );
                            activeDownloads = activeDownloads.map((d) =>
                              d.id === download.id
                                ? { ...d, use_proxy: result.use_proxy }
                                : d,
                            );
                          } else {
                            toast.error(
                              $t("proxy_mode_change_failed")
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
                          <!-- File whose source is gone / repeated failures — block the click itself to prevent pointless re-requests -->
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
                          <!-- cooldown state — force retry is allowed (the server only resets the cooldown) -->
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

      <!-- Pagination - always shown -->
      <div class="pagination-footer">
      <div class="page-info">
        {#if totalPages > 1}
          <div>{$t("pagination_page_info", { currentPage, totalPages })}</div>
        {/if}
        <div class="items-info">
          {#if currentTabTotalCount > 0}
            {$t("pagination_items_info", {
              total: currentTabTotalCount,
              start: (currentPage - 1) * itemsPerPage + 1,
              end: Math.min(
                currentPage * itemsPerPage,
                currentTabTotalCount
              ),
            })}
          {/if}
        </div>
      </div>
      {#if totalPages > 1}
        <div class="pagination-buttons">
          <!-- Smart pagination for desktop -->
          <div class="pagination-desktop">
            <button
              class="page-number-btn prev-next-btn"
              on:click={() => goToPage(currentPage - 1)}
              disabled={currentPage <= 1}
            >
              <ChevronLeftIcon />
            </button>

            <!-- Smart page-number buttons -->
            {#if totalPages <= 7}
              <!-- If there are 7 or fewer total pages, show them all -->
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
              <!-- Complex pagination logic -->
              {#if currentPage <= 4}
                <!-- When the current page is near the front: 1,2,3,4,5 ... 14 -->
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
                <!-- When the current page is near the end: 1 ... 10,11,12,13,14 -->
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
                <!-- When the current page is in the middle: 1 ... 7,8,9,10,11 ... 14 -->
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

          <!-- Smart pagination for mobile -->
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
                <!-- If there are 7 or fewer total pages, show them all -->
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
                <!-- Complex pagination logic -->
                {#if currentPage <= 4}
                  <!-- When the current page is near the front: 1,2,3,4,5 ... 14 -->
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
                  <!-- When the current page is near the end: 1 ... 10,11,12,13,14 -->
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
                  <!-- When the current page is in the middle: 1 ... 7,8,9,10,11 ... 14 -->
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
      on:statsPeriodChange={() => scheduleDashboardFetch()}
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

  {#if selectedIds.size > 0}
    <div class="bulk-action-bar">
      <span class="bulk-count">{$t("select_count", { count: selectedIds.size })}</span>
      <div class="bulk-actions">
        <button class="button button-secondary" on:click={auditSelected}>
          {$t("bulk_action_audit")}
        </button>
        <button class="button button-danger" on:click={bulkDeleteSelected}>
          {$t("bulk_action_delete")}
        </button>
        <button class="button button-secondary" on:click={clearSelection}>
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
