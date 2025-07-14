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
  let isDownloadsLoading = false;
  let activeDownloads = []; // 활성 다운로드 목록

  let showSettingsModal = false;
  let showPasswordModal = false;
  let showDetailModal = false;
  let currentSettings = {};
  let hasPassword = false; // To track if a password has been set
  let selectedDownload = {};
  let downloadPath = ""; // Declare downloadPath here
  let prevLang = null;

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

        // 상태 업데이트 후 활성 다운로드 목록 갱신
        fetchActiveDownloads();
      }
    };

    ws.onclose = () => {
      console.log("WebSocket disconnected. Attempting to reconnect...");
      setTimeout(connectWebSocket, 5000);
    };
  }

  async function fetchDownloads(page = 1) {
    isDownloadsLoading = true;
    try {
      const response = await fetch(`/api/history/?page=${page}&size=10`);
      if (response.ok) {
        const data = await response.json();
        downloads = data.items;
        currentPage = data.page;
        totalPages = data.total_pages;
      } else {
        downloads = [];
      }
    } catch (error) {
      downloads = [];
    } finally {
      isDownloadsLoading = false;
    }
  }

  async function addDownload() {
    if (!url) return;
    try {
      const response = await fetch("/api/download/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, password }),
      });
      if (response.ok) {
        const newDownload = await response.json();
        url = "";
        password = ""; // Clear password after successful download
        hasPassword = false; // Reset password status
        // fetchDownloads(); // No longer needed for immediate UI update
      } else {
        const errorData = await response.json();
        alert(`Failed to add download: ${errorData.detail}`);
      }
    } catch (error) {
      console.error("Error adding download:", error);
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

  async function cancelDownload(downloadId) {
    if (!confirm($t("cancel_confirm"))) return;

    try {
      const response = await fetch(`/api/downloads/cancel/${downloadId}`, {
        method: "POST",
      });
      if (response.ok) {
        showToastMsg($t("download_cancelled"));
        await fetchActiveDownloads();
      } else {
        showToastMsg($t("cancel_failed"));
      }
    } catch (error) {
      console.error("Error cancelling download:", error);
      showToastMsg($t("cancel_failed"));
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
    if (!confirm($t("delete_confirm"))) return;
    await callApi(`/api/delete/${id}`);
    fetchDownloads(currentPage);
  }

  function formatBytes(bytes, decimals = 2) {
    if (!bytes || bytes === 0) return "0 Bytes";
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
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

  function handleSettingsChanged() {
    // 이후엔 오직 localStorage.lang만 기준
    const lang = localStorage.getItem("lang");
    if (lang && lang !== prevLang) {
      loadTranslations(lang);
      prevLang = lang;
    }
  }
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
        <button type="submit" class="button button-primary add-download-button">
          <DownloadIcon />
          {$t("add_download")}
        </button>
      </form>
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
              <th class="actions-header">{$t("table_header_actions")}</th>
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
            {:else if downloads.length === 0}
              <tr>
                <td colspan="7" class="no-downloads-message">
                  {$t("no_downloads_message")}
                </td>
              </tr>
            {:else}
              {#each downloads as download (download.id)}
                <tr>
                  <td class="filename" title={download.url}>
                    {download.file_name || $t("file_name_na")}
                  </td>
                  <td>
                    <span
                      class="status status-{download.status.toLowerCase()}"
                      title={download.status.toLowerCase() === "failed"
                        ? download.error
                        : ""}
                    >
                      {$t(`download_${download.status.toLowerCase()}`)}
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
                  <td class="actions">
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
                            "paused"
                          )}
                      >
                        <PauseIcon />
                      </button>
                      {#if activeDownloads.includes(download.id)}
                        <button
                          class="button-icon danger"
                          title="강제 취소"
                          on:click={() => cancelDownload(download.id)}
                        >
                          ✕
                        </button>
                      {/if}
                    {:else if (download.status
                      .toLowerCase()
                      .includes("pending") || download.status
                        .toLowerCase()
                        .includes("paused")) && !download.status
                        .toLowerCase()
                        .includes("proxying")}
                      <button
                        class="button-icon"
                        title={$t("action_resume")}
                        on:click={() =>
                          callApi(
                            `/api/resume/${download.id}`,
                            download.id,
                            "pending"
                          )}
                      >
                        <ResumeIcon />
                      </button>
                    {/if}
                    {#if download.status.toLowerCase().includes("failed")}
                      <button
                        class="button-icon"
                        title={$t("action_retry")}
                        on:click={() => callApi(`/api/retry/${download.id}`)}
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
                      class="button-icon danger"
                      title={$t("action_delete")}
                      on:click={() => deleteDownload(download.id)}
                    >
                      <DeleteIcon />
                    </button>
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
</main>
