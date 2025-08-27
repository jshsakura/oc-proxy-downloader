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

  // --- Icons ---
  // icons 객체 완전히 삭제

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

  // 프록시 관리 관련 변수
  let userProxies = [];
  let newProxyAddress = "";
  let newProxyDescription = "";
  let isAddingProxy = false;

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

  function closeModal() {
    dispatch("close");
  }

  // 프록시 관리 함수들
  async function loadUserProxies() {
    try {
      const response = await fetch("/api/proxies");
      if (response.ok) {
        userProxies = await response.json();
      }
    } catch (error) {
      console.error("프록시 목록 로드 실패:", error);
    }
  }

  async function addProxy() {
    if (!newProxyAddress.trim()) {
      showToastMsg("프록시 주소를 입력하세요", "error");
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
        showToastMsg("프록시가 추가되었습니다", "success");
        newProxyAddress = "";
        newProxyDescription = "";
        await loadUserProxies();
        dispatch('proxyChanged'); // 부모 컴포넌트에 프록시 변경 알림
      } else {
        const error = await response.text();
        showToastMsg(`프록시 추가 실패: ${error}`, "error");
      }
    } catch (error) {
      showToastMsg("프록시 추가 중 오류가 발생했습니다", "error");
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
        showToastMsg("프록시가 삭제되었습니다", "success");
        await loadUserProxies();
        dispatch('proxyChanged'); // 부모 컴포넌트에 프록시 변경 알림
      } else {
        showToastMsg("프록시 삭제 실패", "error");
      }
    } catch (error) {
      showToastMsg("프록시 삭제 중 오류가 발생했습니다", "error");
    }
  }

  async function toggleProxy(proxyId) {
    try {
      const response = await fetch(`/api/proxies/${proxyId}/toggle`, {
        method: "PUT"
      });

      if (response.ok) {
        await loadUserProxies();
        dispatch('proxyChanged'); // 부모 컴포넌트에 프록시 변경 알림
      } else {
        showToastMsg("프록시 상태 변경 실패", "error");
      }
    } catch (error) {
      showToastMsg("프록시 상태 변경 중 오류가 발생했습니다", "error");
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
        // Fallback for older browsers or non-HTTPS
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
      showToastMsg($t("copy_success") || "복사되었습니다", "success");
    } catch (error) {
      console.error("클립보드 복사 실패:", error);
      showToastMsg($t("copy_failed") || "복사에 실패했습니다", "error");
    }
  }

  // 모달이 열릴 때 프록시 목록 로드
  $: if (showModal) {
    loadUserProxies();
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
        let errorMessage = `설정 저장에 실패했습니다 (${response.status})`;
        
        if (response.status === 500) {
          errorMessage += "\n서버 내부 오류가 발생했습니다.";
        } else if (response.status === 403) {
          errorMessage += "\n권한이 없습니다.";
        } else if (response.status === 404) {
          errorMessage += "\nAPI 경로를 찾을 수 없습니다.";
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
      console.log("[DEBUG] 기본 경로 가져오기 API 호출 시작");
      const response = await fetch("/api/default_download_path");
      console.log("[DEBUG] API 응답 받음:", response.status);
      
      if (response.ok) {
        const data = await response.json();
        console.log("[DEBUG] 기본 경로 데이터:", data);
        if (data.path) {
          settings = { ...settings, download_path: data.path };
          console.log("[DEBUG] 기본 경로로 리셋됨:", data.path);
        } else {
          // API 응답에 path가 없으면 기본값 사용
          settings = { ...settings, download_path: "/downloads" };
          console.log("[DEBUG] 기본값으로 리셋됨: /downloads");
        }
      } else {
        console.warn("[WARN] 기본 경로 API 실패, 기본값 사용:", response.status);
        // API 실패 시 기본값으로 직접 설정
        settings = { ...settings, download_path: "/downloads" };
      }
    } catch (e) {
      console.warn("[WARN] 기본 경로 API 오류, 기본값 사용:", e.message);
      // 오류 발생 시 기본값으로 직접 설정
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
                <p class="subtitle">{$t("settings_subtitle")}</p>
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

          <!-- 프록시 관리 섹션 -->
          <fieldset class="form-group proxy-management">
            <legend>{$t("proxy_management")}</legend>
            
            <!-- 프록시 추가 -->
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
                  {isAddingProxy ? "추가 중..." : $t("proxy_add_button")}
                </button>
              </div>
            </div>

            <!-- 프록시 목록 -->
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
    padding-right: 48px; /* 리셋 버튼 하나만 있으므로 패딩 줄임 */
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
    right: 8px; /* 폴더 버튼 제거했으므로 오른쪽으로 이동 */
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

  /* 프록시 관리 스타일 */
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

  .proxy-table th:nth-child(1), .proxy-table td:nth-child(1) { width: 35%; } /* 주소 */
  .proxy-table th:nth-child(2), .proxy-table td:nth-child(2) { width: 12%; } /* 타입 */
  .proxy-table th:nth-child(3), .proxy-table td:nth-child(3) { width: 12%; } /* 상태 */
  .proxy-table th:nth-child(4), .proxy-table td:nth-child(4) { width: 26%; } /* 추가일시 */
  .proxy-table th:nth-child(5), .proxy-table td:nth-child(5) { width: 15%; } /* 작업 */

  /* 모든 테이블 셀에 기본 오버플로우 처리 */
  .proxy-table td {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* 주소 컬럼은 특별 처리 */
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

  /* 이전 스타일 제거됨 - 새로운 proxy-action-btn 스타일 사용 */

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