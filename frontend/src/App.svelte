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
  import CloseIcon from "./icons/CloseIcon.svelte";
  import ChevronLeftIcon from "./icons/ChevronLeftIcon.svelte";
  import ChevronRightIcon from "./icons/ChevronRightIcon.svelte";
  import { Toaster, toast } from 'svelte-sonner';
  import ConfirmModal from "./lib/ConfirmModal.svelte";
  import ProxyGauge from "./lib/ProxyGauge.svelte";
  import LocalGauge from "./lib/LocalGauge.svelte";
  import { EventSourceManager } from "./EventSource.js";

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

  // 디바운싱을 위한 타이머
  let activeDownloadsTimer = null;

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
  let searchTimeout;

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
    dracula: "🧛‍♀️",
    system: "💻",
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

    // 로그인이 필요하지 않거나 이미 인증된 경우에만 EventSource 연결
    if (!$needsLogin || $isAuthenticated) {
      fetchDownloads(currentPage);
      connectEventSource();
      fetchActiveDownloads();
      fetchProxyStatus();
      checkProxyAvailability();
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
  });

  function handleLoginSuccess() {
    // 로그인 성공 후 필요한 데이터 로드 및 EventSource 연결
    fetchDownloads(currentPage);
    connectEventSource();
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

  function connectEventSource() {
    if (!eventSourceManager) {
      eventSourceManager = new EventSourceManager();
    }

    eventSourceManager.connect((message) => {

      if (message.type === "status_update") {
        const updatedDownload = message.data;
        // ID 타입 통일 (숫자로 변환)
        const downloadId = parseInt(updatedDownload.id);
        const index = downloads.findIndex((d) => parseInt(d.id) === downloadId);

        if (index !== -1) {
          downloads = downloads.map((d, i) =>
            i === index ? { ...d, ...updatedDownload } : d
          );
          // save_path 업데이트 로그
          if (updatedDownload.save_path) {
          }

          // 상태가 대기(waiting)가 아닌 다른 상태로 변경되면 대기 정보 제거
          if (updatedDownload.status !== "waiting" && downloadWaitInfo[downloadId]) {
            delete downloadWaitInfo[downloadId];
            downloadWaitInfo = { ...downloadWaitInfo };
          }

          // 프록시 상태 리셋 처리 (stopped, failed, done 상태일 때)
          if (proxyStats.status === "trying" &&
              ['stopped', 'failed', 'done'].includes(updatedDownload.status?.toLowerCase())) {
            const otherProxyDownloads = downloads.filter(d =>
              d.id !== downloadId &&
              (d.status === "parsing" || d.status === "downloading")
            );

            if (otherProxyDownloads.length === 0) {
              proxyStats.status = "idle";
              proxyStats.currentProxy = null;
              proxyStats.tryStartTime = null;
              console.log(`🔄 다운로드 ${downloadId} 상태 변경으로 인한 프록시 상태 리셋`);
            }
          }
        } else {
          // 중복 추가 방지: 유효한 ID와 URL이 있을 때만 추가
          if (downloadId && !isNaN(downloadId) && updatedDownload.url) {
            downloads = [updatedDownload, ...downloads];
          } else {
            console.warn("❌ 잘못된 다운로드 데이터 무시:", updatedDownload);
          }
        }

        updateStats(downloads);
      }

      // 배치 업데이트 처리
      if (message.type === "batch_status_update") {
        
        let hasChanges = false;
        const newDownloads = [...downloads];
        
        message.data.forEach(updatedDownload => {
          const index = newDownloads.findIndex((d) => d.id === updatedDownload.id);
          if (index !== -1) {
            const oldDownload = newDownloads[index];
            newDownloads[index] = { ...newDownloads[index], ...updatedDownload };
            hasChanges = true;
            
            // 프록시 다운로드의 상태가 stopped, failed, done으로 변경되면 다른 진행 중인 프록시 다운로드가 없을 때만 프록시 상태 초기화
            if (oldDownload.use_proxy &&
                oldDownload.status !== updatedDownload.status &&
                ['stopped', 'failed', 'done'].includes(updatedDownload.status?.toLowerCase())) {

              // 다른 활성 프록시 다운로드가 있는지 확인
              const otherActiveProxyDownloads = newDownloads.filter(d =>
                d.use_proxy &&
                d.id !== updatedDownload.id &&
                ['pending', 'proxying', 'parsing', 'downloading'].includes(d.status?.toLowerCase())
              );

              // 다른 활성 프록시 다운로드가 없을 때만 프록시 상태 초기화
              if (otherActiveProxyDownloads.length === 0) {
                proxyStats.status = "";
                proxyStats.currentProxy = "";
                proxyStats.currentStep = "";
                proxyStats.currentIndex = 0;
                proxyStats.totalAttempting = 0;
                proxyStats = { ...proxyStats };
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
      }



      if (message.type === "proxy_success") {
        const { id, proxy, step, message: msg } = message.data;
        proxyStats.currentProxy = proxy;
        proxyStats.currentStep = msg || step;
        proxyStats.status = "success";
        proxyStats.successCount++;
        proxyStats = { ...proxyStats };

        // 메인 그리드에서 해당 다운로드 상태도 업데이트
        if (id) {
          const download = downloads.find(d => d.id === id);
          if (download) {
            download.proxy_message = `${proxy} - ${msg || step}`;
            downloads = [...downloads];
          }
        }
      }

      if (message.type === "proxy_failed") {
        const { id, proxy, step, error, message: msg } = message.data;
        proxyStats.currentProxy = proxy || "";
        proxyStats.currentStep = msg || step;
        proxyStats.status = "failed";
        proxyStats.lastError = error || "";

        // 개별 프록시 실패는 이미 proxy_trying에서 실시간 차감됨

        // 메인 그리드에서 해당 다운로드 상태도 업데이트
        if (id) {
          const download = downloads.find(d => d.id === id);
          if (download) {
            download.proxy_message = msg || step;
            downloads = [...downloads];
          }
        }
        proxyStats.failCount++;
        proxyStats = { ...proxyStats };
      }

      // 프록시 상태 초기화 처리
      if (message.type === "proxy_reset") {
        console.log("🔄 프록시 상태 초기화 메시지 수신:", message.data);
        proxyStats.status = "";
        proxyStats.currentProxy = "";
        proxyStats.currentStep = "";
        proxyStats.currentIndex = 0;
        proxyStats.totalAttempting = 0;
        proxyStats = { ...proxyStats };
        console.log("[LOG] 프록시 상태 강제 초기화 완료");
      }

      // 1fichier 대기시간 처리 (파싱 후 대기)
      if (message.type === "waiting") {
        console.log("🕐 1fichier waiting 메시지 수신:", message.data);
        const { id, remaining, total, message: waitMsg } = message.data;
        downloadWaitInfo[id] = {
          remaining_time: remaining,
          total_time: total,
          wait_message: waitMsg || `1fichier 대기 중... ${remaining}초 남음`
        };

        // 해당 다운로드 상태를 waiting으로 업데이트
        const download = downloads.find(d => d.id === id);
        if (download) {
          download.status = "waiting";
          download.wait_message = waitMsg || `1fichier 대기 중... ${remaining}초 남음`;
          downloads = [...downloads];
        }

        downloadWaitInfo = { ...downloadWaitInfo };
        updateStats(downloads);
      }

      // 대기시간 카운트다운 처리 (로컬 다운로드용)
      if (message.type === "wait_countdown") {
        console.log("🕐 wait_countdown 메시지 수신:", message.data);
        const { id, remaining_time, wait_message } = message.data;
        downloadWaitInfo[id] = {
          remaining_time: remaining_time,
          message: wait_message,
          timestamp: Date.now(),
        };

        // 다운로드 상태는 서버에서 설정한 상태를 유지 (강제 변경하지 않음)
        downloadWaitInfo = { ...downloadWaitInfo };
        console.log("📊 downloadWaitInfo 업데이트됨:", downloadWaitInfo);
        console.log("🔍 wait_countdown 조건 체크:", {
          id,
          hasWaitInfo: !!downloadWaitInfo[id],
          remaining_time: downloadWaitInfo[id]?.remaining_time,
          condition:
            downloadWaitInfo[id] &&
            downloadWaitInfo[id].remaining_time > 0,
        });
      }

      // 대기 완료 처리
      if (message.type === "wait_countdown_complete") {
        const { id } = message.data;
        delete downloadWaitInfo[id];
        downloadWaitInfo = { ...downloadWaitInfo };
      }

      // 다운로드 정지 시 대기 정보 제거
      if (message.type === "download_stopped") {
        const { id } = message.data;
        if (downloadWaitInfo[id]) {
          delete downloadWaitInfo[id];
          downloadWaitInfo = { ...downloadWaitInfo };
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
            console.log(`🔄 마지막 프록시 다운로드 ${id} 중지로 인한 프록시 상태 리셋`);
          } else {
            console.log(`🔄 다른 프록시 다운로드 ${otherProxyDownloads.length}개 진행 중, 프록시 상태 유지`);
          }
        }
      }

      // 파일명 업데이트 처리
      if (message.type === "filename_update") {
        console.log("📁 filename_update 메시지 수신:", message.data);
        const { id, filename, file_size } = message.data;
        const index = downloads.findIndex((d) => d.id === id);
        if (index !== -1) {
          downloads = downloads.map((d, i) => {
            if (i === index) {
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
      }

      // SSE 테스트 메시지 처리
      if (message.type === "test_message") {
        console.log("🧪 SSE 테스트 메시지 수신:", message.data);
        alert($t("sse_connection_normal") + ": " + message.data.message);
      }

      if (message.type === "force_refresh") {
        const { id, status: newStatus, action } = message.data;
        if (action === "pause_confirmed") {
          const index = downloads.findIndex((d) => d.id === id);
          if (index !== -1 && downloads[index].status !== newStatus) {
            downloads = downloads.map((d, i) =>
              i === index ? { ...d, status: newStatus } : d
            );
          }
          updateStats(downloads);
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

  // fetchActiveDownloads를 주기적으로 호출하는 인터벌 (5초마다 - 성능 최적화)
  setInterval(() => {
    if (needsActiveDownloadsUpdate) {
      fetchActiveDownloads();
      needsActiveDownloadsUpdate = false;
    }
  }, 5000);

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

    // 어제 이전이면 간단한 날짜 형식
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
    currentPage = 1;
  }

  // 검색 필터 적용된 다운로드 목록 (한번만 필터링)
  $: searchFiltered = (() => {
    if (!Array.isArray(downloads)) return [];

    let filtered = downloads;

    // 검색 필터 적용
    if (searchQuery && searchQuery.trim()) {
      const query = searchQuery.trim().toLowerCase();
      filtered = filtered.filter((d) => {
        const filename = d.filename?.toLowerCase() || "";
        const url = d.url?.toLowerCase() || "";
        return filename.includes(query) || url.includes(query);
      });
    }

    return filtered;
  })();

  // 검색 필터가 적용된 카운트
  $: workingCount = searchFiltered.filter((d) => {
    const status = d.status?.toLowerCase?.() || "";
    return !(
      status === "done" ||
      (status === "stopped" &&
        (d.progress >= 100 || getDownloadProgress(d) >= 100))
    );
  }).length;

  $: completedCount = searchFiltered.filter((d) => {
    const status = d.status?.toLowerCase?.() || "";
    return (
      status === "done" ||
      (status === "stopped" &&
        (d.progress >= 100 || getDownloadProgress(d) >= 100))
    );
  }).length;

  $: filteredDownloads = (() => {
    if (currentTab === "working") {
      return searchFiltered.filter((d) => {
        const status = d.status?.toLowerCase?.() || "";
        // 완료된 것만 제외하고 나머지는 모두 진행중으로 처리
        return !(
          status === "done" ||
          (status === "stopped" &&
            (d.progress >= 100 || getDownloadProgress(d) >= 100))
        );
      });
    } else {
      // 완료 탭: done 상태 또는 100% 완료인 stopped 상태만
      return searchFiltered
        .filter((d) => {
          const status = d.status?.toLowerCase?.() || "";
          return (
            status === "done" ||
            (status === "stopped" &&
              (d.progress >= 100 || getDownloadProgress(d) >= 100))
          );
        })
        .sort((a, b) => {
          // finished_at을 우선으로 하고, 없으면 created_at, 없으면 updated_at으로 정렬 (최신 순)
          const aTime = new Date(a.finished_at || a.created_at || a.updated_at || 0);
          const bTime = new Date(b.finished_at || b.created_at || b.updated_at || 0);
          return bTime.getTime() - aTime.getTime(); // 내림차순 정렬 (최신 순 먼저)
        });
    }
  })();

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
          statusMessage={proxyStats.status_message || ""}
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

        <!-- 검색 필터 -->
        <div class="search-container">
          <input
            type="text"
            class="search-input"
            placeholder={$t("search_placeholder")}
            bind:value={searchQuery}
            on:input={handleSearchInput}
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
          {:else}
            <div class="search-icon">
              <SearchIcon />
            </div>
          {/if}
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
                    title={download.filename || $t("file_name_na")}
                  >
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
                      {#if download.status.toLowerCase() === "cooldown" && download.cooldown_remaining}
                        <span class="cooldown-countdown">
                          {$t("download_cooldown")} ({download.cooldown_remaining}{$t(
                            "time_seconds"
                          )})
                          <span class="cooldown-indicator"></span>
                        </span>
                      {:else if download.status.toLowerCase() === "waiting" && downloadWaitInfo[download.id] && downloadWaitInfo[download.id].remaining_time > 0}
                        <span class="wait-countdown">
                          {#if downloadWaitInfo[download.id].remaining_time >= 60}
                            {$t("download_waiting_time")} ({Math.floor(
                              downloadWaitInfo[download.id].remaining_time /
                                60
                            )}{$t("time_minutes")})
                          {:else if downloadWaitInfo[download.id].remaining_time > 10}
                            {$t("download_waiting_time")} ({downloadWaitInfo[
                              download.id
                            ].remaining_time}{$t("time_seconds")})
                          {:else}
                            {$t("download_waiting_time")} ({Math.max(1, Math.floor((downloadWaitInfo[download.id].remaining_time * 1000 - (Date.now() - (downloadWaitInfo[download.id].timestamp || 0))) / 1000))}{$t("time_seconds")})
                          {/if}
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
                      {#if ["downloading", "proxying", "pending", "parsing", "cooldown", "waiting"].includes(download.status?.toLowerCase())}
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
                        <button
                          class="button-icon"
                          title={$t("action_retry")}
                          on:click={() => callApi(`/api/retry/${download.id}`)}
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
          <!-- 데스크톱용 기존 레이아웃 -->
          <div class="pagination-desktop">
            <button
              class="page-number-btn prev-next-btn"
              on:click={() => goToPage(currentPage - 1)}
              disabled={currentPage <= 1}
            >
              <ChevronLeftIcon />
            </button>

            <!-- 페이지 번호 버튼들 - 최대 5개 표시 -->
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
              <ChevronRightIcon />
            </button>
          </div>

          <!-- 모바일용 세로 레이아웃 -->
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
              {#each Array(Math.min(totalPages, 5)) as _, i}
                {@const pageNum = Math.max(1, currentPage - 2) + i}
                {#if pageNum <= totalPages}
                  <button
                    class="page-number-btn-mobile"
                    class:active={currentPage === pageNum}
                    on:click={() => goToPage(pageNum)}
                  >
                    {pageNum}
                  </button>
                {/if}
              {/each}
            </div>
          </div>
        </div>
      {/if}
    </div>
  {/if}

  <SettingsModal
    showModal={showSettingsModal}
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
    style: $theme === 'dracula' ?
      'background: var(--card-background); color: var(--text-primary); border: 1px solid var(--card-border);' :
      $theme === 'dark' ?
      'background: var(--card-background); color: var(--text-primary); border: 1px solid var(--card-border);' :
      ''
  }}
/>
