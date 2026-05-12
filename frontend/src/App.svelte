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
    locale as localeStore,
  } from "./lib/i18n.js";
  import { 
    formatBytes, 
    isValidUrl, 
    isMobileDevice 
  } from "./lib/utils.js";
  import {
    needsLogin,
    isAuthenticated,
    authRequired,
    authManager,
    authUser,
  } from "./lib/auth.js";
  import { api } from "./lib/api.js";
  import { downloads as downloadsStore, fetchProxyStatus, proxyStats as proxyStatsStore } from "./lib/stores/downloads.js";
  
  import LoginScreen from "./lib/LoginScreen.svelte";
  import DetailModal from "./lib/DetailModal.svelte";
  import { Toaster, toast } from 'svelte-sonner';
  import ConfirmModal from "./lib/ConfirmModal.svelte";
  import ProxyGauge from "./lib/ProxyGauge.svelte";
  import LocalGauge from "./lib/LocalGauge.svelte";
  import Dashboard from "./lib/Dashboard.svelte";
  import { EventSourceManager } from "./EventSource.js";

  // New components
  import AddDownload from "./lib/components/AddDownload.svelte";
  import DownloadTabs from "./lib/components/DownloadTabs.svelte";
  import DownloadTable from "./lib/components/DownloadTable.svelte";

  // Icons for main UI
  import SettingsIcon from "./icons/SettingsIcon.svelte";
  import BarChartIcon from "./icons/BarChartIcon.svelte";
  import ChevronRightIcon from "./icons/ChevronRightIcon.svelte";

  let downloads = [];
  $: downloadsStore.set(downloads); // Sync store with local state

  let url = "";
  let password = "";
  let eventSourceManager;
  let currentPage = 1;
  let itemsPerPage = 10;
  let isDownloadsLoading = false;
  let isAddingDownload = false;
  let activeDownloads = [];

  let showSettingsModal = false;
  let showPasswordModal = false;
  let showDetailModal = false;
  let currentSettings = {};
  let hasPassword = false;
  let selectedDownload = null;
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
  $: proxyStatsStore.set(proxyStats);

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

  let waitTimeUpdateTimer = null;
  let currentTime = Date.now();

  let showConfirm = false;
  let confirmMessage = "";
  let confirmAction = null;
  let confirmTitle = null;
  let confirmIcon = null;
  let confirmButtonText = null;
  let cancelButtonText = null;

  let currentTab = "working";
  let searchQuery = "";
  let searchExpanded = false;
  let searchInputEl;
  let searchTimeout;

  // Dashboard state
  let dashboardPeriod = "30d";
  let dashboardStartDate = "";
  let dashboardEndDate = "";
  let dashboardStats = null;
  let dashboardHistory = [];
  let dashboardTotalPages = 0;
  let dashboardCurrentPage = 1;
  let dashboardExpanded = false;

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

    if (!$needsLogin || $isAuthenticated) {
      refreshData();
    }

    waitTimeUpdateTimer = setInterval(() => {
      currentTime = Date.now();
    }, 1000);

    const handleProxyRefresh = () => {
      fetchProxyStatusLocal();
      checkProxyAvailability();
    };
    document.addEventListener("proxy-refreshed", handleProxyRefresh);
    window.addEventListener("resize", handleResize);

    const handleVisibilityChange = () => {
      if (!document.hidden) {
        syncDownloadsSilently();
        if (!eventSourceManager || !eventSourceManager.isConnected()) {
          reconnectEventSource();
        }
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    const unsubscribeTitle = t.subscribe((t_func) => {
      document.title = t_func("title");
    });

    return () => {
      document.removeEventListener("proxy-refreshed", handleProxyRefresh);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("resize", handleResize);
      unsubscribeTitle();
      if (waitTimeUpdateTimer) clearInterval(waitTimeUpdateTimer);
      if (eventSourceManager) eventSourceManager.disconnect();
    };
  });

  async function refreshData() {
    await Promise.all([
      getDownloads(),
      fetchProxyStatusLocal(),
      checkProxyAvailability(),
      fetchActiveDownloads()
    ]);
    connectEventSource();
  }

  async function fetchSettings() {
    try {
      currentSettings = await api.getSettings();
    } catch (error) {
      console.error("Error fetching settings:", error);
    }
  }

  async function fetchProxyStatusLocal() {
    try {
      const data = await api.getProxyStatus();
      proxyStats = {
        ...proxyStats,
        totalProxies: data.total_proxies,
        availableProxies: data.available_proxies,
        usedProxies: data.used_proxies,
        successCount: data.success_count,
        failCount: data.fail_count,
        status_message: data.status_message,
      };
    } catch (error) {
      console.error($t("proxy_status_fetch_failed"), error);
    }
  }

  async function checkProxyAvailability() {
    try {
      const data = await api.checkProxyAvailability();
      proxyAvailable = data.available;
      if (!proxyAvailable && useProxy) {
        useProxy = false;
      }
    } catch (error) {
      console.error($t("proxy_availability_check_failed"), error);
      proxyAvailable = false;
    }
  }

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
      case "custom":
        return { start: dashboardStartDate, end: dashboardEndDate };
      default:
        return { start: "", end: "" };
    }
  }

  async function fetchDashboardStats() {
    try {
      const { start, end } = getDashboardDateRange();
      dashboardStats = await api.getHistoryStats(start, end);
    } catch (e) {
      console.error("Dashboard stats error:", e);
    }
  }

  async function fetchDashboardHistory() {
    try {
      const { start, end } = getDashboardDateRange();
      const data = await api.getHistoryPeriod(start, end, dashboardCurrentPage, 10);
      dashboardHistory = data.history;
      dashboardTotalPages = data.total_pages;
    } catch (e) {
      console.error("Dashboard history error:", e);
    }
  }

  async function toggleDashboard() {
    dashboardExpanded = !dashboardExpanded;
    if (dashboardExpanded) {
      await Promise.all([fetchDashboardStats(), fetchDashboardHistory()]);
    }
  }

  function connectEventSource() {
    if (eventSourceManager) eventSourceManager.disconnect();

    eventSourceManager = new EventSourceManager();
    eventSourceManager.connect();

    eventSourceManager.on("download_update", (data) => {
      if (data && data.id) {
        downloads = downloads.map((d) => d.id === data.id ? { ...d, ...data } : d);
      }
    });

    eventSourceManager.on("download_added", (data) => {
      if (data && data.id) {
        if (!downloads.find((d) => d.id === data.id)) {
          downloads = [data, ...downloads];
        }
      }
    });

    eventSourceManager.on("download_deleted", (data) => {
      if (data && data.id) {
        downloads = downloads.filter((d) => d.id !== data.id);
      }
    });

    eventSourceManager.on("proxy_stats", (data) => {
      if (data) {
        proxyStats = { ...proxyStats, ...data };
      }
    });

    eventSourceManager.on("local_stats", (data) => {
      if (data) {
        localStats = { ...localStats, ...data };
      }
    });

    eventSourceManager.on("proxy_step", (data) => {
      if (data && data.id) {
        downloadProxyInfo[data.id] = {
          proxy: data.proxy,
          step: data.step,
          current: data.current,
          total: data.total,
          status: data.status || "trying",
          error: data.error,
          timestamp: Date.now(),
        };
      }
    });

    eventSourceManager.on("wait_countdown", (data) => {
      if (data && data.id) {
        downloadWaitInfo[data.id] = data.until * 1000;
      }
    });

    eventSourceManager.on("downloads_active_update", (data) => {
      if (data && data.active_downloads) {
        activeDownloads = data.active_downloads;
      }
    });
  }

  function reconnectEventSource() {
    connectEventSource();
  }

  async function getDownloads() {
    isDownloadsLoading = true;
    try {
      const data = await api.getHistory();
      downloads = data.history || [];
    } catch (error) {
      console.error("Error fetching downloads:", error);
    } finally {
      isDownloadsLoading = false;
    }
  }

  async function syncDownloadsSilently() {
    try {
      const data = await api.getHistory();
      downloads = data.history || [];
    } catch (e) {
      console.error("Silent sync failed:", e);
    }
  }

  async function fetchActiveDownloads() {
    try {
      const data = await api.getActiveDownloads();
      activeDownloads = data.active_downloads || [];
    } catch (error) {
      console.error("Error fetching active downloads:", error);
    }
  }

  async function callApi(endpoint) {
    try {
      const responseData = await api.request(endpoint, { method: "POST" });
      if (responseData && responseData.status === "waiting" && responseData.message_key) {
        toast.info($t(responseData.message_key, responseData.message_args));
        return;
      }
      const actionKey = endpoint.includes("/start/") ? "download" :
                        endpoint.includes("/stop/") ? "pause" :
                        endpoint.includes("/resume/") ? "resume" :
                        endpoint.includes("/retry/") ? "retry" : "work";
      toast.success($t(`action_${actionKey}_success`));
    } catch (error) {
      toast.error(error.message);
    }
  }

  async function addDownload(skipValidation = false, isAutoDownload = false) {
    if (!skipValidation && (!url || url.trim() === "")) {
      toast.error($t("url_required"));
      return;
    }

    isAddingDownload = true;
    try {
      const newDownload = await api.addDownload(url.trim(), password, useProxy);
      if (newDownload.status === "waiting" && newDownload.message_key) {
        toast.info($t(newDownload.message_key, newDownload.message_args));
      } else if (!isAutoDownload) {
        toast.success($t("download_added_successfully"));
      }
      url = "";
      password = "";
      hasPassword = false;
      getDownloads();
    } catch (error) {
      toast.error($t("add_download_failed", { detail: error.message }));
    } finally {
      isAddingDownload = false;
    }
  }

  async function deleteDownload(id) {
    if (!id || isNaN(parseInt(id))) return;
    
    openConfirm({
      message: $t("delete_confirm"),
      onConfirm: async () => {
        try {
          await api.deleteDownload(id);
          toast.success($t("download_deleted_success"));
          downloads = downloads.filter((d) => d.id !== id);
        } catch (error) {
          toast.error($t("delete_error"));
        }
      },
      title: $t("confirm_delete_title"),
      confirmText: $t("button_delete"),
      cancelText: $t("button_cancel"),
    });
  }

  function getStatusTooltip(download) {
    const proxyInfo = downloadProxyInfo[download.id];
    if (download.status?.toLowerCase() === "pending" && download.error_message?.includes($t("auto_retry_in_progress"))) {
      return download.error_message + "\n3분마다 자동 재시도됩니다.";
    }
    if (download.status?.toLowerCase() === "failed" && download.error_message) {
      return proxyInfo?.error ? $t("status_tooltip_failed_with_proxy", { error: download.error_message, proxy: proxyInfo.proxy, proxy_error: proxyInfo.error }) : download.error_message;
    }
    if (proxyInfo) {
      const statusIcon = { trying: "🔄", success: "✅", failed: "❌" };
      const icon = statusIcon[proxyInfo.status] || "❓";
      let tooltip = `${icon} ${$t("proxy_tooltip_proxy")}: ${proxyInfo.proxy}\n${$t("proxy_tooltip_step")}: ${proxyInfo.step}`;
      if (proxyInfo.current && proxyInfo.total) tooltip += `\n${$t("proxy_tooltip_progress")}: ${proxyInfo.current}/${proxyInfo.total}`;
      if (proxyInfo.status === "trying") tooltip += `\n${$t("proxy_tooltip_trying")} (${Math.floor((Date.now() - proxyInfo.timestamp) / 1000)}${$t("proxy_tooltip_seconds")})`;
      if (proxyInfo.error) tooltip += `\n${$t("proxy_tooltip_error")}: ${proxyInfo.error}`;
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
    return statusTooltips[download.status?.toLowerCase()] || download.status;
  }

  function calculateItemsPerPage() {
    if (typeof window === 'undefined') return 10;
    const height = window.innerHeight;
    if (window.innerWidth < 768) return Math.max(5, Math.floor(height / 80));
    if (window.innerWidth < 1024) return Math.max(8, Math.floor(height / 70));
    return Math.max(10, Math.floor(height / 60));
  }

  function handleResize() {
    const newItemsPerPage = calculateItemsPerPage();
    if (newItemsPerPage !== itemsPerPage) {
      itemsPerPage = newItemsPerPage;
    }
  }

  async function pasteFromClipboard() {
    try {
      if (navigator.clipboard && navigator.clipboard.readText) {
        const text = await navigator.clipboard.readText();
        if (!text || text.trim() === "") {
          toast.warning($t("clipboard_empty"));
          return;
        }
        url = text.trim();
        if (!isValidUrl(url)) {
          toast.info($t("clipboard_pasted"));
          return;
        }
        toast.info($t("clipboard_url_auto_download"));
        await addDownload(true, true);
      } else {
        toast.info(isMobileDevice() ? $t("clipboard_mobile_paste_guide") : $t("clipboard_desktop_paste_guide"));
      }
    } catch (err) {
      toast.error($t("clipboard_read_failed"));
    }
  }

  function openPasswordModal() { showPasswordModal = true; }
  function handlePasswordSet(event) {
    password = event.detail.password;
    hasPassword = !!password;
    showPasswordModal = false;
  }

  function openDetailModal(download) {
    selectedDownload = download;
    showDetailModal = true;
  }

  async function copyDownloadLink(download) {
    try {
      await navigator.clipboard.writeText(download.url);
      toast.success($t("clipboard_copy_success_with_link", { link: download.url }));
    } catch (e) {
      toast.error($t("clipboard_copy_failed"));
    }
  }

  async function redownload(download) {
    try {
      await api.addDownload(download.url, "", download.use_proxy || false);
      toast.success($t("redownload_requested"));
      syncDownloadsSilently();
      currentTab = "working";
    } catch (error) {
      toast.error($t("redownload_failed_with_detail", { detail: error.message }));
    }
  }

  function onTabChange(tab) {
    currentTab = tab;
    currentPage = 1;
  }

  function handleSearchInput() {
    if (searchTimeout) clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
      currentPage = 1;
    }, 300);
  }

  function clearSearch() {
    searchQuery = "";
    currentPage = 1;
  }

  function openSearch() {
    searchExpanded = true;
    setTimeout(() => searchInputEl?.focus(), 100);
  }

  function closeSearch() {
    searchExpanded = false;
    searchQuery = "";
    currentPage = 1;
  }

  function goToPage(page) {
    if (page >= 1 && page <= totalPages) {
      currentPage = page;
    }
  }

  function handleResetProxyStatus() {
    proxyStats = { ...proxyStats, status: "idle", currentProxy: "", currentStep: "", currentIndex: 0, totalAttempting: 0, status_message: "" };
  }

  function handleLoginSuccess() {
    refreshData();
  }

  $: filteredDownloads = downloads.filter((d) => {
    const status = d.status?.toLowerCase?.() || "";
    const isCompleted = status === "done" || (status === "stopped" && (d.progress >= 100 || d.downloaded_size >= d.total_size));
    const tabMatch = currentTab === "working" ? !isCompleted : isCompleted;
    if (!tabMatch) return false;
    if (!searchQuery) return true;
    const query = searchQuery.toLowerCase();
    return (d.filename || "").toLowerCase().includes(query) || (d.url || "").toLowerCase().includes(query);
  }).sort((a, b) => {
    if (currentTab === "completed") {
      const aTime = new Date(a.finished_at || a.created_at || 0).getTime();
      const bTime = new Date(b.finished_at || b.created_at || 0).getTime();
      return bTime - aTime;
    }
    return new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime();
  });

  $: totalPages = Math.ceil(filteredDownloads.length / itemsPerPage) || 1;
  $: if (currentPage > totalPages) currentPage = totalPages;
  $: paginatedDownloads = filteredDownloads.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage);

  $: workingCount = downloads.filter(d => {
    const status = d.status?.toLowerCase?.() || "";
    return !(status === "done" || (status === "stopped" && d.progress >= 100));
  }).length;
  $: completedCount = downloads.length - workingCount;

  $: dashboardSummaryTotal = dashboardStats?.total_downloads || 0;
  $: dashboardSummarySuccessRate = dashboardStats?.total_downloads > 0 ? (dashboardStats.by_status?.done / dashboardStats.total_downloads) * 100 : 0;
  $: dashboardSummaryBytes = dashboardStats?.total_bytes || 0;
  $: activeProxyDownloadCount = downloads.filter(d => d.use_proxy && ["downloading", "proxying", "parsing"].includes(d.status?.toLowerCase())).length;

