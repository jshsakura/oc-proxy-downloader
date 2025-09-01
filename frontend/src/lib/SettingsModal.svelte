<script>
  import { createEventDispatcher } from "svelte";
  import { theme } from "./theme.js";
  import { t, loadTranslations } from "./i18n.js";
  import HomeIcon from "../icons/HomeIcon.svelte";
  import XIcon from "../icons/XIcon.svelte";
  import SettingsIcon from "../icons/SettingsIcon.svelte";
  import CopyIcon from "../icons/CopyIcon.svelte";
  import { toastMessage, showToast, showToastMsg } from "./toast.js";
  import { onMount, onDestroy } from "svelte";

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

  let userProxies = [];
  let newProxyAddress = "";
  let newProxyDescription = "";
  let isAddingProxy = false;

  $: if (currentSettings && currentSettings.download_path && !initialSettingsLoaded) {
    settings = { ...currentSettings };
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
          description: newProxyDescription.trim()
        })
      });

      if (response.ok) {
        showToastMsg($t("proxy_added_success"), "success");
        newProxyAddress = "";
        newProxyDescription = "";
        await loadUserProxies();
        dispatch('proxyChanged');
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
        method: "DELETE"
      });

      if (response.ok) {
        showToastMsg($t("proxy_deleted_success"), "success");
        await loadUserProxies();
        dispatch('proxyChanged');
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
        method: "PUT"
      });

      if (response.ok) {
        await loadUserProxies();
        dispatch('proxyChanged');
      } else {
        showToastMsg($t("proxy_toggle_failed"), "error");
      }
    } catch (error) {
      showToastMsg($t("proxy_toggle_error"), "error");
    }
  }

  function formatDate(dateString) {
    if (!dateString) return "-";
    const currentLocale = localStorage.getItem('lang') || 'en';
    const date = new Date(dateString);
    const localeCode = currentLocale === 'ko' ? 'ko-KR' : 'en-US';
    
    if (currentLocale === 'ko') {
      return date.toLocaleDateString(localeCode, {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      });
    } else {
      return date.toLocaleDateString(localeCode, {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
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
        document.execCommand('copy');
        textArea.remove();
      }
      showToastMsg($t("copy_success"), "success");
    } catch (error) {
      console.error("Clipboard copy failed:", error);
      showToastMsg($t("copy_failed"), "error");
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
        let errorMessage = $t("settings_save_failed", { status: response.status });
        
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
        console.warn("[WARN] Default path API failed, using fallback:", response.status);
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
    on:click={closeModal}
    on:keydown={(e) => {
      if (e.key === "Escape") closeModal();
    }}
  >
    <div class="modern-modal" on:click|stopPropagation on:keydown={() => {}} role="dialog" tabindex="-1">
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
                  <span class="theme-icon" aria-label={$t("theme_light_aria")} >{themeIcons.light}</span>
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
                  <span class="theme-icon" aria-label={$t("theme_dark_aria")} >{themeIcons.dark}</span>
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
                  <span class="theme-icon" aria-label={$t("theme_dracula_aria")} >{themeIcons.dracula}</span>
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
                  <span class="theme-icon" aria-label={$t("theme_system_aria")} >{themeIcons.system}</span>
                  <span>{$t("theme_system")}</span>
                </div>
              </label>
            </div>
          </fieldset>

          <fieldset class="form-group proxy-management">
            <legend>{$t("proxy_management")}</legend>
            
            <div class="proxy-add-section">
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

            <div class="proxy-list-section">
              {#if userProxies.length === 0}
                <div class="proxy-empty-state">
                  <p>{$t("proxy_empty_message")}</p>
                  <small>{$t("proxy_empty_description")}</small>
                </div>
              {:else}
                <div class="proxy-table-container">
                  <table class="proxy-table">
                    <thead>
                      <tr>
                        <th>{$t("proxy_address")}</th>
                        <th class="text-center">{$t("proxy_type")}</th>
                        <th class="text-center">{$t("proxy_status")}</th>
                        <th class="text-center">{$t("proxy_added_date")}</th>
                        <th class="text-center">{$t("proxy_actions")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each userProxies as proxy (proxy.id)}
                        <tr class="proxy-row {proxy.is_active ? 'active' : 'inactive'}">
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
                              <small class="proxy-description">{proxy.description}</small>
                            {/if}
                          </td>
                          <td class="text-center">
                            <span class="proxy-type-badge {proxy.proxy_type}">
                              {proxy.proxy_type === 'list' ? $t("proxy_type_list") : $t("proxy_type_single")}
                            </span>
                          </td>
                          <td class="text-center">
                            <span class="proxy-status-badge {proxy.is_active ? 'active' : 'inactive'}">
                              {proxy.is_active ? $t("proxy_status_active") : $t("proxy_status_inactive")}
                            </span>
                          </td>
                          <td class="proxy-date text-center">
                            {formatDate(proxy.added_at)}
                          </td>
                          <td class="proxy-actions">
                            <div class="proxy-action-buttons">
                              <button
                                class="proxy-action-btn toggle-btn {proxy.is_active ? 'active' : 'inactive'}"
                                on:click={() => toggleProxy(proxy.id)}
                                title={proxy.is_active ? $t("proxy_toggle_inactive") : $t("proxy_toggle_active")}
                                type="button"
                              >
                                {proxy.is_active ? '⏸' : '▶'}
                              </button>
                              <button
                                class="proxy-action-btn delete-btn"
                                on:click={() => deleteProxy(proxy.id)}
                                title={$t("proxy_delete")}
                                type="button"
                              >
                                🗑
                              </button>
                            </div>
                          </td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                </div>
              {/if}
            </div>
          </fieldset>
        </div>

        <div class="modal-footer">
          <div class="footer-left">
          </div>
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
    background: linear-gradient(135deg, var(--primary-color) 0%, var(--primary-hover, #1e40af) 100%);
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
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
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
    transition: background-color 0.2s ease, color 0.2s ease;
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
    background: linear-gradient(135deg, 
      rgba(var(--primary-color-rgb, 59, 130, 246), 0.03) 0%,
      rgba(var(--primary-color-rgb, 59, 130, 246), 0.01) 100%);
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
    background: linear-gradient(135deg, var(--primary-color) 0%, var(--primary-hover, #1e40af) 100%);
    color: white;
    box-shadow: 
      0 2px 4px rgba(0, 0, 0, 0.1),
      0 1px 3px rgba(0, 0, 0, 0.08);
    border: 2px solid rgba(255, 255, 255, 0.1);
  }

  .button-primary:hover {
    background: linear-gradient(135deg, var(--primary-hover, #1e40af) 0%, var(--primary-color) 100%);
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
    background: var(--button-secondary-background-hover, var(--bg-secondary, #f8fafc));
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
      margin: 1rem;
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
    padding: 0.5rem 1rem;
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
    overflow-y: auto;
    overflow-x: hidden;
    border: 1px solid var(--card-border);
    border-radius: 8px;
    max-width: 100%;
    width: 100%;
  }

  .proxy-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    table-layout: fixed;
  }

  .proxy-table th,
  .proxy-table td {
    padding: 0.5rem;
    text-align: left;
    border-bottom: 1px solid var(--card-border);
    font-size: 0.85rem;
    vertical-align: middle;
  }

  .text-center {
    text-align: center !important;
  }

  .proxy-table th:nth-child(1), .proxy-table td:nth-child(1) { width: 35%; }
  .proxy-table th:nth-child(2), .proxy-table td:nth-child(2) { width: 12%; }
  .proxy-table th:nth-child(3), .proxy-table td:nth-child(3) { width: 12%; }
  .proxy-table th:nth-child(4), .proxy-table td:nth-child(4) { width: 26%; }
  .proxy-table th:nth-child(5), .proxy-table td:nth-child(5) { width: 15%; }

  .proxy-table td {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .proxy-table td:nth-child(1) {
    white-space: normal;
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
    display: flex;
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
    display: flex;
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
    display: flex;
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
    }

    .proxy-address-input,
    .proxy-description-input,
    .proxy-add-button {
      grid-column: 1;
    }

    .proxy-table-container {
      font-size: 0.8rem;
    }

    .proxy-address {
      max-width: 120px;
    }
  }
</style>
