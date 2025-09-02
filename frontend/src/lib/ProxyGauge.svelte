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

  $: usagePercentage = totalProxies > 0 ? ((totalProxies - availableProxies) / totalProxies) * 100 : 0;
  $: successRate = (successCount + failCount) > 0 ? (successCount / (successCount + failCount)) * 100 : 0;
  $: successPercentage = totalProxies > 0 ? (successCount / totalProxies) * 100 : 0;
  $: failPercentage = totalProxies > 0 ? (failCount / totalProxies) * 100 : 0;
  $: unusedPercentage = totalProxies > 0 ? (availableProxies / totalProxies) * 100 : 0;

  async function refreshProxies() {
    try {
      const response = await fetch('/api/proxy-status/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      if (response.ok) {
        // 리셋 후 상태 다시 가져오기
        window.location.reload();
      }
    } catch (error) {
      console.error($t('proxy_reset_failed'), error);
    }
  }
</script>

<div class="proxy-gauge">
  <div class="status-text">
    <div class="status-left">
      <span class="label-icon"><NetworkIcon /></span>
      <span class="label-text">{$t("proxy_title")}</span>
      <span class="proxy-count">{availableProxies}/{totalProxies}</span>
      <div class="proxy-stats">
        <span class="success-badge">{successCount}</span>
        <span class="fail-badge">{failCount}</span>
      </div>
    </div>
    <div class="gauge-bar">
      <div 
        class="gauge-fill success" 
        style="width: {successPercentage}%"
        title={$t("proxy_success_tooltip", { count: successCount })}
      ></div>
      <div 
        class="gauge-fill failed" 
        style="width: {failPercentage}%"
        title={$t("proxy_failed_tooltip", { count: failCount })}
      ></div>
      <div 
        class="gauge-fill unused" 
        style="width: {unusedPercentage}%"
        title={$t("proxy_unused_tooltip", { count: availableProxies })}
      ></div>
    </div>
  </div>
  
  <!-- 실시간 프록시 상태 표시 (항상 표시) -->
  <div class="proxy-status" class:trying={status === "trying"} class:success={status === "success"} class:failed={status === "failed"} class:idle={!status || !currentProxy}>
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
        {currentStep === "parsing" ? $t("proxy_link_parsing") : $t("proxy_downloading")} {$t("proxy_in_progress")}... 
        ({currentIndex}/{totalAttempting}) {currentProxy}
      </span>
    {:else if status === "success" && currentProxy}
      <span class="status-icon success-icon"></span>
      <span class="status-text">
        {currentStep === "parsing" ? $t("proxy_link_parsing") : $t("proxy_downloading")} {$t("proxy_success_msg")}! {currentProxy}
      </span>
    {:else if status === "failed" && currentProxy}
      <span class="status-icon failed-icon"></span>
      <span class="status-text">
        {currentStep === "parsing" ? $t("proxy_link_parsing") : $t("proxy_downloading")} {$t("proxy_failed_msg")}: {currentProxy}
      </span>
    {:else}
      <span class="status-icon idle-icon"></span>
      <span class="status-text">
        {#if activeDownloadCount === 0}
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
    transition: background-color 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
    font-size: 0.85rem;
  }

  .proxy-label {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background-color: #FFB74D;
    color: white;
    padding: 4px 10px;
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
    gap: 0.5rem;
    flex: 1;
    min-width: 0;
  }

  /* 게이지 바 스타일 */
  .gauge-bar {
    flex-shrink: 0;
    width: 120px;
    height: 6px;
    background-color: var(--card-border);
    border-radius: 6px;
    overflow: hidden;
    display: flex;
  }


  .proxy-count {
    font-weight: 700;
    color: var(--text-primary);
    font-size: 0.75rem;
    flex-shrink: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
    max-width: 60px;
  }


  .gauge-fill {
    height: 100%;
    transition: width 0.3s ease;
    position: relative;
  }

  .gauge-fill.success {
    background-color: var(--success-color);
  }

  .gauge-fill.failed {
    background-color: var(--danger-color);
  }

  .gauge-fill.unused {
    background-color: var(--text-secondary);
    opacity: 0.3;
  }

  .proxy-stats {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    font-size: 0.65rem;
    font-weight: 600;
  }

  .success-badge {
    color: var(--success-color);
    background: rgba(16, 185, 129, 0.1);
    padding: 0.15rem 0.3rem;
    border-radius: 4px;
    border: 1px solid rgba(16, 185, 129, 0.2);
  }

  .fail-badge {
    color: var(--danger-color);
    background: rgba(239, 68, 68, 0.1);
    padding: 0.15rem 0.3rem;
    border-radius: 4px;
    border: 1px solid rgba(239, 68, 68, 0.2);
  }


  .refresh-btn {
    background-color: var(--button-secondary-background);
    color: var(--button-secondary-text);
    border: 1px solid var(--button-secondary-border);
    border-radius: 6px;
    padding: 4px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.2s ease;
    min-width: 24px;
    height: 24px;
    flex-shrink: 0;
  }

  .refresh-btn:hover:not(:disabled) {
    background-color: var(--button-secondary-background-hover);
  }

  .refresh-btn:disabled {
    background-color: var(--disabled-button-background);
    color: var(--disabled-button-text);
    cursor: not-allowed;
    opacity: 0.7;
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
    content: '';
    position: absolute;
    top: 2px;
    left: 4px;
    width: 3px;
    height: 6px;
    border: solid white;
    border-width: 0 2px 2px 0;
    transform: rotate(45deg);
  }
  
  .failed-icon {
    position: relative;
    border-radius: 50%;
    background: currentColor;
  }
  
  .failed-icon::before,
  .failed-icon::after {
    content: '';
    position: absolute;
    top: 50%;
    left: 50%;
    width: 8px;
    height: 2px;
    background: white;
    transform: translate(-50%, -50%) rotate(45deg);
  }
  
  .failed-icon::after {
    transform: translate(-50%, -50%) rotate(-45deg);
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
    content: '!';
    position: absolute;
    top: 2px;
    left: -2px;
    color: var(--warning-color);
    font-size: 8px;
    font-weight: bold;
  }
  
  .idle-icon {
    position: relative;
    border: 2px solid currentColor;
    border-radius: 50%;
    opacity: 0.5;
  }
  
  .idle-icon::after {
    content: '';
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
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

</style>