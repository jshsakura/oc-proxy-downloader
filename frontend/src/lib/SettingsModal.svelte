<script>
  import { createEventDispatcher } from "svelte";
  import { theme } from "./theme.js";
  import { t, loadTranslations } from "./i18n.js";
  import FolderIcon from "../icons/FolderIcon.svelte";
  import XIcon from "../icons/XIcon.svelte";
  import SettingsIcon from "../icons/SettingsIcon.svelte";
  import { toastMessage, showToast, showToastMsg } from "./toast.js";
  import { onMount, onDestroy } from "svelte";

  // --- Icons ---
  // icons 객체 완전히 삭제

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

  // settings 동기화 시 언어도 동기화
  $: if (currentSettings && currentSettings.download_path) {
    settings = { ...currentSettings };
    selectedTheme = settings.theme || $theme;
    // selectedLocale = settings.language || "ko"; // 이 줄은 주석 처리 또는 삭제
  }

  // download_path가 있을 때만 로딩 false
  $: isLoading = !settings || !settings.download_path;

  $: if (showModal && !selectedLocaleWasSet) {
    selectedLocale = localStorage.getItem("lang") || "ko";
    selectedLocaleWasSet = true;
  }
  $: if (!showModal) {
    selectedLocaleWasSet = false;
  }

  const dispatch = createEventDispatcher();

  function closeModal() {
    dispatch("close");
  }

  async function saveSettings() {
    theme.set(selectedTheme);
    settings.theme = selectedTheme;
    settings.language = selectedLocale;
    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (response.ok) {
        if (localStorage.getItem("lang") !== selectedLocale) {
          localStorage.setItem("lang", selectedLocale);
          window.location.reload();
        }
        // dispatch("settingsChanged", settings);
        // closeModal();
      } else {
        alert("Failed to save settings");
      }
    } catch (error) {
      console.error("Error saving settings:", error);
      alert("Error saving settings");
    }
  }

  async function selectFolder() {
    try {
      const response = await fetch("/api/select_folder", { method: "POST" });
      if (response.ok) {
        const data = await response.json();
        if (data.path) {
          settings.download_path = data.path;
        }
      } else {
        alert("폴더 선택에 실패했습니다.");
      }
    } catch (e) {
      alert("폴더 선택 중 오류 발생");
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
    class="modal-backdrop"
    role="dialog"
    aria-label="Settings"
    aria-modal="true"
    tabindex="0"
    on:click={closeModal}
    on:keydown={(e) => {
      if (e.key === "Escape") closeModal();
    }}
  >
    <div class="modal" on:click|stopPropagation>
      {#if isLoading}
        <div class="modal-loading-container">
          <div class="modal-spinner"></div>
          <div class="modal-loading-text">로딩 중...</div>
        </div>
      {:else}
        <!-- 기존 폼 내용 시작 -->
        <div class="modal-header">
          <div class="modal-title-group">
            <SettingsIcon />
            <h2>{$t("settings_title")}</h2>
          </div>
          <button class="button-icon close-button" on:click={closeModal}>
            <XIcon />
          </button>
        </div>
        <div class="form-group">
          <label for="download-path">{$t("settings_download_path")}</label>
          <div class="input-group">
            <input
              id="download-path"
              type="text"
              class="input"
              bind:value={settings.download_path}
            />
            <button
              type="button"
              class="button-icon"
              title="폴더 선택"
              on:click={selectFolder}
              aria-label="폴더 선택"
            >
              <FolderIcon />
            </button>
          </div>
        </div>
        <div class="form-group">
          <label for="locale">{$t("settings_language")}</label>
          <div class="input-group">
            <select
              id="locale"
              class="input"
              bind:value={selectedLocale}
              on:change={changeLocale}
            >
              <option value="ko">한국어</option>
              <option value="en">English</option>
            </select>
          </div>
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
                <span class="theme-icon" aria-label="라이트"
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
                <span class="theme-icon" aria-label="다크"
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
                <span class="theme-icon" aria-label="드라큘라"
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
                <span class="theme-icon" aria-label="시스템"
                  >{themeIcons.system}</span
                >
                <span>{$t("theme_system")}</span>
              </div>
            </label>
          </div>
        </fieldset>
        <div
          class="modal-actions"
          style="padding-top: 1rem; border-top: 1px solid var(--card-border);"
        >
          <button on:click={closeModal} class="button button-secondary"
            >{$t("button_cancel")}</button
          >
          <button on:click={saveSettings} class="button button-primary"
            >{$t("button_save")}</button
          >
        </div>
        <!-- 기존 폼 내용 끝 -->
      {/if}
    </div>
  </div>
{/if}

{#if $showToast}
  <div class="toast">{$toastMessage}</div>
{/if}

<style>
  .modal {
    max-height: 90vh;
    overflow-y: auto;
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
</style>