</script>

<Toaster position="top-right" richColors closeButton />

{#if $isLoading}
  <div class="initial-loading">
    <div class="loader-container">
      <div class="spinner-large"></div>
      <div class="loader-text">{$t("loading_message")}</div>
    </div>
  </div>
{:else if $needsLogin && !$isAuthenticated}
  <LoginScreen on:loginSuccess={handleLoginSuccess} />
{:else}
  <header class="app-header">
    <div class="header-container">
      <div class="logo-area">
        <img src={logo} alt="Logo" class="app-logo" />
        <div class="app-title-group">
          <h1 class="app-name">OC Proxy</h1>
          <p class="app-subtitle">{$t("subtitle")}</p>
        </div>
      </div>
      <div class="header-actions">
        <button
          class="settings-btn"
          on:click={() => (showSettingsModal = true)}
          title={$t("settings_title")}
        >
          <SettingsIcon />
          <span class="btn-text">{$t("settings_title")}</span>
        </button>
      </div>
    </div>
  </header>

  <main id="app">
    <div class="main-content">
      <AddDownload
        bind:url
        {password}
        {hasPassword}
        bind:useProxy
        {proxyAvailable}
        {isAddingDownload}
        {pasteFromClipboard}
        {openPasswordModal}
        {addDownload}
      />

      <button
        type="button"
        class="dashboard-summary-strip"
        class:expanded={dashboardExpanded}
        on:click={toggleDashboard}
        aria-expanded={dashboardExpanded}
      >
        <span class="dashboard-summary-icon"><BarChartIcon /></span>
        <span class="dashboard-summary-pill">
          <strong>{dashboardSummaryTotal.toLocaleString()}</strong>
          <span>{$t("dashboard_total_downloads")}</span>
        </span>
        <span class="dashboard-summary-pill">
          <strong>{dashboardSummarySuccessRate.toFixed(0)}%</strong>
          <span>{$t("dashboard_success_rate")}</span>
        </span>
        <span class="dashboard-summary-pill">
          <strong>{workingCount}</strong>
          <span>{$t("tab_working")}</span>
        </span>
        <span class="dashboard-summary-pill dashboard-summary-data">
          <strong>{formatBytes(dashboardSummaryBytes)}</strong>
          <span>{$t("dashboard_total_data")}</span>
        </span>
        <span class="dashboard-summary-chevron">
          <ChevronRightIcon />
        </span>
      </button>

      {#if dashboardExpanded}
        <div class="dashboard-drawer">
          <div class="gauge-container dashboard-gauges">
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
                statusMessage={proxyStats.status_message || ""}
                on:resetProxyStatus={handleResetProxyStatus}
              />
            </div>

            <div class="gauge-item">
              <LocalGauge
                localDownloadCount={localStats.localDownloadCount}
                localStatus={localStats.localStatus}
              />
            </div>
          </div>

          <Dashboard
            {dashboardStats}
            {dashboardPeriod}
            {dashboardStartDate}
            {dashboardEndDate}
            {dashboardHistory}
            {dashboardTotalPages}
            dashboardCurrentPage={dashboardCurrentPage}
            on:periodChange={(e) => { dashboardPeriod = e.detail; }}
            on:customApply={() => { fetchDashboardStats(); fetchDashboardHistory(); }}
            on:pageChange={(e) => { dashboardCurrentPage = e.detail; fetchDashboardHistory(); }}
          />
        </div>
      {/if}

      <div class="downloads-section">
        <DownloadTabs
          {currentTab}
          {workingCount}
          {completedCount}
          {onTabChange}
          {searchExpanded}
          {searchQuery}
          {handleSearchInput}
          {clearSearch}
          {openSearch}
          {closeSearch}
          bind:searchInputEl
        />

        <DownloadTable
          {currentTab}
          {paginatedDownloads}
          {filteredDownloads}
          {isDownloadsLoading}
          {downloadProxyInfo}
          {downloadWaitInfo}
          {currentTime}
          {currentPage}
          {totalPages}
          {itemsPerPage}
          {goToPage}
          {openDetailModal}
          {deleteDownload}
          {redownload}
          {copyDownloadLink}
          {callApi}
          {getStatusTooltip}
          bind:downloads
        />
      </div>
    </div>
  </main>
{/if}

<SettingsModal
  bind:showModal={showSettingsModal}
  {currentSettings}
  on:settingsChanged={(e) => {
    currentSettings = e.detail;
  }}
  on:proxyChanged={fetchProxyStatusLocal}
/>

<PasswordModal
  bind:showModal={showPasswordModal}
  on:setPassword={handlePasswordSet}
/>

{#if selectedDownload}
  <DetailModal
    bind:showModal={showDetailModal}
    download={selectedDownload}
    on:delete={() => deleteDownload(selectedDownload.id)}
  />
{/if}

<ConfirmModal
  bind:showModal={showConfirm}
  title={confirmTitle || $t("confirm_title")}
  message={confirmMessage}
  icon={confirmIcon}
  confirmText={confirmButtonText || $t("button_confirm")}
  cancelText={cancelButtonText || $t("button_cancel")}
  on:confirm={confirmAction}
  on:cancel={() => (showConfirm = false)}
/>

<style>
  .initial-loading {
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100vh;
    background: var(--background);
  }

  .loader-container {
    text-align: center;
  }

  .spinner-large {
    width: 60px;
    height: 60px;
    border: 6px solid var(--card-border);
    border-top: 6px solid var(--primary-color);
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin: 0 auto 1.5rem;
  }

  .loader-text {
    font-size: 1.2rem;
    color: var(--text-secondary);
    font-weight: 600;
  }

  .app-header {
    background: var(--card-background);
    border-bottom: 1px solid var(--card-border);
    padding: 1rem 0;
    position: sticky;
    top: 0;
    z-index: 100;
  }

  .header-container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 0 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .logo-area {
    display: flex;
    align-items: center;
    gap: 1rem;
  }

  .app-logo {
    width: 40px;
    height: 40px;
  }

  .app-name {
    font-size: 1.5rem;
    margin: 0;
    font-weight: 800;
    color: var(--primary-color);
  }

  .app-subtitle {
    margin: 0;
    font-size: 0.8rem;
    color: var(--text-secondary);
  }

  .settings-btn {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: var(--bg-secondary);
    border: 1px solid var(--card-border);
    padding: 0.5rem 1rem;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
    color: var(--text-primary);
  }

  .settings-btn:hover {
    border-color: var(--primary-color);
    background: var(--card-background);
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  @media (max-width: 600px) {
    .btn-text { display: none; }
    .settings-btn { padding: 0.6rem; }
  }

  .main-content {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }
</style>
