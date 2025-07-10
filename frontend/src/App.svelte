<script>
  import logo from "./assets/images/logo256.png";
  import SettingsModal from "./lib/SettingsModal.svelte";
  import PasswordModal from "./lib/PasswordModal.svelte";
  import { onMount } from "svelte";
  import { theme } from "./lib/theme.js";
  import { t, isLoading, initializeLocale } from "./lib/i18n.js";

  let downloads = [];
  let url = "";
  let password = "";
  let ws;
  let currentPage = 1;
  let totalPages = 1;

  let showSettingsModal = false;
  let showPasswordModal = false;
  let currentSettings = {};
  let hasPassword = false; // To track if a password has been set

  // --- Icons ---
  const icons = {
    pause:
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>',
    resume:
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>',
    retry:
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>',
    delete:
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>',
    clipboard:
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path><rect x="8" y="2" width="8" height="4" rx="1" ry="1"></rect></svg>',
    lock: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-lock"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
    unlock:
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-unlock"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/></svg>',
    folder:
      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-folder"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.24A2 2 0 0 0 4.07 2H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2z"/></svg>',
  };

  onMount(async () => {
    await initializeLocale();
    fetchDownloads(currentPage);
    connectWebSocket();
    fetchSettings();

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
    const wsProtocol = window.location.protocol === "https" ? "wss" : "ws";
    ws = new WebSocket(`${wsProtocol}://${window.location.host}/ws/status`);

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "status_update") {
        const updatedDownload = message.data;
        const index = downloads.findIndex((d) => d.id === updatedDownload.id);
        if (index !== -1) {
          downloads[index] = updatedDownload;
        } else {
          fetchDownloads(1);
        }
      }
    };

    ws.onclose = () => {
      setTimeout(connectWebSocket, 5000);
    };
  }

  async function fetchDownloads(page = 1) {
    try {
      const response = await fetch(`/api/history/?page=${page}&size=10`);
      if (response.ok) {
        const data = await response.json();
        downloads = data.items;
        currentPage = data.page;
        totalPages = data.total_pages;
      } else {
        console.error("Failed to fetch downloads");
      }
    } catch (error) {
      console.error("Error fetching downloads:", error);
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
        url = "";
        password = ""; // Clear password after successful download
        hasPassword = false; // Reset password status
        fetchDownloads();
      } else {
        const errorData = await response.json();
        alert(`Failed to add download: ${errorData.detail}`);
      }
    } catch (error) {
      console.error("Error adding download:", error);
    }
  }

  async function callApi(endpoint) {
    try {
      await fetch(endpoint, { method: "POST" });
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

  function getDownloadProgress(download) {
    console.log("Download object for progress:", download);
    if (download.file_size === 0 || download.status === "pending") return 0;
    if (download.status === "done") return 100;
    // Ensure downloaded_size and file_size are numbers
    const downloaded = Number(download.downloaded_size);
    const total = Number(download.file_size);

    if (isNaN(downloaded) || isNaN(total) || total === 0) {
      console.warn("Invalid download progress data:", { downloaded, total });
      return 0; // Return 0 or handle as appropriate
    }
    return Math.round((downloaded / total) * 100);
  }

  async function pasteFromClipboard() {
    try {
      url = await navigator.clipboard.readText();
    } catch (err) {
      console.error("Failed to read clipboard contents: ", err);
      alert("Failed to read clipboard. Please paste manually.");
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
</script>

<main>
  {#if $isLoading}
    <div class="loading-container">
      <p>Loading...</p>
    </div>
  {:else}
    <div class="header">
      <img src={logo} alt="Logo" class="logo" />
      <h1>{$t("title")}</h1>
      <div class="header-actions">
        <button
          on:click={() => (showSettingsModal = true)}
          class="button-icon settings-button"
          aria-label="Settings"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            ><circle cx="12" cy="12" r="3"></circle><path
              d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"
            ></path></svg
          >
        </button>
      </div>
    </div>

    <div class="card">
      <form on:submit|preventDefault={addDownload} class="download-form">
        <div class="input-group main-input-group">
          <!-- Combined input group -->
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
            title="Paste from clipboard">{@html icons.clipboard}</button
          >
          <button
            type="button"
            class="button-icon password-toggle-button"
            on:click={openPasswordModal}
            title="Set password"
          >
            {#if hasPassword}
              {@html icons.unlock}
            {:else}
              {@html icons.lock}
            {/if}
          </button>
        </div>
        <button type="submit" class="button button-primary add-download-button"
          >{$t("add_download")}</button
        >
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
              <th>{$t("table_header_requested_date")}</th>
              <th>{$t("table_header_requested_time")}</th>
              <th class="actions-header">{$t("table_header_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {#if downloads.length === 0}
              <tr>
                <td colspan="7" class="no-downloads-message">
                  {$t("no_downloads_message")}
                </td>
              </tr>
            {:else}
              {#each downloads as download (download.id)}
                <tr>
                  <td class="filename" title={download.file_name}
                    >{download.file_name || $t("file_name_na")}</td
                  >
                  <td>
                    <span
                      class="status status-{download.status
                        .toLowerCase()
                        .replace(/ /g, '-')}"
                    >
                      {download.status}
                    </span>
                  </td>
                  <td>
                    {download.file_size ? formatBytes(download.file_size) : "-"}
                  </td>
                  <td>
                    <div class="progress-container">
                      <div
                        class="progress-bar"
                        style="width: {getDownloadProgress(download)}%"
                      ></div>
                      <span class="progress-text"
                        >{getDownloadProgress(download)}%</span
                      >
                    </div>
                  </td>
                  <td>{new Date(download.requested_at).toLocaleDateString()}</td
                  >
                  <td>{new Date(download.requested_at).toLocaleTimeString()}</td
                  >
                  <td class="actions">
                    {#if download.status
                      .toLowerCase()
                      .includes("downloading") || download.status
                        .toLowerCase()
                        .includes("다운로드")}
                      <button
                        class="button-icon"
                        title={$t("action_pause")}
                        on:click={() => callApi(`/api/pause/${download.id}`)}
                        >{@html icons.pause}</button
                      >
                    {:else if download.status
                      .toLowerCase()
                      .includes("pending") || download.status
                        .toLowerCase()
                        .includes("대기")}
                      <button
                        class="button-icon"
                        title={$t("action_resume")}
                        on:click={() => callApi(`/api/resume/${download.id}`)}
                        >{@html icons.resume}</button
                      >
                    {/if}
                    {#if download.status
                      .toLowerCase()
                      .includes("failed") || download.status
                        .toLowerCase()
                        .includes("실패")}
                      <button
                        class="button-icon"
                        title={$t("action_retry")}
                        on:click={() => callApi(`/api/retry/${download.id}`)}
                        >{@html icons.retry}</button
                      >
                    {/if}
                    <button
                      class="button-icon danger"
                      title={$t("action_delete")}
                      on:click={() => deleteDownload(download.id)}
                      >{@html icons.delete}</button
                    >
                  </td>
                </tr>
              {/each}
            {/if}
          </tbody>
        </table>
      </div>

      <div class="pagination">
        <span class="page-info"
          >{$t("pagination_page_info", { currentPage, totalPages })}</span
        >
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
  {/if}

  <SettingsModal
    bind:showModal={showSettingsModal}
    {currentSettings}
    on:settingsChanged={(e) => (currentSettings = e.detail)}
    on:close={() => (showSettingsModal = false)}
  />

  {#if showPasswordModal}
    <PasswordModal
      bind:showModal={showPasswordModal}
      on:passwordSet={handlePasswordSet}
      on:close={() => (showPasswordModal = false)}
    />
  {/if}
</main>

<style>
  .loading-container {
    display: flex;
    justify-content: center;
    align-items: center;
    height: 80vh;
    font-size: 1.8rem;
    color: var(--text-secondary);
  }
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between; /* Changed to space-between */
    margin-bottom: 2rem;
    text-align: center;
    position: relative;
    padding: 0 1rem; /* Added padding for alignment */
  }
  .header-actions {
    display: flex;
    gap: 0.5rem;
  }
  .settings-button {
    color: var(--text-secondary);
  }
  .settings-button:hover {
    color: var(--text-primary);
  }
  .logo {
    width: 50px;
    height: 50px;
    /* Removed margin-right: 1rem; */
  }
  .header h1 {
    /* Added specific style for h1 in header */
    margin: 0; /* Remove default margin */
    flex-grow: 1; /* Allow h1 to take available space */
    text-align: center; /* Center the text */
  }
  .download-form {
    display: flex; /* Changed to flex */
    gap: 1rem;
    align-items: center;
    flex-wrap: wrap; /* Allow wrapping on smaller screens */
  }
  .input-group {
    flex-grow: 1; /* Allow input groups to grow */
    display: flex;
    gap: 0.5rem;
    position: relative;
  }
  .url-input {
    flex-grow: 1;
    padding-right: 6rem; /* Make space for two buttons */
    border-radius: 10px; /* Applied border-radius */
  }
  .clipboard-button {
    position: absolute;
    right: 3.2rem; /* Adjusted position for two buttons */
    top: 50%;
    transform: translateY(-50%);
    width: 2.5rem; /* Half size */
    height: 2.5rem; /* Half size */
    padding: 0;
    border-radius: 10px; /* Applied border-radius */
    background-color: var(--input-bg);
    border: 1px solid var(--input-border);
  }
  .clipboard-button:hover {
    background-color: var(--card-border);
  }
  .clipboard-button svg {
    width: 1rem;
    height: 1rem;
  }
  .password-toggle-button {
    position: absolute;
    right: 0.5rem;
    top: 50%;
    transform: translateY(-50%);
    width: 2.5rem;
    height: 2.5rem;
    padding: 0;
    border-radius: 10px;
    background-color: var(--input-bg);
    border: 1px solid var(--input-border);
  }
  .password-toggle-button:hover {
    background-color: var(--card-border);
  }
  .password-toggle-button svg {
    width: 1rem;
    height: 1rem;
  }
  .add-download-button {
    margin-left: auto; /* Push to the right */
    border-radius: 10px; /* Applied border-radius */
  }
  .table-container {
    overflow-x: auto;
    border-radius: 10px; /* Applied border-radius */
    border: 1px solid var(--card-border);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    white-space: nowrap;
  }
  th,
  td {
    padding: 1rem 1.25rem;
    text-align: left;
    border-bottom: 1px solid var(--card-border);
  }
  th {
    font-weight: 700;
    font-size: 0.9rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    background-color: var(--card-background);
  }
  tbody tr {
    transition: background-color 0.2s ease;
  }
  tbody tr:hover {
    background-color: rgba(var(--primary-color-rgb), 0.05);
  }
  tbody tr:last-child td {
    border-bottom: none;
  }
  .filename {
    max-width: 350px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .actions {
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
  }
  .actions-header {
    text-align: right;
  }
  .status {
    display: inline-block;
    padding: 0.4em 0.8em;
    font-size: 0.8rem;
    font-weight: 700;
    line-height: 1;
    text-align: center;
    white-space: nowrap;
    vertical-align: middle;
    border-radius: 10px; /* Applied border-radius */
    text-transform: capitalize;
  }
  .status-download-pending,
  .status-대기-중 {
    color: var(--text-primary); /* Changed to ensure visibility */
    background-color: var(--text-secondary);
  }
  .status-download-downloading,
  .status-다운로드-중 {
    color: #fff;
    background-color: var(--primary-color);
  }
  .status-download-done,
  .status-완료 {
    color: #fff;
    background-color: var(--success-color);
  }
  .status-download-failed,
  .status-실패 {
    color: #fff;
    background-color: hsl(0, 80%, 70%);
  }
  .progress-container {
    width: 100%;
    background-color: var(--card-border);
    border-radius: 10px; /* Applied border-radius */
    overflow: hidden;
    height: 1.5rem;
    display: flex;
    align-items: center;
    position: relative;
  }
  .progress-bar {
    height: 100%;
    background-color: var(--primary-color);
    transition: width 0.5s ease-in-out;
  }
  .progress-text {
    position: absolute;
    width: 100%;
    text-align: center;
    color: var(--text-primary);
    font-weight: 600;
    font-size: 0.8rem;
  }
  .button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.5rem 1rem;
    font-size: 0.9rem;
    font-weight: 600;
    border-radius: 10px; /* Applied border-radius */
    border: 1px solid transparent;
    cursor: pointer;
    transition:
      background-color 0.3s ease,
      border-color 0.3s ease,
      color 0.3s ease,
      box-shadow 0.3s ease;
    text-decoration: none;
    box-shadow: var(--shadow-light);
    background-color: var(--button-background); /* Explicitly set background */
  }
  .button:hover {
    background-color: var(--button-hover-background);
  }
  .button-primary {
    background-color: var(--primary-color);
    color: #fff; /* White text for primary button */
  }
  .button-primary:hover {
    background-color: var(--primary-hover);
  }
  .button-secondary {
    background-color: var(
      --button-secondary-background,
      #e0e0e0
    ); /* Default light gray */
    color: var(--button-secondary-text, #333); /* Default dark text */
  }
  .button-secondary:hover {
    background-color: var(--button-secondary-background-hover, #c0c0c0);
  }

  /* Theme-specific variables for button backgrounds and text */
  :root[data-theme="light"] {
    --button-background: #f0f0f0; /* Light gray for light theme buttons */
    --button-hover-background: #d0d0d0; /* Slightly darker gray on hover */
    --button-text: #333; /* Dark text for light theme buttons */

    --button-secondary-background: #e0e0e0;
    --button-secondary-text: #333;
    --button-secondary-background-hover: #c0c0c0;
  }

  :root[data-theme="dark"] {
    --button-background: #555; /* Dark gray for dark theme buttons */
    --button-hover-background: #777; /* Slightly lighter gray on hover */
    --button-text: #f0f0f0; /* Light text for dark theme buttons */

    --button-secondary-background: #555;
    --button-secondary-text: #f0f0f0;
    --button-secondary-background-hover: #777;
  }

  /* Apply the theme-specific text color to the button */
  .button {
    color: var(--button-text);
  }

  .button:disabled {
    background-color: var(
      --disabled-button-background,
      #ccc
    ); /* Default disabled background */
    color: var(--disabled-button-text, #666); /* Default disabled text */
    cursor: not-allowed;
    opacity: 0.7; /* Reduce opacity slightly */
  }

  :root[data-theme="light"] {
    --disabled-button-background: #e0e0e0;
    --disabled-button-text: #999;
  }

  :root[data-theme="dark"] {
    --disabled-button-background: #444;
    --disabled-button-text: #888;
  }

  .button-icon {
    background: none;
    border: none;
    padding: 0.3rem;
    cursor: pointer;
    color: var(--text-secondary); /* Default icon color */
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition:
      background-color 0.2s ease,
      color 0.2s ease;
  }
  .button-icon:hover {
    background-color: var(--card-border);
    color: var(--text-primary);
  }
  .button-icon.danger:hover {
    color: var(--danger-color);
  }
  .pagination {
    display: flex;
    justify-content: right;
    align-items: center;
    padding-top: 1.5rem;
    gap: 1rem;
  }
  .page-info {
    margin: 0 0.5rem;
    font-size: 0.9rem;
    color: var(--text-secondary);
  }
  .no-downloads-message {
    text-align: center;
    padding: 3rem;
    font-size: 1.2rem;
    color: var(--text-secondary);
    font-style: italic;
  }

  /* Mobile Responsiveness */
  @media (max-width: 768px) {
    .card {
      padding: 1rem;
    }

    .download-form {
      flex-direction: column;
      align-items: stretch;
    }

    .input-group {
      width: 100%;
    }

    .add-download-button {
      width: 100%;
    }

    .button {
      width: 100%;
    }

    .button-icon {
      padding: 0.2rem;
    }

    h1 {
      font-size: 2rem;
      letter-spacing: -0.02em;
    }

    th,
    td {
      padding: 0.6rem;
      font-size: 0.8rem;
    }

    .status {
      font-size: 0.7rem;
      padding: 0.2em 0.5em;
    }

    .pagination {
      flex-direction: column;
      gap: 0.5rem;
      padding-top: 1rem;
    }

    .page-info {
      font-size: 0.8rem;
    }

    .no-downloads-message {
      padding: 2rem;
      font-size: 1rem;
    }
  }
</style>
