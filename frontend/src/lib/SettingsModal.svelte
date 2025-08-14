<script>
  import { createEventDispatcher } from "svelte";
  import { theme } from "./theme.js";
  import { t, loadTranslations } from "./i18n.js";
  import FolderIcon from "../icons/FolderIcon.svelte";
  import HomeIcon from "../icons/HomeIcon.svelte";
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
  let initialSettingsLoaded = false;

  // settings 초기 로드 시에만 동기화 (중복 동기화 방지)
  $: if (currentSettings && currentSettings.download_path && !initialSettingsLoaded) {
    settings = { ...currentSettings };
    selectedTheme = settings.theme || $theme;
    initialSettingsLoaded = true;
  }

  // settings가 로드되면 로딩 false (download_path가 없어도 설정 가능하도록)
  $: isLoading = !settings;

  $: if (showModal && !selectedLocaleWasSet) {
    selectedLocale = localStorage.getItem("lang") || "ko";
    selectedLocaleWasSet = true;
  }
  $: if (!showModal) {
    selectedLocaleWasSet = false;
    initialSettingsLoaded = false; // 모달이 닫히면 초기화 플래그 리셋
  }

  const dispatch = createEventDispatcher();

  function closeModal() {
    dispatch("close");
  }

  async function saveSettings() {
    // 테마 먼저 적용
    theme.set(selectedTheme);
    
    // 설정 객체 업데이트
    settings.theme = selectedTheme;
    settings.language = selectedLocale;
    
    console.log("[DEBUG] 저장할 설정:", settings);
    
    try {
      const response = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      
      console.log("[DEBUG] 저장 API 응답:", response.status);
      
      if (response.ok) {
        const responseData = await response.json();
        console.log("[DEBUG] 저장 응답 데이터:", responseData);
        
        // 언어 변경 시에만 새로고침
        if (localStorage.getItem("lang") !== selectedLocale) {
          localStorage.setItem("lang", selectedLocale);
          window.location.reload();
          return; // 새로고침되므로 더 이상 진행하지 않음
        }
        
        // 테마만 변경된 경우 모달 닫기
        dispatch("settingsChanged", settings);
        closeModal();
      } else {
        console.error("[ERROR] 저장 실패:", response.status);
        alert("Failed to save settings");
      }
    } catch (error) {
      console.error("Error saving settings:", error);
      alert("Error saving settings");
    }
  }

  async function selectFolder() {
    try {
      console.log("[DEBUG] 폴더 선택 API 호출 시작");
      const response = await fetch("/api/select_folder", { 
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });
      console.log("[DEBUG] API 응답 받음:", response.status);
      
      if (response.ok) {
        const data = await response.json();
        console.log("[DEBUG] 응답 데이터:", data);
        if (data.path) {
          settings = { ...settings, download_path: data.path };
          console.log("[DEBUG] 폴더 경로 업데이트됨:", data.path);
        }
      } else {
        console.warn("[WARN] 폴더 선택 API 실패 (도커 환경일 수 있음):", response.status);
        // 도커 환경에서는 조용히 실패 처리
      }
    } catch (e) {
      console.warn("[WARN] 폴더 선택 실패 (도커 환경일 수 있음):", e.message);
      // 도커 환경에서는 조용히 실패 처리, 사용자가 수동 입력 가능
    }
  }

  async function resetToDefault() {
    try {
      console.log("[DEBUG] 기본 경로 가져오기 API 호출 시작");
      const response = await fetch("/api/default_download_path");
      console.log("[DEBUG] API 응답 받음:", response.status);
      
      if (response.ok) {
        const data = await response.json();
        console.log("[DEBUG] 기본 경로 데이터:", data);
        if (data.path) {
          settings = { ...settings, download_path: data.path };
          console.log("[DEBUG] 기본 경로로 리셋됨:", data.path);
        }
      } else {
        console.error("[ERROR] 기본 경로 가져오기 실패:", response.status);
        alert("기본 경로를 가져오는데 실패했습니다.");
      }
    } catch (e) {
      console.error("[ERROR] 기본 경로 가져오기 중 오류:", e);
      alert("기본 경로 가져오기 중 오류 발생: " + e.message);
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
    <div class="modern-modal" on:click|stopPropagation>
      {#if isLoading}
        <div class="modal-loading-container">
          <div class="modal-spinner"></div>
          <div class="modal-loading-text">로딩 중...</div>
        </div>
      {:else}
        <!-- 모던 헤더 -->
        <div class="modal-header">
          <div class="header-content">
            <div class="title-section">
              <div class="icon-wrapper">
                <SettingsIcon />
              </div>
              <div class="title-text">
                <h2>{$t("settings_title")}</h2>
                <p class="subtitle">애플리케이션 설정</p>
              </div>
            </div>
            <button class="close-button" on:click={closeModal}>
              <XIcon />
            </button>
          </div>
        </div>

        <!-- 모던 본문 -->
        <div class="modal-body">
          <div class="form-group">
            <label for="download-path">{$t("settings_download_path")}</label>
            <div class="input-group">
              <input
                id="download-path"
                type="text"
                class="input"
                bind:value={settings.download_path}
                placeholder="다운로드 경로를 입력하세요 (예: /downloads)"
              />
              <button
                type="button"
                class="input-icon-button"
                on:click={selectFolder}
                title="폴더 선택"
                aria-label="폴더 선택"
              >
                <FolderIcon />
              </button>
              <button
                type="button"
                class="input-icon-button reset-button"
                on:click={resetToDefault}
                title="기본 경로로 리셋"
                aria-label="기본 경로로 리셋"
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
              <option value="ko">한국어</option>
              <option value="en">English</option>
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
        </div>

        <!-- 모던 푸터 -->
        <div class="modal-footer">
          <div class="footer-left">
            <!-- 왼쪽 공간 비워둠 -->
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
  /* 모던 백드롭 */
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

  /* 모던 모달 */
  .modern-modal {
    background: var(--card-background);
    border-radius: 16px;
    box-shadow: 
      0 25px 50px -12px rgba(0, 0, 0, 0.25),
      0 0 0 1px rgba(255, 255, 255, 0.05);
    width: 90vw;
    max-width: 650px;
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

  /* 모던 헤더 */
  .modal-header {
    background: linear-gradient(135deg, var(--primary-color) 0%, var(--primary-hover, #1e40af) 100%);
    color: white;
    padding: 1.5rem 2rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
    flex-shrink: 0; /* 헤더가 줄어들지 않도록 */
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
    transform: scale(1.05);
  }

  .close-button :global(svg) {
    width: 1.25rem;
    height: 1.25rem;
    color: white;
  }

  /* 로딩 상태 */
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

  /* 모던 본문 */
  .modal-body {
    padding: 2rem;
    flex: 1;
    overflow-y: auto;
    margin-bottom: 0;
    min-height: 0; /* flexbox 스크롤을 위해 필요 */
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

  /* 입력 그룹 (폴더 선택용) */
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
    padding-right: 88px; /* 두 개의 버튼 공간 확보 (48px + 40px) */
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
    right: 48px; /* 첫 번째 버튼 왼쪽에 배치 */
  }

  .input-icon-button:hover {
    background-color: var(--card-border);
    color: var(--text-primary);
  }

  .input-icon-button :global(svg) {
    width: 1rem;
    height: 1rem;
  }

  /* 테마 선택 */
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
    /* 기본 배경은 각 테마별 클래스에서 덮어씀 */
    background: var(--card-background);
    color: var(--text-primary);
  }

  .theme-card:hover {
    border-color: var(--primary-color);
    transform: translateY(-1px);
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

  /* 모던 푸터 */
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
    flex-shrink: 0; /* 푸터가 줄어들지 않도록 */
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
    transform: translateY(-2px);
    box-shadow: 
      0 6px 12px rgba(0, 0, 0, 0.15),
      0 2px 4px rgba(0, 0, 0, 0.08);
    border-color: rgba(255, 255, 255, 0.2);
  }

  .button-primary:active {
    transform: translateY(0px);
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
    transform: translateY(-1px);
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
  }

  .button-secondary:active {
    transform: translateY(0px);
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
  }

  /* 반응형 디자인 */
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
</style>