<script>
  import { createEventDispatcher, onMount, onDestroy } from "svelte";
  import { theme } from "./theme.js";
  import { t, loadTranslations, isLoading } from "./i18n.js";
  import XIcon from "../icons/XIcon.svelte";
  import SettingsIcon from "../icons/SettingsIcon.svelte";
  import GitHubIcon from "./icons/GitHubIcon.svelte";
  import DockerIcon from "./icons/DockerIcon.svelte";
  import ConfirmModal from "./ConfirmModal.svelte";
  import { toast } from "svelte-sonner";
  import {
    authRequired,
    isAuthenticated,
    authUser,
    authManager,
  } from "./auth.js";
  import { api } from "./api.js";

  // Sub-components
  import GeneralSettings from "./settings/GeneralSettings.svelte";
  import ProxySettings from "./settings/ProxySettings.svelte";
  import AuthSettings from "./settings/AuthSettings.svelte";
  import TelegramSettings from "./settings/TelegramSettings.svelte";

  const dispatch = createEventDispatcher();

  const themeIcons = {
    light: "☀️",
    dark: "🌙",
    dracula: "🧛‍♂️",
    nord: "❄️",
    solarized: "🌞",
    monokai: "🎨",
    ocean: "🌊",
    system: "🖥️",
  };

  export let showModal;
  export let currentSettings;

  let settings = {};
  let selectedTheme = "system";
  let selectedLocale = "ko";

  let userProxies = [];
  let newProxyAddress = "";
  let newProxyDescription = "";
  let isAddingProxy = false;

  // 페이징 변수들
  let currentPage = 1;
  let itemsPerPage = 50; // 페이지당 50개만 표시
  $: totalPages = Math.ceil(userProxies.length / itemsPerPage);
  $: paginatedProxies = userProxies.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );
  let telegramGuideExpanded = false;
  let telegramSettingsExpanded = false;
  let detailedGuideExpanded = false;
  let fichierAccountExpanded = false;
  let fichierTestLoading = false;
  let fichierEditMode = false;

  function startFichierEdit() {
    fichierEditMode = true;
    settings.fichier_password = "";
  }

  async function clearFichierAccount() {
    settings.fichier_email = "";
    settings.fichier_password = "";
    fichierEditMode = true;
    toast.info($t("fichier_clear_toast"));
  }

  async function testFichierLogin() {
    if (!settings.fichier_email || !settings.fichier_password) {
      toast.error($t("fichier_test_empty"));
      return;
    }
    fichierTestLoading = true;
    try {
      const data = await api.request('/fichier/test-login', {
        method: "POST",
        body: JSON.stringify({
          email: settings.fichier_email,
          password: settings.fichier_password,
        }),
      });
      if (data.success) {
        toast.success(data.message || $t("fichier_test_login"));
      } else {
        toast.error(data.message || $t("fichier_test_login"));
      }
    } catch (e) {
      toast.error($t("fichier_test_error") + " " + e.message);
    } finally {
      fichierTestLoading = false;
    }
  }
  let showLogoutConfirm = false;

  // 버전 정보
  let versionInfo = {
    current_version: "v1.0.0",
    latest_version: null,
    update_available: false,
    error: null,
  };
  let isLoadingVersion = false;

  $: isSettingsLoading = !settings || Object.keys(settings).length === 0;

  function closeModal() {
    dispatch("close");
  }

  async function loadUserProxies() {
    try {
      const data = await api.getUserProxies(1, 1000); // Get all for internal pagination
      userProxies = data.proxies || [];
    } catch (error) {
      console.error("Proxy list load failed:", error);
      userProxies = [];
    }
  }

  async function addProxy() {
    if (!newProxyAddress.trim()) {
      toast.error($t("proxy_address_placeholder"));
      return;
    }

    isAddingProxy = true;
    try {
      await api.addUserProxy(newProxyAddress.trim(), newProxyDescription.trim());
      toast.success($t("proxy_added_success"));
      newProxyAddress = "";
      newProxyDescription = "";
      await loadUserProxies();
      dispatch("proxyChanged");
    } catch (error) {
      toast.error($t("proxy_add_failed", { error: error.message }));
    } finally {
      isAddingProxy = false;
    }
  }

  async function deleteProxy(proxyId) {
    try {
      await api.deleteUserProxy(proxyId);
      toast.success($t("proxy_deleted_success"));
      await loadUserProxies();
      dispatch("proxyChanged");
    } catch (error) {
      toast.error($t("proxy_delete_failed"));
    }
  }

  async function toggleProxy(proxyId) {
    try {
      await api.toggleUserProxy(proxyId);
      await loadUserProxies();
      dispatch("proxyChanged");
    } catch (error) {
      toast.error($t("proxy_toggle_failed"));
    }
  }

  async function testTelegramNotification() {
    if (!settings.telegram_bot_token || !settings.telegram_chat_id) {
      toast.error($t("telegram_test_missing_config"));
      return;
    }

    try {
      await api.request('/telegram/test', {
        method: "POST",
        headers: {
          Authorization: `Bearer ${localStorage.getItem("access_token")}`,
        },
        body: JSON.stringify({
          bot_token: settings.telegram_bot_token,
          chat_id: settings.telegram_chat_id,
        }),
      });
      toast.success($t("telegram_test_success"));
    } catch (error) {
      toast.error($t("telegram_test_failed") + ": " + error.message);
    }
  }

  let isInitialized = false;

  $: if (showModal && currentSettings && !isInitialized) {
    settings = {
      ...currentSettings,
      telegram_bot_token: currentSettings.telegram_bot_token || "",
      telegram_chat_id: currentSettings.telegram_chat_id || "",
      telegram_notify_success: currentSettings.telegram_notify_success === true,
      telegram_notify_failure:
        currentSettings.telegram_notify_failure !== false,
      telegram_notify_wait: currentSettings.telegram_notify_wait !== false,
      telegram_notify_start: currentSettings.telegram_notify_start === true,
      fichier_email: currentSettings.fichier_email || "",
      fichier_password: currentSettings.fichier_password || "",
    };
    selectedTheme = settings.theme || $theme;
    selectedLocale = localStorage.getItem("lang") || "ko";
    isInitialized = true;
  }

  $: if (!showModal) {
    settings = {};
    isInitialized = false;
    fichierEditMode = false;
  }

  $: if (showModal) {
    loadUserProxies();
  }

  async function saveSettings() {
    theme.set(selectedTheme);

    const settingsToSave = {
      ...settings,
      theme: selectedTheme,
      language: selectedLocale,
    };

    try {
      await api.saveSettings(settingsToSave);
      dispatch("settingsChanged", settings);
      closeModal();
    } catch (error) {
      console.error("Error saving settings:", error);
      alert($t("settings_save_failed", { status: error.message }));
    }
  }

  let environmentInfo = { is_standalone: false, is_docker: false };

  async function resetToDefault() {
    try {
      const data = await api.request('/default_download_path');
      environmentInfo = {
        is_standalone: data.is_standalone || false,
        is_docker: data.is_docker || false,
      };

      if (data.default_download_path) {
        settings = { ...settings, download_path: data.default_download_path };
      } else {
        settings = { ...settings, download_path: "/downloads" };
      }
    } catch (e) {
      settings = { ...settings, download_path: "/downloads" };
    }
  }

  async function selectFolder() {
    if (environmentInfo.is_docker) {
      toast.error("폴더 선택은 도커 환경에서 지원되지 않습니다");
      return;
    }

    try {
      const data = await api.selectFolder();
      if (data.path) {
        settings = { ...settings, download_path: data.path };
      }
    } catch (error) {
      toast.error(error.message || "폴더 선택에 실패했습니다");
    }
  }

  async function changeLocale(e) {
    selectedLocale = e.target.value;
    localStorage.setItem("lang", selectedLocale);
    await loadTranslations(selectedLocale);
  }

  function handleLogout() {
    showLogoutConfirm = true;
  }

  function confirmLogout() {
    authManager.logout();
    showLogoutConfirm = false;
    closeModal();
    setTimeout(() => {
      window.location.reload();
    }, 100);
  }

  function cancelLogout() {
    showLogoutConfirm = false;
  }

  async function loadVersionInfo() {
    if (isLoadingVersion) return;

    try {
      isLoadingVersion = true;
      versionInfo = await api.request('/version', {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("access_token")}`,
        },
      });
    } catch (error) {
      console.warn("[WARN] Failed to load version info:", error);
      versionInfo.error = "Failed to check version";
    } finally {
      isLoadingVersion = false;
    }
  }

  onMount(async () => {
    document.body.style.overflow = "hidden";

    try {
      const data = await api.request('/default_download_path');
      environmentInfo = {
        is_standalone: data.is_standalone || false,
        is_docker: data.is_docker || false,
      };
    } catch (error) {
      console.warn("[WARN] Failed to load environment info:", error);
    }

    loadVersionInfo();
  });
  onDestroy(() => {
    document.body.style.overflow = "";
  });
</script>

{#if showModal}
  <div
    class="modern-backdrop"
    role="dialog"
    aria-label="Settings"
    aria-modal="true"
    tabindex="0"
    on:keydown={(e) => {
      if (e.key === "Escape") closeModal();
    }}
  >
    <div
      class="modern-modal"
      on:click|stopPropagation
      on:keydown={() => {}}
      role="dialog"
      tabindex="-1"
    >
      {#if isSettingsLoading}
        <div class="modal-loading-container">
          <div class="modal-spinner"></div>
          <div class="modal-loading-text">{$t("loading_message")}</div>
        </div>
      {:else}
        <div class="modal-header">
          <div class="header-content">
            <div class="title-section">
              <div class="icon-wrapper">
                <SettingsIcon />
              </div>
              <div class="title-text">
                <h2>{$t("settings_title")}</h2>
                <p class="subtitle">{$t("settings_subtitle")}</p>
              </div>
            </div>
            <button class="close-button" on:click={closeModal}>
              <XIcon />
            </button>
          </div>
        </div>

        <div class="modal-body">
          {#if $authRequired && $isAuthenticated}
            <div class="form-group">
              <div class="auth-info-card">
                <div class="user-info-compact">
                  <div class="user-avatar">
                    <svg
                      width="20"
                      height="20"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    >
                      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                      <circle cx="12" cy="7" r="4" />
                    </svg>
                  </div>
                  <div class="user-details">
                    <span class="user-greeting">{$t("logged_in_as")}</span>
                    <strong class="user-name">{$authUser?.username}</strong>
                  </div>
                </div>
                <button
                  type="button"
                  class="logout-btn compact"
                  on:click={handleLogout}
                >
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  >
                    <path d="M18.36 6.64a9 9 0 1 1-12.73 0" />
                    <line x1="12" y1="2" x2="12" y2="12" />
                  </svg>
                  {$t("logout")}
                </button>
              </div>
            </div>
          {/if}

          <GeneralSettings
            bind:settings
            {environmentInfo}
            {selectedLocale}
            {selectedTheme}
            {themeIcons}
            {selectFolder}
            {resetToDefault}
            {changeLocale}
          />

          <ProxySettings
            {userProxies}
            bind:newProxyAddress
            bind:newProxyDescription
            {isAddingProxy}
            bind:currentPage
            {itemsPerPage}
            {totalPages}
            {paginatedProxies}
            {addProxy}
            {deleteProxy}
            {toggleProxy}
          />

          <AuthSettings
            bind:settings
            {currentSettings}
            bind:fichierAccountExpanded
            bind:fichierEditMode
            {fichierTestLoading}
            {startFichierEdit}
            {clearFichierAccount}
            {testFichierLogin}
          />

          <TelegramSettings
            bind:settings
            bind:telegramGuideExpanded
            bind:detailedGuideExpanded
            bind:telegramSettingsExpanded
            {testTelegramNotification}
          />

          <!-- 버전 정보 섹션 -->
          <div class="version-section">
            <h4 class="section-title">📊 {$t("version_info")}</h4>
            <div class="version-content">
              <div class="version-display">
                {#if isLoadingVersion}
                  <div class="version-loading">
                    <span class="loading-spinner"></span>
                    <span>{$t("checking_version")}</span>
                  </div>
                {:else if versionInfo.error}
                  <div class="version-simple">
                    <span class="version-text"
                      >{versionInfo.current_version}</span
                    >
                    <span class="version-status error"
                      >({$t("version_check_failed")})</span
                    >
                  </div>
                {:else if versionInfo.update_available}
                  <div class="version-simple">
                    <span class="version-text"
                      >{versionInfo.current_version} → {versionInfo.latest_version}</span
                    >
                    <span class="version-label update"
                      >🎉 {$t("update_available")}</span
                    >
                  </div>
                {:else}
                  <div class="version-simple">
                    <span class="version-text"
                      >{versionInfo.current_version}</span
                    >
                    <span class="version-label latest"
                      >✨ {$t("latest_version")}</span
                    >
                  </div>
                {/if}
              </div>
              <div class="version-links">
                <a
                  href="https://github.com/jshsakura/oc-proxy-downloader"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="version-link github-link"
                  title="GitHub Repository"
                  aria-label="GitHub Repository"
                >
                  <GitHubIcon width={20} height={20} />
                  <span>GitHub</span>
                </a>
                <a
                  href="https://hub.docker.com/r/jshsakura/oc-proxy-downloader"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="version-link docker-link"
                  title="Docker Hub"
                  aria-label="Docker Hub"
                >
                  <DockerIcon width={20} height={20} />
                  <span>Docker Hub</span>
                </a>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <button class="button button-secondary" on:click={closeModal}>
            {$t("button_cancel")}
          </button>
          <button class="button button-primary" on:click={saveSettings}>
            {$t("button_save")}
          </button>
        </div>
      {/if}
    </div>
  </div>
{/if}

{#if !$isLoading}
  <ConfirmModal
    bind:showModal={showLogoutConfirm}
    title={$t("logout_confirm_title")}
    message={$t("logout_confirm_message")}
    confirmText={$t("logout_confirm_yes")}
    cancelText={$t("logout_confirm_no")}
    isDeleteAction={true}
    on:confirm={confirmLogout}
    on:cancel={cancelLogout}
  />
{/if}

<style>
  .modern-backdrop {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(15, 23, 42, 0.7);
    backdrop-filter: blur(8px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 10000;
    animation: backdrop-fade-in 0.2s ease-out;
  }

  @keyframes backdrop-fade-in {
    from {
      opacity: 0;
      backdrop-filter: blur(0px);
    }
    to {
      opacity: 1;
      backdrop-filter: blur(8px);
    }
  }

  .modern-modal {
    background: var(--card-background);
    border-radius: 16px;
    box-shadow:
      0 25px 50px -12px rgba(0, 0, 0, 0.25),
      0 0 0 1px rgba(255, 255, 255, 0.05);
    width: 95vw;
    max-width: 800px;
    max-height: 90vh;
    min-height: 400px;
    overflow: hidden;
    animation: modal-slide-in 0.3s ease-out;
    position: relative;
    display: flex;
    flex-direction: column;
  }

  @keyframes modal-slide-in {
    from {
      opacity: 0;
      transform: translateY(-20px) scale(0.95);
    }
    to {
      opacity: 1;
      transform: translateY(0) scale(1);
    }
  }

  .modal-header {
    background: linear-gradient(
      135deg,
      var(--primary-color) 0%,
      var(--primary-hover, #1e40af) 100%
    );
    color: white;
    padding: 1.5rem 2rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    flex-shrink: 0;
  }

  .header-content {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
  }

  .title-section {
    display: flex;
    align-items: center;
    gap: 1rem;
    flex: 1;
  }

  .icon-wrapper {
    width: 44px;
    height: 44px;
    background: rgba(255, 255, 255, 0.15);
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.2);
  }

  .icon-wrapper :global(svg) {
    width: 22px;
    height: 22px;
    color: white;
  }

  .title-text h2 {
    margin: 0;
    font-size: 1.5rem;
    font-weight: 700;
    color: white;
  }

  .title-text .subtitle {
    margin: 0.25rem 0 0 0;
    font-size: 0.875rem;
    color: rgba(255, 255, 255, 0.8);
    font-weight: 400;
  }

  .close-button {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2.5rem;
    height: 2.5rem;
    border: none;
    background: rgba(255, 255, 255, 0.1);
    color: white;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s ease;
    flex-shrink: 0;
  }

  .close-button:hover {
    background: rgba(255, 255, 255, 0.2);
  }

  .close-button :global(svg) {
    width: 1.25rem;
    height: 1.25rem;
    color: white;
  }

  .modal-loading-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 300px;
    padding: 2rem 0;
  }

  .modal-spinner {
    width: 48px;
    height: 48px;
    border: 5px solid var(--card-border, #e0e0e0);
    border-top: 5px solid var(--primary-color, #0b6bcb);
    border-radius: 50%;
    animation: modal-spin 1s linear infinite;
    margin-bottom: 1.5rem;
  }

  @keyframes modal-spin {
    0% {
      transform: rotate(0deg);
    }
    100% {
      transform: rotate(360deg);
    }
  }

  .modal-loading-text {
    font-size: 1.1rem;
    color: var(--text-secondary, #666);
    font-weight: 600;
    letter-spacing: 0.05em;
  }

  /* 프록시 로딩 상태 */
  .proxy-loading-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2rem;
    gap: 1rem;
    text-align: center;
  }

  .proxy-spinner {
    width: 32px;
    height: 32px;
    border: 3px solid var(--card-border, #e0e0e0);
    border-top: 3px solid var(--primary-color, #0b6bcb);
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  /* 프록시 테이블 푸터 */
  .proxy-table-footer {
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

  .proxy-footer-info {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    margin: 0;
    text-align: left;
  }

  .proxy-count-info {
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--text-primary);
  }

  .proxy-pagination-buttons {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .proxy-page-number-btn {
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

  .proxy-page-number-btn:hover:not(.active) {
    background: var(--bg-secondary);
    border-color: var(--primary-color);
  }

  .proxy-page-number-btn.active {
    background: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
  }

  .proxy-page-number-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    background: var(--card-border);
  }

  .proxy-prev-next-btn {
    font-size: 18px;
    font-weight: bold;
  }

  .proxy-page-info {
    color: #6b7280;
    font-size: 0.85rem;
    font-weight: 400;
  }

  /* 테마별 프록시 페이지 번호 버튼 스타일 */
  :global(body.dark) .proxy-page-number-btn {
    background: #374151;
    border-color: #4b5563;
    color: #f3f4f6;
  }

  :global(body.dark) .proxy-page-number-btn:hover:not(.active) {
    background: #4b5563;
  }

  :global(body.dark) .proxy-page-number-btn:disabled {
    background: #4b5563;
  }

  :global(body.dracula) .proxy-page-number-btn {
    background: #44475a;
    border-color: #6272a4;
    color: #f8f8f2;
  }

  :global(body.dracula) .proxy-page-number-btn:hover:not(.active) {
    background: #6272a4;
  }

  :global(body.dracula) .proxy-page-number-btn:disabled {
    background: #6272a4;
  }

  /* 프록시 테이블 푸터 모바일 반응형 */
  @media (max-width: 768px) {
    .proxy-table-footer {
      flex-direction: column;
      gap: 1rem;
      padding: 1rem;
      align-items: center;
    }

    .proxy-footer-info {
      width: 100%;
      text-align: center;
      align-items: center;
    }

    .proxy-pagination-buttons {
      gap: 0.25rem;
    }

    .proxy-page-number-btn {
      width: 32px;
      height: 32px;
      font-size: 12px;
    }

    .proxy-prev-next-btn {
      font-size: 16px;
    }
  }

  .modal-body {
    padding: 2rem;
    flex: 1;
    overflow-y: auto;
    margin-bottom: 0;
    min-height: 0;
  }

  .form-group {
    margin-bottom: 1.5rem;
  }

  .form-group:last-child {
    margin-bottom: 0;
  }

  fieldset.form-group {
    border: none;
    padding: 0;
    margin-bottom: 1.5rem;
  }

  legend {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 600;
    font-size: 0.875rem;
    color: var(--text-primary);
    text-transform: uppercase;
    letter-spacing: 0.025em;
    padding: 0;
  }

  .proxy-management-title {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 600;
    font-size: 0.875rem;
    color: var(--text-primary);
    text-transform: uppercase;
    letter-spacing: 0.025em;
  }

  label {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 600;
    font-size: 0.875rem;
    color: var(--text-primary);
    text-transform: uppercase;
    letter-spacing: 0.025em;
  }

  .input-group {
    position: relative;
    display: flex;
    align-items: center;
  }

  .input {
    width: 100%;
    padding: 0.875rem 1rem;
    border: 2px solid var(--card-border, #e5e7eb);
    border-radius: 12px;
    background-color: var(--input-bg, #ffffff);
    color: var(--text-primary);
    font-size: 0.875rem;
    font-weight: 500;
    transition: all 0.2s ease;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  }

  .input-group .input {
    padding-right: 48px;
  }

  .path-input-group .input {
    padding-right: 88px;
  }

  .path-buttons {
    position: absolute;
    right: 8px;
    display: flex;
    gap: 4px;
    align-items: center;
  }

  .input:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px rgba(var(--primary-color-rgb, 59, 130, 246), 0.1);
  }

  .input-icon-button {
    position: absolute;
    right: 8px;
    width: 2.5rem;
    height: 2.5rem;
    padding: 0;
    border: none !important;
    background-color: var(--input-bg);
    color: var(--text-secondary);
    border-radius: 10px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition:
      background-color 0.2s ease,
      color 0.2s ease;
  }

  .input-icon-button.reset-button {
    right: 8px;
  }

  .input-icon-button:hover {
    background-color: var(--card-border);
    color: var(--text-primary);
  }

  .input-icon-button :global(svg) {
    width: 1rem;
    height: 1rem;
  }

  .theme-options {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.5rem;
    margin-top: 0.75rem;
  }

  .theme-option-label {
    cursor: pointer;
    display: block;
  }

  .theme-card {
    border: 2px solid var(--card-border, #e5e7eb);
    border-radius: 8px;
    padding: 0.4rem 0.25rem;
    text-align: center;
    transition: all 0.2s ease;
    font-size: 0.75rem;
    font-weight: 500;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.25rem;
    background: var(--card-background);
    color: var(--text-primary);
  }

  .theme-card:hover {
    border-color: var(--primary-color);
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
  }

  .theme-option-label input[type="radio"]:checked + .theme-card {
    border-color: var(--primary-color);
    background: rgba(var(--primary-color-rgb, 59, 130, 246), 0.05);
    box-shadow: 0 0 0 3px rgba(var(--primary-color-rgb, 59, 130, 246), 0.1);
  }

  .theme-icon {
    font-size: 1.2rem;
  }

  .light-theme-card {
    background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%) !important;
    color: #1e293b !important;
  }
  .dark-theme-card {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%) !important;
    color: #f8fafc !important;
  }
  .dracula-theme-card {
    background: linear-gradient(135deg, #282a36 0%, #21222c 100%) !important;
    color: #f8f8f2 !important;
  }
  .system-theme-card {
    background: linear-gradient(135deg, #64748b 0%, #475569 100%) !important;
    color: white !important;
  }
  .nord-theme-card {
    background: linear-gradient(135deg, #2e3440 0%, #3b4252 100%) !important;
    color: #eceff4 !important;
  }
  .solarized-theme-card {
    background: linear-gradient(135deg, #002b36 0%, #073642 100%) !important;
    color: #fdf6e3 !important;
  }
  .monokai-theme-card {
    background: linear-gradient(135deg, #272822 0%, #1e1f1c 100%) !important;
    color: #f8f8f2 !important;
  }
  .ocean-theme-card {
    background: linear-gradient(135deg, #0a192f 0%, #112240 100%) !important;
    color: #ccd6f6 !important;
  }

  .modal-footer {
    padding: 1.25rem 2rem;
    border-top: 1px solid var(--card-border, #e5e7eb);
    background: linear-gradient(
      135deg,
      rgba(var(--primary-color-rgb, 59, 130, 246), 0.03) 0%,
      rgba(var(--primary-color-rgb, 59, 130, 246), 0.01) 100%
    );
    backdrop-filter: blur(10px);
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 0.75rem;
    position: relative;
    z-index: 10;
    border-bottom-left-radius: 16px;
    border-bottom-right-radius: 16px;
    flex-shrink: 0;
  }

  /* 버전 정보 섹션 스타일 */
  .version-section {
    margin-top: 1.5rem;
    padding: 1rem;
    background: var(--bg-secondary, #f8f9fa);
    border-radius: 8px;
    border: 1px solid var(--card-border);
  }

  .section-title {
    margin: 0 0 1rem 0;
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--text-primary);
  }

  .version-display {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .version-loading {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--text-secondary);
    font-size: 0.875rem;
  }

  .loading-spinner {
    width: 16px;
    height: 16px;
    border: 2px solid var(--card-border);
    border-top: 2px solid var(--primary-color);
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  .version-simple {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .version-text {
    font-weight: 600;
    color: var(--text-primary);
    font-size: 0.875rem;
  }

  .version-status {
    font-size: 0.8rem;
    font-weight: 500;
  }

  .version-status.error {
    color: var(--text-secondary);
  }

  .version-status.update {
    color: var(--warning-color);
    font-weight: 600;
  }

  .version-status.latest {
    color: var(--success-color, #10b981);
    font-weight: 500;
  }

  .version-label {
    display: inline-flex;
    align-items: center;
    padding: 0.125rem 0.5rem;
    border-radius: 8px;
    font-size: 0.7rem;
    font-weight: 500;
    margin-left: 0.5rem;
  }

  .version-label.update {
    background: #f59e0b;
    color: white;
  }

  .version-label.latest {
    background: #10b981;
    color: white;
  }

  .version-links {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.75rem;
  }

  .version-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    padding: 0.6rem 0.75rem;
    border: 1px solid var(--card-border);
    border-radius: 8px;
    color: var(--text-secondary);
    text-decoration: none;
    transition: all 0.2s ease;
    background: var(--card-background);
    font-size: 0.875rem;
    font-weight: 500;
    line-height: 1;
    vertical-align: middle;
  }

  .version-link:hover {
    background: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
  }

  .button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0.75rem 1.5rem;
    font-size: 0.875rem;
    font-weight: 600;
    border-radius: 12px;
    border: 2px solid transparent;
    cursor: pointer;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    text-decoration: none;
    min-width: 90px;
    letter-spacing: 0.025em;
    position: relative;
    overflow: hidden;
  }

  .button-primary {
    background: linear-gradient(
      135deg,
      var(--primary-color) 0%,
      var(--primary-hover, #1e40af) 100%
    );
    color: white;
    box-shadow:
      0 2px 4px rgba(0, 0, 0, 0.1),
      0 1px 3px rgba(0, 0, 0, 0.08);
    border: 2px solid rgba(255, 255, 255, 0.1);
  }

  .button-primary:hover {
    background: linear-gradient(
      135deg,
      var(--primary-hover, #1e40af) 0%,
      var(--primary-color) 100%
    );
    border-color: rgba(255, 255, 255, 0.2);
  }

  .button-primary:active {
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  }

  .button-secondary {
    background: var(--card-background);
    color: var(--text-secondary);
    border-color: var(--card-border, #e5e7eb);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  }

  .button-secondary:hover {
    background: var(
      --button-secondary-background-hover,
      var(--bg-secondary, #f8fafc)
    );
    border-color: var(--primary-color);
    color: var(--text-primary);
  }

  .button-secondary:active {
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  }

  @media (max-height: 700px) {
    .modern-modal {
      max-height: 95vh;
      min-height: 300px;
    }

    .modal-header {
      padding: 1rem 1.5rem;
    }

    .modal-body {
      padding: 1.5rem;
    }

    .modal-footer {
      padding: 1rem 1.5rem;
    }

    .title-text h2 {
      font-size: 1.25rem;
    }

    .title-text .subtitle {
      font-size: 0.8rem;
    }
  }

  @media (max-width: 640px) {
    .modern-modal {
      width: 95vw;
      height: 80vh;
      max-height: 80vh;
      margin: 0.5rem;
    }

    .modern-backdrop {
      padding: 1rem;
      align-items: flex-start;
      padding-top: 2rem;
      padding-bottom: 3rem;
    }

    .theme-options {
      grid-template-columns: repeat(4, 1fr);
    }

    .button {
      flex: 1;
      justify-content: center;
    }
  }

  .proxy-management {
    margin-top: 1.5rem;
    margin-bottom: 0;
  }

  .proxy-form-section {
    margin-top: 0;
    margin-bottom: 1rem;
  }

  .proxy-list-section {
    margin-top: 0;
  }

  .telegram-notifications {
    margin-top: 1.5rem;
  }

  .telegram-header {
    width: 100%;
    background: var(--card-background);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    cursor: pointer;
    transition: all 0.2s ease;
    text-align: left;
  }

  .telegram-header + .telegram-header {
    margin-top: 0.5rem;
  }

  .telegram-header:hover {
    background: var(--bg-secondary, #f8f9fa);
    border-color: var(--primary-color);
    box-shadow: var(--shadow-light);
  }

  .telegram-info {
    flex: 1;
  }

  .telegram-desc {
    margin: 0;
    color: var(--text-primary);
    font-size: 0.9rem;
    line-height: 1.4;
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  /* 헤더 보조 문구 — 부모 <button> 의 기본 색(black)을 상속하지 않게
     명시적으로 테마 변수 사용. 누락 시 라이트 모드에서 검정 고정으로
     보여 다크/드라큘라 테마와 안 맞는 문제가 있었음. */
  .telegram-sub {
    margin: 0.25rem 0 0 0;
    color: var(--text-secondary);
    font-size: 0.8rem;
    line-height: 1.4;
    font-weight: 400;
  }

  .toggle-chevron {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 6px;
    background: var(--bg-secondary, #f8f9fa);
    color: var(--text-secondary);
    transition: all 0.2s ease;
    margin-left: 1rem;
  }

  .toggle-chevron svg {
    transition: transform 0.3s ease;
    transform: rotate(0deg);
  }

  .toggle-chevron.expanded svg {
    transform: rotate(180deg);
  }

  .telegram-header:hover .toggle-chevron {
    background: var(--primary-color);
    color: white;
  }

  .telegram-accordion {
    border: 1px solid var(--card-border);
    border-radius: 8px;
    overflow: hidden;
    background: var(--card-background);
    animation: slideDown 0.2s ease-out;
    margin-bottom: 0.5rem;
  }

  @keyframes slideDown {
    from {
      opacity: 0;
      transform: translateY(-10px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  .accordion-content {
    padding: 1.5rem;
    border-top: none;
  }

  .telegram-input-group {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    margin-bottom: 1.5rem;
  }

  .input-field {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .input-field label {
    font-weight: 500;
    color: var(--text-primary);
    font-size: 0.875rem;
  }

  .telegram-token-input,
  .telegram-chat-input {
    font-family: "Courier New", monospace;
    font-size: 0.875rem;
    background: var(--input-background);
    border: 1px solid var(--input-border);
    border-radius: 6px;
    padding: 0.75rem;
    transition: border-color 0.2s ease;
  }

  .telegram-token-input:focus,
  .telegram-chat-input:focus {
    outline: none;
    border-color: var(--primary-color);
    box-shadow: 0 0 0 3px rgba(var(--primary-color-rgb), 0.1);
  }

  .input-hint {
    color: var(--text-secondary);
    font-size: 0.75rem;
    margin-top: 0.25rem;
  }

  .telegram-options {
    margin-bottom: 1.5rem;
    padding: 1rem;
    background: var(--bg-secondary, #f8f9fa);
    border-radius: 6px;
    border: 1px solid var(--card-border);
  }

  .telegram-checkbox-group {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .telegram-checkbox-label {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    cursor: pointer;
    font-size: 0.875rem;
    padding: 0.5rem;
    border-radius: 4px;
    transition: background-color 0.2s ease;
  }

  .telegram-checkbox-label:hover {
    background: var(--card-background);
  }

  .telegram-checkbox-label input[type="checkbox"] {
    width: 16px;
    height: 16px;
    cursor: pointer;
  }

  .telegram-checkbox-text {
    color: var(--text-primary);
    font-weight: 500;
  }

  .telegram-option-description {
    margin-top: -0.25rem;
    margin-left: 2rem;
    color: var(--text-secondary);
    font-size: 0.75rem;
    line-height: 1.3;
    padding-bottom: 0.5rem;
  }

  .telegram-test-section {
    display: flex;
    justify-content: center;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-top: 1rem;
  }

  .test-telegram-button {
    padding: 0.75rem 1.5rem;
    font-size: 0.875rem;
    min-height: 2.5rem;
  }

  /* 1fichier 저장된 자격증명 카드 — 테마 변수만 사용 */
  .fichier-saved {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    padding: 1rem 1.25rem;
    background: var(--card-background);
    border: 1px solid var(--card-border);
    border-radius: 10px;
  }
  .fichier-saved-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
  .fichier-saved-icon {
    flex-shrink: 0;
    width: 1.75rem;
    height: 1.75rem;
    border-radius: 50%;
    background: rgba(var(--primary-color-rgb), 0.12);
    color: var(--primary-color);
    font-weight: 700;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 0.95rem;
  }
  .fichier-saved-text {
    display: flex;
    flex-direction: column;
    gap: 0.125rem;
    min-width: 0;
    flex: 1;
  }
  .fichier-saved-email {
    font-weight: 600;
    color: var(--text-primary);
    font-size: 0.95rem;
    word-break: break-all;
  }
  .fichier-saved-sub {
    color: var(--text-secondary);
    font-size: 0.78rem;
  }
  .fichier-saved-actions {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  .fichier-danger-button {
    background: var(--danger-color) !important;
    color: #fff !important;
    border-color: var(--danger-color) !important;
  }
  .fichier-inline-link {
    color: var(--primary-color);
    text-decoration: none;
  }
  .fichier-inline-link:hover {
    text-decoration: underline;
  }

  /* Telegram Setup Guide Styles */
  .telegram-setup-guide {
    background: linear-gradient(
      135deg,
      rgba(59, 130, 246, 0.05) 0%,
      rgba(147, 197, 253, 0.05) 100%
    );
    border: 1px solid rgba(59, 130, 246, 0.15);
    border-radius: 12px;
    padding: 1.5rem;
    margin-bottom: 2rem;
  }

  .setup-guide-header {
    text-align: center;
    margin-bottom: 1.5rem;
  }

  .guide-title {
    margin: 0 0 0.5rem 0;
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--primary-color);
  }

  .guide-description {
    margin: 0;
    color: var(--text-secondary);
    font-size: 0.875rem;
    line-height: 1.5;
  }

  .setup-steps {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 1.5rem;
    margin-bottom: 1.5rem;
  }

  .setup-step {
    background: var(--card-background);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 1.25rem;
    transition: all 0.2s ease;
  }

  .setup-step:hover {
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  }

  .step-header {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.75rem;
  }

  .step-icon {
    font-size: 1.5rem;
    line-height: 1;
  }

  .step-title {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
  }

  .step-description {
    margin: 0 0 1rem 0;
    color: var(--text-secondary);
    font-size: 0.875rem;
    line-height: 1.5;
  }

  .telegram-link {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 1rem;
    background: linear-gradient(
      135deg,
      var(--primary-color) 0%,
      var(--primary-hover, #1e40af) 100%
    );
    color: white;
    text-decoration: none;
    border-radius: 6px;
    font-size: 0.875rem;
    font-weight: 500;
    transition: all 0.2s ease;
    border: none;
    cursor: pointer;
  }

  .telegram-link:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(var(--primary-color-rgb, 59, 130, 246), 0.3);
    color: white;
    text-decoration: none;
  }

  .botfather-link {
    background: linear-gradient(135deg, #0088cc 0%, #006ba6 100%);
  }

  .getid-link {
    background: linear-gradient(135deg, #28a745 0%, #20853e 100%);
  }

  .detailed-guide {
    border-top: 1px solid var(--card-border);
    padding-top: 1.5rem;
  }

  .guide-header-button {
    width: 100%;
    background: var(--card-background);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    cursor: pointer;
    transition: all 0.2s ease;
    text-align: left;
  }

  .guide-header-button:hover {
    background: var(--bg-secondary, #f8f9fa);
    border-color: var(--primary-color);
    box-shadow: var(--shadow-light);
  }

  .guide-info {
    flex: 1;
  }

  .guide-desc {
    margin: 0;
    color: var(--text-primary);
    font-size: 0.9rem;
    line-height: 1.4;
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .guide-accordion {
    border: 1px solid var(--card-border);
    border-radius: 8px;
    overflow: hidden;
    background: var(--card-background);
    animation: slideDown 0.2s ease-out;
  }

  .guide-accordion-content {
    padding: 1.5rem;
    border-top: none;
  }

  .guide-header-button .toggle-chevron {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 6px;
    background: var(--bg-secondary, #f8f9fa);
    color: var(--text-secondary);
    transition: all 0.2s ease;
    margin-left: 1rem;
  }

  .guide-header-button .toggle-chevron svg {
    transition: transform 0.3s ease;
    transform: rotate(0deg);
  }

  .guide-header-button .toggle-chevron.expanded svg {
    transform: rotate(180deg);
  }

  .guide-header-button:hover .toggle-chevron {
    background: var(--primary-color);
    color: white;
  }

  .guide-steps {
    margin: 0 0 1rem 0;
    padding-left: 1.5rem;
    color: var(--text-primary);
  }

  .guide-steps li {
    margin-bottom: 0.5rem;
    line-height: 1.5;
    font-size: 0.875rem;
  }

  .guide-note {
    background: rgba(59, 130, 246, 0.1);
    border: 1px solid rgba(59, 130, 246, 0.2);
    border-radius: 6px;
    padding: 0.75rem;
    font-size: 0.875rem;
    color: var(--text-primary);
    line-height: 1.5;
  }

  /* Dark theme adjustments */
  :global(body.dark) .telegram-setup-guide {
    background: linear-gradient(
      135deg,
      rgba(59, 130, 246, 0.08) 0%,
      rgba(147, 197, 253, 0.08) 100%
    );
  }

  :global(body.dark) .setup-step:hover {
    box-shadow: 0 2px 8px rgba(255, 255, 255, 0.08);
  }

  :global(body.dark) .guide-note {
    background: rgba(59, 130, 246, 0.15);
  }

  /* Dracula theme adjustments */
  :global(body.dracula) .telegram-setup-guide {
    background: linear-gradient(
      135deg,
      rgba(139, 233, 253, 0.08) 0%,
      rgba(189, 147, 249, 0.08) 100%
    );
    border-color: rgba(139, 233, 253, 0.2);
  }

  :global(body.dracula) .guide-note {
    background: rgba(139, 233, 253, 0.15);
    border-color: rgba(139, 233, 253, 0.3);
  }

  .proxy-add-section {
    margin-bottom: 1rem;
  }

  .proxy-input-group {
    display: grid;
    grid-template-columns: 2fr 1fr auto;
    gap: 0.5rem;
    align-items: end;
  }

  .proxy-address-input {
    grid-column: 1;
  }

  .proxy-description-input {
    grid-column: 2;
  }

  .proxy-add-button {
    grid-column: 3;
    white-space: nowrap;
    padding: 0.75rem 1rem;
    height: auto;
    min-height: 2.5rem;
  }

  .proxy-empty-state {
    text-align: center;
    padding: 2rem;
    background: var(--bg-secondary, #f8f9fa);
    border-radius: 8px;
    color: var(--text-secondary);
  }

  .proxy-empty-state p {
    margin: 0 0 0.5rem 0;
    font-weight: 500;
  }

  .proxy-empty-state small {
    opacity: 0.7;
  }

  .proxy-table-container {
    max-height: 250px;
    min-height: 60px;
    overflow-y: auto;
    overflow-x: hidden;
    border: 1px solid var(--card-border);
    border-radius: 8px;
    width: 100%;
  }

  .proxy-table-wrapper {
    overflow-x: auto;
    width: 100%;
  }

  .proxy-table {
    width: 100%;
    min-width: 700px;
    border-collapse: collapse;
    table-layout: auto;
    display: table !important;
  }

  .proxy-table thead {
    display: table-header-group !important;
  }

  .proxy-table tbody {
    display: table-row-group !important;
  }

  .proxy-table tr {
    display: table-row !important;
  }

  .proxy-table th,
  .proxy-table td {
    display: table-cell !important;
  }

  .proxy-table th,
  .proxy-table td {
    padding: 0.4rem 0.5rem;
    text-align: left;
    border-bottom: 1px solid var(--card-border);
    font-size: 0.85rem;
    vertical-align: middle;
    white-space: nowrap;
    min-width: fit-content;
    line-height: 1.3;
  }

  .proxy-table tbody tr:last-child td {
    border-bottom: 1px solid var(--card-border);
  }

  .proxy-table th:first-child,
  .proxy-table td:first-child {
    min-width: 200px;
    max-width: 300px;
  }

  .text-center {
    text-align: center !important;
  }

  .proxy-table td:nth-child(1) {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-all;
  }

  .proxy-table th {
    background: var(--bg-secondary);
    font-weight: 600;
    position: sticky;
    top: 0;
    text-align: center;
    border-bottom: 2px solid var(--card-border) !important;
  }

  .proxy-table th:first-child {
    text-align: left;
  }

  .proxy-address {
    position: relative;
  }

  .proxy-address-content {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    max-width: 100%;
  }

  .proxy-url {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .copy-proxy-button {
    background: var(--card-background);
    border: 1px solid var(--card-border);
    border-radius: 6px;
    padding: 6px;
    cursor: pointer;
    color: var(--text-secondary);
    transition: all 0.2s ease;
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    min-width: 28px;
    max-width: 28px;
    display: flex !important;
    align-items: center;
    justify-content: center;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
    opacity: 1;
    visibility: visible;
  }

  .copy-proxy-button:hover {
    background-color: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
    transform: scale(1.05);
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
  }

  .copy-proxy-button:active {
    transform: scale(0.95);
  }

  .copy-proxy-button :global(svg) {
    width: 14px;
    height: 14px;
  }

  .proxy-description {
    display: block;
    opacity: 0.7;
    font-style: italic;
    margin-top: 0.25rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .proxy-actions {
    padding: 0.25rem !important;
  }

  .proxy-action-buttons {
    display: flex !important;
    gap: 0.25rem;
    justify-content: center;
  }

  .proxy-action-btn {
    background: none;
    border: none;
    cursor: pointer;
    padding: 0.25rem;
    border-radius: 4px;
    font-size: 0.75rem;
    transition: all 0.2s;
    min-width: 24px;
    height: 24px;
    display: flex !important;
    align-items: center;
    justify-content: center;
  }

  .proxy-action-btn:hover {
    transform: scale(1.05);
  }

  .toggle-btn.active {
    background-color: rgba(34, 197, 94, 0.1);
    color: #22c55e;
  }

  .toggle-btn.inactive {
    background-color: rgba(156, 163, 175, 0.1);
    color: #9ca3af;
  }

  .delete-btn {
    background-color: rgba(239, 68, 68, 0.1);
    color: #ef4444;
  }

  .delete-btn:hover {
    background-color: #ef4444;
    color: white;
  }

  .proxy-type-badge,
  .proxy-status-badge {
    display: inline-block;
    padding: 0.2rem 0.8rem;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 500;
  }

  .proxy-type-badge.list {
    background: #e1f5fe;
    color: #0277bd;
  }

  .proxy-type-badge.single {
    background: #f3e5f5;
    color: #7b1fa2;
  }

  .proxy-status-badge.active {
    background: #e8f5e8;
    color: #2e7d32;
  }

  .proxy-status-badge.inactive {
    background: #fafafa;
    color: #616161;
  }

  .proxy-date {
    white-space: nowrap;
  }

  /* Auth Info Section Styles */
  .auth-info-section {
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 1rem;
    margin-bottom: 1.5rem;
    background: var(--bg-secondary);
  }

  .auth-section-title {
    margin: 0 0 1rem 0;
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
  }

  .auth-info-card {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem;
    background: var(--bg-secondary);
    border: 1px solid var(--card-border);
    border-radius: 12px;
    gap: 1rem;
  }

  .user-info-compact {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .user-avatar {
    width: 2.5rem;
    height: 2.5rem;
    background: var(--primary-color);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.2rem;
    color: white;
    overflow: hidden;
  }

  .user-details {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }

  .user-greeting {
    font-size: 0.8rem;
    color: var(--text-secondary);
    line-height: 1;
  }

  .user-name {
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
    line-height: 1.2;
  }

  .logout-btn {
    background: var(--danger-color);
    color: white;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: 8px;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .logout-btn.compact {
    padding: 0.6rem 0.8rem;
    font-size: 0.8rem;
  }

  .logout-btn:hover {
    background: var(--danger-hover);
  }

  @media (max-width: 600px) {
    .auth-info-card {
      flex-direction: column;
      align-items: stretch;
      gap: 1rem;
    }

    .user-info-compact {
      justify-content: flex-start;
    }

    .logout-btn {
      align-self: stretch;
      width: 100%;
      justify-content: center;
      margin-top: 0.5rem;
    }
  }

  .proxy-actions {
    white-space: nowrap;
  }

  .proxy-row.inactive {
    opacity: 0.6;
  }

  @media (max-width: 768px) {
    .proxy-input-group {
      grid-template-columns: 1fr;
      grid-template-rows: auto auto auto;
      gap: 0.75rem;
    }

    .proxy-address-input,
    .proxy-description-input,
    .proxy-add-button {
      grid-column: 1;
      width: 100%;
    }

    .proxy-add-button {
      justify-self: stretch;
    }

    .proxy-table-wrapper {
      overflow-x: auto;
    }

    .proxy-table-container {
      font-size: 0.75rem;
    }
  }

  @media (max-width: 640px) {
    .proxy-input-group {
      gap: 1rem;
    }

    .proxy-table-wrapper {
      overflow-x: auto;
    }

    .proxy-table-container {
      font-size: 0.7rem;
    }

    .telegram-input-group {
      gap: 1rem;
    }

    .telegram-checkbox-group {
      gap: 1rem;
    }

    .telegram-test-section {
      margin-top: 1.5rem;
    }

    .test-telegram-button {
      width: 100%;
      justify-content: center;
    }

    /* Telegram Setup Guide Mobile Styles */
    .telegram-setup-guide {
      padding: 1rem;
      margin-bottom: 1.5rem;
    }

    .setup-steps {
      grid-template-columns: 1fr;
      gap: 1rem;
    }

    .setup-step {
      padding: 1rem;
    }

    .step-header {
      gap: 0.5rem;
    }

    .step-icon {
      font-size: 1.25rem;
    }

    .step-title {
      font-size: 0.9rem;
    }

    .telegram-link {
      padding: 0.5rem 0.75rem;
      font-size: 0.8rem;
      width: 100%;
      justify-content: center;
      text-align: center;
    }

    .guide-header-button {
      padding: 1rem;
    }

    .guide-desc {
      font-size: 0.875rem;
    }

    .guide-accordion-content {
      padding: 1rem;
    }

    .guide-steps {
      padding-left: 1rem;
    }

    .guide-steps li {
      font-size: 0.8rem;
    }

    .guide-note {
      padding: 0.5rem;
      font-size: 0.8rem;
    }
  }

  @media (max-width: 480px) {
    .proxy-table-wrapper {
      overflow-x: auto;
    }

    .proxy-table-container {
      font-size: 0.65rem;
    }
  }
</style>
