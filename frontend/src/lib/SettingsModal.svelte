<script>
  import { createEventDispatcher } from "svelte";
  import { theme } from "./theme.js";
  import { t, loadTranslations } from "./i18n.js";
  import HomeIcon from "../icons/HomeIcon.svelte";
  import XIcon from "../icons/XIcon.svelte";
  import SettingsIcon from "../icons/SettingsIcon.svelte";
  import CopyIcon from "../icons/CopyIcon.svelte";
  import ConfirmModal from "./ConfirmModal.svelte";
  import { toastMessage, showToast, showToastMsg } from "./toast.js";
  import { onMount, onDestroy } from "svelte";
  import {
    authRequired,
    isAuthenticated,
    authUser,
    authManager,
  } from "./auth.js";

  const dispatch = createEventDispatcher();

  const themeIcons = {
    light: "☀️",
    dark: "🌙",
    dracula: "🧛‍♂️",
    system: "🖥️",
  };

  export let showModal;
  export let currentSettings;

  let settings = { ...currentSettings };
  let selectedTheme = settings.theme || $theme;
  let selectedLocale = settings.language || "ko";
  let selectedLocaleWasSet = false;
  let initialSettingsLoaded = false;
  
  function getGravatarUrl(email, size = 40) {
    if (!email || !email.includes('@')) return null;
    
    const crypto = window.crypto || window.msCrypto;
    if (!crypto || !crypto.subtle) return null;
    
    return crypto.subtle.digest('SHA-256', new TextEncoder().encode(email.toLowerCase().trim()))
      .then(hashBuffer => {
        const hashArray = Array.from(new Uint8Array(hashBuffer));
        const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
        return `https://www.gravatar.com/avatar/${hashHex}?s=${size}&d=404`;
      })
      .catch(() => null);
  }
  
  let gravatarUrl = null;
  $: if ($authUser?.username) {
    getGravatarUrl($authUser.username).then(url => {
      gravatarUrl = url;
    });
  }

  let userProxies = [];
  let newProxyAddress = "";
  let newProxyDescription = "";
  let isAddingProxy = false;
  let telegramGuideExpanded = false;
  let telegramSettingsExpanded = false;
  let detailedGuideExpanded = false;
  let showLogoutConfirm = false;

  $: if (
    currentSettings &&
    currentSettings.download_path &&
    !initialSettingsLoaded
  ) {
    settings = {
      ...currentSettings,
      telegram_bot_token: currentSettings.telegram_bot_token || "",
      telegram_chat_id: currentSettings.telegram_chat_id || "",
      telegram_notify_success: currentSettings.telegram_notify_success || false,
      telegram_notify_failure: currentSettings.telegram_notify_failure || true,
      telegram_notify_wait: currentSettings.telegram_notify_wait !== false, // 기본값 true
    };
    selectedTheme = settings.theme || $theme;
    initialSettingsLoaded = true;
  }

  $: isLoading = !settings;

  $: if (showModal && !selectedLocaleWasSet) {
    selectedLocale = localStorage.getItem("lang") || "ko";
    selectedLocaleWasSet = true;
  }
  $: if (!showModal) {
    selectedLocaleWasSet = false;
    initialSettingsLoaded = false;
  }

  function closeModal() {
    dispatch("close");
  }

  async function loadUserProxies() {
    try {
      const response = await fetch("/api/proxies");
      if (response.ok) {
        userProxies = await response.json();
      }
    } catch (error) {
      console.error("Proxy list load failed:", error);
    }
  }

  async function addProxy() {
    if (!newProxyAddress.trim()) {
      showToastMsg($t("proxy_address_placeholder"), "error");
      return;
    }

    isAddingProxy = true;
    try {
      const response = await fetch("/api/proxies", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          address: newProxyAddress.trim(),
          description: newProxyDescription.trim(),
        }),
      });

      if (response.ok) {
        showToastMsg($t("proxy_added_success"), "success");
        newProxyAddress = "";
        newProxyDescription = "";
        await loadUserProxies();
        dispatch("proxyChanged");
      } else {
        const error = await response.text();
        showToastMsg($t("proxy_add_failed", { error }), "error");
      }
    } catch (error) {
      showToastMsg($t("proxy_add_error"), "error");
    } finally {
      isAddingProxy = false;
    }
  }

  async function deleteProxy(proxyId) {
    try {
      const response = await fetch(`/api/proxies/${proxyId}`, {
        method: "DELETE",
      });

      if (response.ok) {
        showToastMsg($t("proxy_deleted_success"), "success");
        await loadUserProxies();
        dispatch("proxyChanged");
      } else {
        showToastMsg($t("proxy_delete_failed"), "error");
      }
    } catch (error) {
      showToastMsg($t("proxy_delete_error"), "error");
    }
  }

  async function toggleProxy(proxyId) {
    try {
      const response = await fetch(`/api/proxies/${proxyId}/toggle`, {
        method: "PUT",
      });

      if (response.ok) {
        await loadUserProxies();
        dispatch("proxyChanged");
      } else {
        showToastMsg($t("proxy_toggle_failed"), "error");
      }
    } catch (error) {
      showToastMsg($t("proxy_toggle_error"), "error");
    }
  }

  function formatDate(dateString) {
    if (!dateString) return "-";
    const currentLocale = localStorage.getItem("lang") || "en";
    const date = new Date(dateString);
    const localeCode = currentLocale === "ko" ? "ko-KR" : "en-US";

    if (currentLocale === "ko") {
      return date.toLocaleDateString(localeCode, {
        year: "numeric",
        month: "long",
        day: "numeric",
      });
    } else {
      return date.toLocaleDateString(localeCode, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      });
    }
  }

  async function copyToClipboard(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        textArea.style.position = "fixed";
        textArea.style.left = "-999999px";
        textArea.style.top = "-999999px";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand("copy");
        textArea.remove();
      }
      showToastMsg($t("copy_success"), "success");
    } catch (error) {
      console.error("Clipboard copy failed:", error);
      showToastMsg($t("copy_failed"), "error");
    }
  }

  async function testTelegramNotification() {
    if (!settings.telegram_bot_token || !settings.telegram_chat_id) {
      showToastMsg($t("telegram_test_missing_config"), "error");
      return;
    }

    try {
      const response = await fetch("/api/telegram/test", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("access_token")}`,
        },
        body: JSON.stringify({
          bot_token: settings.telegram_bot_token,
          chat_id: settings.telegram_chat_id,
        }),
      });

      if (response.ok) {
        showToastMsg($t("telegram_test_success"), "success");
      } else {
        const errorData = await response.json();
        showToastMsg(
          $t("telegram_test_failed") + ": " + errorData.detail,
          "error"
        );
      }
    } catch (error) {
      console.error("Telegram test error:", error);
      showToastMsg($t("telegram_test_error"), "error");
    }
  }

  $: if (showModal) {
    loadUserProxies();
  }

  async function saveSettings() {
    theme.set(selectedTheme);

    settings.theme = selectedTheme;
    settings.language = selectedLocale;

    console.log("[DEBUG] Saving settings:", settings);

    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });

      console.log("[DEBUG] Save API response:", response.status);

      if (response.ok) {
        const responseData = await response.json();
        console.log("[DEBUG] Save response data:", responseData);

        if (localStorage.getItem("lang") !== selectedLocale) {
          localStorage.setItem("lang", selectedLocale);
          window.location.reload();
          return;
        }

        dispatch("settingsChanged", settings);
        closeModal();
      } else {
        console.error("[ERROR] Save failed:", response.status);
        let errorMessage = $t("settings_save_failed", {
          status: response.status,
        });

        if (response.status === 500) {
          errorMessage += `\n${$t("settings_save_error_server")}`;
        } else if (response.status === 403) {
          errorMessage += `\n${$t("settings_save_error_auth")}`;
        } else if (response.status === 404) {
          errorMessage += `\n${$t("settings_save_error_notfound")}`;
        }

        alert(errorMessage);
      }
    } catch (error) {
      console.error("Error saving settings:", error);
      alert("Error saving settings");
    }
  }

  async function resetToDefault() {
    try {
      console.log("[DEBUG] Calling API to get default path");
      const response = await fetch("/api/default_download_path");
      console.log("[DEBUG] API response received:", response.status);

      if (response.ok) {
        const data = await response.json();
        console.log("[DEBUG] Default path data:", data);
        if (data.path) {
          settings = { ...settings, download_path: data.path };
          console.log("[DEBUG] Reset to default path:", data.path);
        } else {
          settings = { ...settings, download_path: "/downloads" };
          console.log("[DEBUG] Reset to default: /downloads");
        }
      } else {
        console.warn(
          "[WARN] Default path API failed, using fallback:",
          response.status
        );
        settings = { ...settings, download_path: "/downloads" };
      }
    } catch (e) {
      console.warn("[WARN] Default path API error, using fallback:", e.message);
      settings = { ...settings, download_path: "/downloads" };
    }
  }

  function changeLocale(e) {
    selectedLocale = e.target.value;
  }

  function handleLogout() {
    showLogoutConfirm = true;
  }

  function confirmLogout() {
    authManager.logout();
    showLogoutConfirm = false;
    closeModal();
    // 로그아웃 후 페이지 새로고침으로 상태 완전 초기화
    setTimeout(() => {
      window.location.reload();
    }, 100);
  }

  function cancelLogout() {
    showLogoutConfirm = false;
  }

  onMount(() => {
    document.body.style.overflow = "hidden";
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
      {#if isLoading}
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
                    {#if gravatarUrl}
                      <img src={gravatarUrl} alt="User Avatar" on:error={() => gravatarUrl = null} />
                    {:else}
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>
                        <circle cx="12" cy="7" r="4"/>
                      </svg>
                    {/if}
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

          <div class="form-group">
            <label for="download-path">{$t("settings_download_path")}</label>
            <div class="input-group">
              <input
                id="download-path"
                type="text"
                class="input"
                bind:value={settings.download_path}
                placeholder={$t("download_path_placeholder_long")}
              />
              <button
                type="button"
                class="input-icon-button reset-button"
                on:click={resetToDefault}
                title={$t("reset_to_default_tooltip")}
                aria-label={$t("reset_to_default_tooltip")}
              >
                <HomeIcon />
              </button>
            </div>
          </div>

          <div class="form-group">
            <label for="locale">{$t("settings_language")}</label>
            <select
              id="locale"
              class="input"
              bind:value={selectedLocale}
              on:change={changeLocale}
            >
              <option value="ko">{$t("language_korean")}</option>
              <option value="en">{$t("language_english")}</option>
            </select>
          </div>

          <fieldset class="form-group">
            <legend>{$t("settings_theme")}</legend>
            <div class="theme-options">
              <label class="theme-option-label">
                <input
                  type="radio"
                  bind:group={selectedTheme}
                  value="light"
                  hidden
                />
                <div class="theme-card light-theme-card">
                  <span class="theme-icon" aria-label={$t("theme_light_aria")}
                    >{themeIcons.light}</span
                  >
                  <span>{$t("theme_light")}</span>
                </div>
              </label>
              <label class="theme-option-label">
                <input
                  type="radio"
                  bind:group={selectedTheme}
                  value="dark"
                  hidden
                />
                <div class="theme-card dark-theme-card">
                  <span class="theme-icon" aria-label={$t("theme_dark_aria")}
                    >{themeIcons.dark}</span
                  >
                  <span>{$t("theme_dark")}</span>
                </div>
              </label>
              <label class="theme-option-label">
                <input
                  type="radio"
                  bind:group={selectedTheme}
                  value="dracula"
                  hidden
                />
                <div class="theme-card dracula-theme-card">
                  <span class="theme-icon" aria-label={$t("theme_dracula_aria")}
                    >{themeIcons.dracula}</span
                  >
                  <span>{$t("theme_dracula")}</span>
                </div>
              </label>
              <label class="theme-option-label">
                <input
                  type="radio"
                  bind:group={selectedTheme}
                  value="system"
                  hidden
                />
                <div class="theme-card system-theme-card">
                  <span class="theme-icon" aria-label={$t("theme_system_aria")}
                    >{themeIcons.system}</span
                  >
                  <span>{$t("theme_system")}</span>
                </div>
              </label>
            </div>
          </fieldset>

          <div class="form-group proxy-management">
            <div class="proxy-management-title">{$t("proxy_management")}</div>
          </div>

          <div class="form-group proxy-form-section">
            <div class="proxy-input-group">
              <input
                type="text"
                class="input proxy-address-input"
                bind:value={newProxyAddress}
                placeholder={$t("proxy_add_address")}
              />
              <input
                type="text"
                class="input proxy-description-input"
                bind:value={newProxyDescription}
                placeholder={$t("proxy_add_description")}
              />
              <button
                class="button button-primary proxy-add-button"
                on:click={addProxy}
                disabled={isAddingProxy}
              >
                {isAddingProxy ? $t("adding_proxy") : $t("proxy_add_button")}
              </button>
            </div>
          </div>

          <div class="form-group proxy-list-section">
              {#if userProxies.length === 0}
                <div class="proxy-empty-state">
                  <p>{$t("proxy_empty_message")}</p>
                  <small>{$t("proxy_empty_description")}</small>
                </div>
              {:else}
                <div class="proxy-table-container">
                  <div class="proxy-table-wrapper">
                    <table class="proxy-table">
                      <thead>
                        <tr>
                          <th class="text-center">{$t("proxy_address")}</th>
                          <th class="text-center">{$t("proxy_type")}</th>
                          <th class="text-center">{$t("proxy_status")}</th>
                          <th class="text-center">{$t("proxy_added_date")}</th>
                          <th class="text-center">{$t("proxy_actions")}</th>
                        </tr>
                      </thead>
                    <tbody>
                      {#each userProxies as proxy (proxy.id)}
                        <tr
                          class="proxy-row {proxy.is_active
                            ? 'active'
                            : 'inactive'}"
                        >
                          <td class="proxy-address" title={proxy.address}>
                            <div class="proxy-address-content">
                              <span class="proxy-url">{proxy.address}</span>
                              <button
                                class="copy-proxy-button"
                                on:click={() => copyToClipboard(proxy.address)}
                                title={$t("proxy_copy_address")}
                                type="button"
                              >
                                <CopyIcon />
                              </button>
                            </div>
                            {#if proxy.description}
                              <small class="proxy-description"
                                >{proxy.description}</small
                              >
                            {/if}
                          </td>
                          <td class="text-center">
                            <span class="proxy-type-badge {proxy.proxy_type}">
                              {proxy.proxy_type === "list"
                                ? $t("proxy_type_list")
                                : $t("proxy_type_single")}
                            </span>
                          </td>
                          <td class="text-center">
                            <span
                              class="proxy-status-badge {proxy.is_active
                                ? 'active'
                                : 'inactive'}"
                            >
                              {proxy.is_active
                                ? $t("proxy_status_active")
                                : $t("proxy_status_inactive")}
                            </span>
                          </td>
                          <td class="proxy-date text-center">
                            {formatDate(proxy.added_at)}
                          </td>
                          <td class="proxy-actions">
                            <div class="proxy-action-buttons">
                              <button
                                class="proxy-action-btn toggle-btn {proxy.is_active
                                  ? 'active'
                                  : 'inactive'}"
                                on:click={() => toggleProxy(proxy.id)}
                                title={proxy.is_active
                                  ? $t("proxy_toggle_inactive")
                                  : $t("proxy_toggle_active")}
                                aria-label={proxy.is_active
                                  ? $t("proxy_toggle_inactive")
                                  : $t("proxy_toggle_active")}
                                type="button"
                              >
                                {#if proxy.is_active}
                                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="6" y="4" width="4" height="16"></rect>
                                    <rect x="14" y="4" width="4" height="16"></rect>
                                  </svg>
                                {:else}
                                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <polygon points="5,3 19,12 5,21"></polygon>
                                  </svg>
                                {/if}
                              </button>
                              <button
                                class="proxy-action-btn delete-btn"
                                on:click={() => deleteProxy(proxy.id)}
                                title={$t("proxy_delete")}
                                aria-label={$t("proxy_delete")}
                                type="button"
                              >
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                  <polyline points="3,6 5,6 21,6"></polyline>
                                  <path d="m19,6v14a2,2 0 0,1 -2,2H7a2,2 0 0,1 -2,-2V6m3,0V4a2,2 0 0,1 2,-2h4a2,2 0 0,1 2,2v2"></path>
                                  <line x1="10" y1="11" x2="10" y2="17"></line>
                                  <line x1="14" y1="11" x2="14" y2="17"></line>
                                </svg>
                              </button>
                            </div>
                          </td>
                        </tr>
                      {/each}
                    </tbody>
                    </table>
                  </div>
                </div>
              {/if}
          </div>

          <fieldset class="form-group telegram-notifications">
            <legend>{$t("telegram_notifications")}</legend>

            <!-- 텔레그램 설정 가이드 아코디언 -->
            <button
              type="button"
              class="telegram-header"
              on:click={() => (telegramGuideExpanded = !telegramGuideExpanded)}
            >
              <div class="telegram-info">
                <p class="telegram-desc">📚 {$t("telegram_setup_guide")}</p>
              </div>
              <div class="toggle-chevron" class:expanded={telegramGuideExpanded}>
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
                  <polyline points="6,9 12,15 18,9"></polyline>
                </svg>
              </div>
            </button>

            {#if telegramGuideExpanded}
              <div class="telegram-accordion">
                <div class="accordion-content">
                  <!-- 텔레그램 설정 가이드 -->
                  <div class="telegram-setup-guide">
                    <div class="setup-guide-header">
                      <h4 class="guide-title">🚀 {$t("telegram_setup_guide")}</h4>
                      <p class="guide-description">{$t("telegram_description")}</p>
                    </div>
                    
                    <div class="setup-steps">
                      <div class="setup-step">
                        <div class="step-header">
                          <span class="step-icon">🤖</span>
                          <h5 class="step-title">{$t("telegram_step1_title")}</h5>
                        </div>
                        <p class="step-description">{$t("telegram_step1_desc")}</p>
                        <a 
                          href="https://t.me/botfather" 
                          target="_blank" 
                          rel="noopener noreferrer"
                          class="telegram-link botfather-link"
                        >
                          🔗 {$t("telegram_botfather_link")}
                        </a>
                      </div>
                      
                      <div class="setup-step">
                        <div class="step-header">
                          <span class="step-icon">🆔</span>
                          <h5 class="step-title">{$t("telegram_step2_title")}</h5>
                        </div>
                        <p class="step-description">{$t("telegram_step2_desc")}</p>
                        <a 
                          href="https://t.me/userinfobot" 
                          target="_blank" 
                          rel="noopener noreferrer"
                          class="telegram-link getid-link"
                        >
                          🔗 {$t("telegram_getid_bot")}
                        </a>
                      </div>
                    </div>
                    
                    <div class="detailed-guide">
                      <button
                        type="button"
                        class="guide-header-button"
                        on:click={() => (detailedGuideExpanded = !detailedGuideExpanded)}
                      >
                        <div class="guide-info">
                          <p class="guide-desc">📋 {$t("telegram_guide_detailed")}</p>
                        </div>
                        <div class="toggle-chevron" class:expanded={detailedGuideExpanded}>
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
                            <polyline points="6,9 12,15 18,9"></polyline>
                          </svg>
                        </div>
                      </button>

                      {#if detailedGuideExpanded}
                        <div class="guide-accordion">
                          <div class="guide-accordion-content">
                            <ol class="guide-steps">
                              <li>{$t("telegram_guide_step1_detail")}</li>
                              <li>{$t("telegram_guide_step2_detail")}</li>
                              <li>{$t("telegram_guide_step3_detail")}</li>
                              <li>{$t("telegram_guide_step4_detail")}</li>
                              <li>{$t("telegram_guide_step5_detail")}</li>
                              <li>{$t("telegram_guide_step6_detail")}</li>
                            </ol>
                            <div class="guide-note">
                              💡 {$t("telegram_guide_group_note")}
                            </div>
                          </div>
                        </div>
                      {/if}
                    </div>
                  </div>
                </div>
              </div>
            {/if}

            <!-- 텔레그램 설정 아코디언 -->
            <button
              type="button"
              class="telegram-header"
              on:click={() => (telegramSettingsExpanded = !telegramSettingsExpanded)}
            >
              <div class="telegram-info">
                <p class="telegram-desc">⚙️ {$t("telegram_settings")}</p>
              </div>
              <div class="toggle-chevron" class:expanded={telegramSettingsExpanded}>
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
                  <polyline points="6,9 12,15 18,9"></polyline>
                </svg>
              </div>
            </button>

            {#if telegramSettingsExpanded}
              <div class="telegram-accordion">
                <div class="accordion-content">
                  <div class="telegram-input-group">
                    <div class="input-field">
                      <label for="telegram-bot-token"
                        >{$t("telegram_bot_token")}</label
                      >
                      <input
                        id="telegram-bot-token"
                        type="text"
                        class="input telegram-token-input"
                        bind:value={settings.telegram_bot_token}
                        placeholder="1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"
                      />
                      <small class="input-hint"
                        >{$t("telegram_bot_token_hint")}</small
                      >
                    </div>

                    <div class="input-field">
                      <label for="telegram-chat-id"
                        >{$t("telegram_chat_id")}</label
                      >
                      <input
                        id="telegram-chat-id"
                        type="text"
                        class="input telegram-chat-input"
                        bind:value={settings.telegram_chat_id}
                        placeholder="-1001234567890"
                      />
                      <small class="input-hint"
                        >{$t("telegram_chat_id_hint")}</small
                      >
                    </div>
                  </div>

                  <div class="telegram-options">
                    <div class="telegram-checkbox-group">
                      <label class="telegram-checkbox-label">
                        <input
                          type="checkbox"
                          bind:checked={settings.telegram_notify_success}
                        />
                        <span class="telegram-checkbox-text"
                          >✅ {$t("telegram_notify_success")}</span
                        >
                      </label>

                      <label class="telegram-checkbox-label">
                        <input
                          type="checkbox"
                          bind:checked={settings.telegram_notify_failure}
                        />
                        <span class="telegram-checkbox-text"
                          >❌ {$t("telegram_notify_failure")}</span
                        >
                      </label>

                      <label class="telegram-checkbox-label">
                        <input
                          type="checkbox"
                          bind:checked={settings.telegram_notify_wait}
                        />
                        <span class="telegram-checkbox-text"
                          >⏳ {$t("telegram_notify_wait")}</span
                        >
                      </label>
                      <div class="telegram-option-description">
                        {$t("telegram_notify_wait_description")}
                      </div>
                    </div>
                  </div>

                  <div class="telegram-test-section">
                    <button
                      class="button button-secondary test-telegram-button"
                      on:click={testTelegramNotification}
                      disabled={!settings.telegram_bot_token ||
                        !settings.telegram_chat_id}
                    >
                      🚀 {$t("telegram_test_notification")}
                    </button>
                  </div>
                </div>
              </div>
            {/if}
          </fieldset>
        </div>

        <div class="modal-footer">
          <div class="footer-left"></div>
          <div class="footer-right">
            <button class="button button-secondary" on:click={closeModal}>
              {$t("button_cancel")}
            </button>
            <button class="button button-primary" on:click={saveSettings}>
              {$t("button_save")}
            </button>
          </div>
        </div>
      {/if}
    </div>
  </div>
{/if}

{#if $showToast}
  <div class="toast">{$toastMessage}</div>
{/if}

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

<style>
  .modern-backdrop {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
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
    border: none;
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
    grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
    gap: 0.75rem;
    margin-top: 0.75rem;
  }

  .theme-option-label {
    cursor: pointer;
    display: block;
  }

  .theme-card {
    border: 2px solid var(--card-border, #e5e7eb);
    border-radius: 12px;
    padding: 0.75rem 0.5rem;
    text-align: center;
    transition: all 0.2s ease;
    font-size: 0.875rem;
    font-weight: 500;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
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
    font-size: 1.5rem;
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
    justify-content: space-between;
    align-items: center;
    position: relative;
    z-index: 10;
    border-bottom-left-radius: 16px;
    border-bottom-right-radius: 16px;
    flex-shrink: 0;
  }

  .footer-left {
    flex: 1;
  }

  .footer-right {
    display: flex;
    gap: 0.75rem;
    align-items: center;
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
      height: 85vh;
      max-height: 85vh;
      margin: 0.5rem;
    }
    
    .modern-backdrop {
      padding: 1rem;
      align-items: flex-start;
      padding-top: 2rem;
    }

    .theme-options {
      grid-template-columns: repeat(2, 1fr);
    }

    .footer-right {
      flex-direction: column;
      gap: 0.5rem;
      width: 100%;
    }

    .modal-footer {
      flex-direction: column;
      align-items: stretch;
    }

    .footer-left {
      display: none;
    }

    .button {
      width: 100%;
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
    margin-top: 1rem;
  }

  .test-telegram-button {
    padding: 0.75rem 1.5rem;
    font-size: 0.875rem;
    min-height: 2.5rem;
  }

  /* Telegram Setup Guide Styles */
  .telegram-setup-guide {
    background: linear-gradient(135deg, rgba(59, 130, 246, 0.05) 0%, rgba(147, 197, 253, 0.05) 100%);
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
    background: linear-gradient(135deg, var(--primary-color) 0%, var(--primary-hover, #1e40af) 100%);
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
    background: linear-gradient(135deg, rgba(59, 130, 246, 0.08) 0%, rgba(147, 197, 253, 0.08) 100%);
  }

  :global(body.dark) .setup-step:hover {
    box-shadow: 0 2px 8px rgba(255, 255, 255, 0.08);
  }

  :global(body.dark) .guide-note {
    background: rgba(59, 130, 246, 0.15);
  }

  /* Dracula theme adjustments */
  :global(body.dracula) .telegram-setup-guide {
    background: linear-gradient(135deg, rgba(139, 233, 253, 0.08) 0%, rgba(189, 147, 249, 0.08) 100%);
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
    min-height: 150px;
    overflow-y: auto;
    overflow-x: auto;
    border: 1px solid var(--card-border);
    border-radius: 8px;
    width: 100%;
  }

  .proxy-table-wrapper {
    overflow-x: auto;
  }

  .proxy-table {
    width: 100%;
    min-width: 600px;
    border-collapse: collapse;
    table-layout: fixed;
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
    padding: 0.5rem;
    text-align: left;
    border-bottom: 1px solid var(--card-border);
    font-size: 0.85rem;
    vertical-align: middle;
    white-space: nowrap;
  }

  .text-center {
    text-align: center !important;
  }


  .proxy-table td:nth-child(1) {
    white-space: normal;
    overflow: hidden;
    text-overflow: ellipsis;
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
    padding: 0.2rem 0.5rem;
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

  .user-avatar img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: 50%;
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
