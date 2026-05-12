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
  import { clickOutside } from "./actions.js";

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
      use:clickOutside
      on:click_outside={closeModal}
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

  /* Common elements in SettingsModal body */
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

  .button-secondary {
    background: var(--card-background);
    color: var(--text-secondary);
    border-color: var(--card-border, #e5e7eb);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  }

  .button-secondary:hover {
    background: var(--bg-secondary, #f8fafc);
    border-color: var(--primary-color);
    color: var(--text-primary);
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
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

    .button {
      flex: 1;
      justify-content: center;
    }

    .auth-info-card {
      flex-direction: column;
      align-items: stretch;
      gap: 1rem;
    }

    .logout-btn {
      align-self: stretch;
      width: 100%;
      justify-content: center;
    }
  }
</style>
