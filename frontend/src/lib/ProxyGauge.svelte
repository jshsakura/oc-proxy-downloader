<script>
  import { onMount, onDestroy } from "svelte";
  import { t } from "./i18n.js";
  import NetworkIcon from "../icons/NetworkIcon.svelte";

  export let totalProxies = 0;
  export let availableProxies = 0;
  export let successCount = 0;
  export let failCount = 0;

  // 실시간 프록시 상태
  export let currentProxy = "";
  export let currentStep = "";
  export let status = ""; // "trying", "success", "failed", ""
  export let currentIndex = 0;
  export let totalAttempting = 0;
  export let activeDownloadCount = 0;
  export let statusMessage = ""; // 백엔드에서 제공하는 상태 메시지

  $: usagePercentage =
    totalProxies > 0
      ? ((totalProxies - availableProxies) / totalProxies) * 100
      : 0;
  $: successRate =
    successCount + failCount > 0
      ? (successCount / (successCount + failCount)) * 100
      : 0;
  $: successPercentage =
    totalProxies > 0 ? (successCount / totalProxies) * 100 : 0;
  $: failPercentage = totalProxies > 0 ? (failCount / totalProxies) * 100 : 0;
  $: unusedPercentage =
    totalProxies > 0 ? (availableProxies / totalProxies) * 100 : 0;

  // 게이지 표시용 퍼센티지 (연한 녹색 기본, 실패시 빨간색 추가)
  $: availableDisplayPercentage =
    totalProxies > 0 ? (availableProxies / totalProxies) * 100 : 0;
  $: failDisplayPercentage =
    totalProxies > 0 && failCount > 0
      ? Math.max((failCount / totalProxies) * 100, 3) // 최소 3% 보장
      : 0;

  let isRefreshing = false;

  async function refreshProxies() {
    if (isRefreshing) return;

    try {
      isRefreshing = true;
      const response = await fetch("/api/proxy-status/reset", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("access_token")}`,
        },
      });
      if (response.ok) {
        // 성공적으로 리셋됨을 알림
        console.log($t("proxy_reset_success"));
        // 부모 컴포넌트에서 상태를 다시 가져오도록 이벤트 발생
        const event = new CustomEvent("proxy-refreshed");
        document.dispatchEvent(event);
      } else {
        console.error($t("proxy_refresh_failed"));
      }
    } catch (error) {
      console.error($t("proxy_reset_failed"), error);
    } finally {
      isRefreshing = false;
    }
  }
</script>

<div class="proxy-gauge">
  <div class="status-text">
    <div class="status-left">
      <div class="proxy-label">
        <span class="label-icon"><NetworkIcon /></span>
        <span class="label-text">{$t("proxy_title")}</span>
      </div>
    </div>
    <div class="status-right">
      <div class="gauge-bar">
        <!-- 전체 배경을 연한 녹색으로 채우기 -->
        <div class="gauge-background"></div>
        <!-- 실패한 프록시는 빨간색으로 우측에서부터 표시 -->
        <div
          class="gauge-fill failed"
          style="width: {failDisplayPercentage}%"
          title={$t("proxy_failed_tooltip", { count: failCount })}
        ></div>
        <div class="gauge-text">
          <span class="gauge-available"
            >{availableProxies.toLocaleString()}</span
          >
          <span class="gauge-separator">/</span>
          <span class="gauge-failed">{failCount.toLocaleString()}</span>
          <span class="gauge-separator">/</span>
          <span class="gauge-total">{totalProxies.toLocaleString()}</span>
        </div>
      </div>
      <button
        class="refresh-button"
        class:refreshing={isRefreshing}
        on:click={refreshProxies}
        disabled={isRefreshing}
        title={isRefreshing ? $t("proxy_refreshing") : $t("proxy_refresh")}
        aria-label={isRefreshing ? $t("proxy_refreshing") : $t("proxy_refresh")}
      >
        <svg
          class:spin={isRefreshing}
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <polyline points="23 4 23 10 17 10"></polyline>
          <polyline points="1 20 1 14 7 14"></polyline>
          <path
            d="m3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"
          ></path>
        </svg>
      </button>
    </div>
  </div>

  <!-- 실시간 프록시 상태 표시 (항상 표시) -->
  <div
    class="proxy-status"
    class:trying={status === "trying"}
    class:success={status === "success"}
    class:failed={status === "failed"}
    class:idle={!status || !currentProxy}
  >
    {#if activeDownloadCount > 1}
      <!-- 다중 다운로드 진행 중일 때 -->
      <span class="status-icon trying-icon"></span>
      <span class="status-text">
        {$t("proxy_multi_download", { count: activeDownloadCount })}
        {#if currentProxy}
          - {currentProxy}
        {/if}
      </span>
    {:else if status === "trying" && currentProxy}
      <span class="status-icon trying-icon"></span>
      <span class="status-text">
        {currentStep === "parsing"
          ? $t("proxy_link_parsing")
          : $t("proxy_attempting")}... ({currentIndex}/{totalAttempting}) {currentProxy}
      </span>
    {:else if status === "success" && currentProxy}
      <span class="status-icon success-icon"></span>
      <span class="status-text">
        {currentStep === "parsing"
          ? $t("proxy_link_parsing")
          : $t("proxy_attempting")}
        {$t("proxy_success_msg")}! {currentProxy}
      </span>
    {:else if status === "failed"}
      <span class="status-icon idle-icon"></span>
      <span class="status-text">
        {#if statusMessage && statusMessage.trim() !== ""}
          {statusMessage}
        {:else}
          {$t("proxy_idle")}
        {/if}
      </span>
    {:else}
      <span class="status-icon idle-icon"></span>
      <span class="status-text">
        {#if statusMessage && statusMessage.trim() !== ""}
          {statusMessage}
        {:else if activeDownloadCount === 0}
          {$t("proxy_idle")}
        {:else}
          {$t("proxy_downloading")}
        {/if}
      </span>
    {/if}
  </div>

  {#if availableProxies === 0 && totalProxies > 0}
    <div class="warning">
      <span class="warning-icon"></span>
      {$t("proxy_exhausted")}
    </div>
  {/if}
</div>

<style>
  .proxy-gauge {
    background-color: var(--card-background);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 0.75rem;
    margin-bottom: 0;
    height: 100%;
    display: flex;
    flex-direction: column;
    transition:
      background-color 0.3s ease,
      border-color 0.3s ease,
      box-shadow 0.3s ease;
    font-size: 0.85rem;
  }

  .proxy-label {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background-color: #ffb74d;
    color: white;
    padding: 4px 15px;
    border-radius: 16px;
    font-size: 12px;
    font-weight: 500;
    min-height: 26px;
  }

  .label-icon {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .label-text {
    line-height: 1;
  }

  .status-text {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    width: 100%;
  }

  .status-left {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex: 0 0 30%;
    min-width: 0;
  }

  .status-right {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.5rem;
    flex: 0 0 65%;
    min-width: 0;
  }

  .refresh-button {
    background: none;
    border: 1px solid var(--card-border);
    border-radius: 6px;
    padding: 0.4rem;
    color: var(--text-secondary);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s ease;
  }

  .refresh-button:hover {
    background: var(--bg-secondary, #f8f9fa);
    border-color: var(--primary-color);
    color: var(--primary-color);
  }

  .refresh-button:active {
    transform: scale(0.95);
  }

  .refresh-button:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .refresh-button:disabled:hover {
    background: none;
    border-color: var(--card-border);
    color: var(--text-secondary);
  }

  .refresh-button.refreshing {
    color: var(--primary-color);
    border-color: var(--primary-color);
  }

  .refresh-button svg {
    width: 16px;
    height: 16px;
  }

  .refresh-button svg.spin {
    animation: spin 1s linear infinite;
  }

  /* 게이지 바 스타일 */
  .gauge-bar {
    flex: 1;
    min-width: 0;
    height: 30px;
    border-radius: 5px;
    overflow: hidden;
    display: flex;
    position: relative;
    border: 1px solid var(--card-border);
    margin-right: 0.5rem;
  }

  .gauge-background {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: var(--card-border);
    z-index: 0;
  }

  .gauge-text {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 11px;
    font-weight: 700;
    white-space: nowrap;
    z-index: 3;
    pointer-events: none;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
    width: calc(100% - 8px);
    text-align: center;
    overflow: hidden;
  }

  .gauge-available {
    color: var(--success-color);
  }

  .gauge-failed {
    color: var(--danger-color);
  }

  .gauge-separator {
    color: var(--text-primary);
  }

  .gauge-total {
    color: var(--text-secondary);
  }

  .gauge-fill {
    height: 100%;
    transition: width 0.3s ease;
    position: absolute;
    top: 0;
    z-index: 1;
  }

  .gauge-fill.failed {
    background-color: var(--danger-color);
    right: 0;
    background: rgba(239, 68, 68, 0.2);
  }

  .warning {
    margin-top: 0.75rem;
    padding: 0.75rem;
    background-color: var(--warning-color);
    border: 1px solid var(--warning-color);
    border-radius: 10px;
    color: #fff;
    font-size: 0.8rem;
    font-weight: 600;
    text-align: center;
    opacity: 0.9;
  }

  .proxy-status {
    margin-top: 0.5rem;
    padding: 0.5rem 0.75rem;
    border-radius: 8px;
    font-size: 0.8rem;
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    transition: background-color 0.3s ease;
  }

  .proxy-status.trying {
    background-color: var(--card-border);
    color: var(--text-primary);
    border: 1px solid var(--card-border);
  }

  .proxy-status.success {
    background-color: var(--success-color);
    color: #fff;
    border: 1px solid var(--success-color);
  }

  .proxy-status.failed {
    background-color: var(--danger-color);
    color: #fff;
    border: 1px solid var(--danger-color);
  }

  .proxy-status.idle {
    background-color: var(--card-background);
    color: var(--text-secondary);
    border: 1px solid var(--card-border);
    opacity: 0.7;
  }

  .status-icon {
    display: inline-block;
    width: 12px;
    height: 12px;
    margin-right: 4px;
  }

  .trying-icon {
    border: 2px solid transparent;
    border-top: 2px solid currentColor;
    border-right: 2px solid currentColor;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  .success-icon {
    position: relative;
    border-radius: 50%;
    background: currentColor;
  }

  .success-icon::after {
    content: "";
    position: absolute;
    top: 2px;
    left: 4px;
    width: 3px;
    height: 6px;
    border: solid white;
    border-width: 0 2px 2px 0;
    transform: rotate(45deg);
  }


  .warning-icon {
    display: inline-block;
    width: 0;
    height: 0;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-bottom: 10px solid currentColor;
    margin-right: 6px;
    vertical-align: middle;
    position: relative;
  }

  .warning-icon::after {
    content: "!";
    position: absolute;
    top: 2px;
    left: -2px;
    color: var(--warning-color);
    font-size: 8px;
    font-weight: bold;
  }

  .idle-icon {
    position: relative;
    border: 1px solid currentColor;
    border-radius: 50%;
    opacity: 0.5;
  }

  .idle-icon::after {
    content: "";
    position: absolute;
    top: 50%;
    left: 50%;
    width: 4px;
    height: 4px;
    background: currentColor;
    border-radius: 50%;
    transform: translate(-50%, -50%);
    opacity: 0.7;
  }

  .status-text {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  @keyframes spin {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }
</style>
