<script>
  import { t } from "./i18n.js";
  import FolderIcon from "../icons/FolderIcon.svelte";

  export let localDownloadCount = 0;
  export let localStatus = ""; // "downloading", "waiting", "completed", "failed"
  export let localCurrentFile = "";
  export let localProgress = 0;
  export let localWaitTime = 0;
  export let activeLocalDownloads = [];
</script>

<div class="local-gauge">
  <div class="local-info">
    <div class="local-label">
      <span class="label-icon"><FolderIcon /></span>
      <span class="label-text">{$t("local_title")}</span>
    </div>
    <span class="local-count">{$t("local_progress_text", { count: localDownloadCount })}</span>
    <div class="local-indicator">
      <div class="local-dot {localStatus}"></div>
    </div>
  </div>
  
  <!-- 로컬 다운로드 상태 표시 -->
  <div class="local-status" class:downloading={localStatus === "downloading"} class:waiting={localStatus === "waiting"} class:completed={localStatus === "completed"} class:failed={localStatus === "failed"} class:idle={!localStatus || localDownloadCount === 0}>
    {#if localStatus === "waiting" && localWaitTime > 0}
      <span class="status-icon waiting-icon"></span>
      <span class="status-text">
        {$t("local_wait_time", { time: localWaitTime })}
        {#if localCurrentFile}
          - {localCurrentFile}
        {/if}
      </span>
    {:else if localStatus === "downloading"}
      <span class="status-icon downloading-icon"></span>
      <span class="status-text">
        {$t("local_downloading")} {localProgress}%
        {#if localCurrentFile}
          - {localCurrentFile}
        {/if}
      </span>
    {:else if localStatus === "completed"}
      <span class="status-icon completed-icon"></span>
      <span class="status-text">
        {$t("local_completed")}
        {#if localCurrentFile}
          - {localCurrentFile}
        {/if}
      </span>
    {:else if localStatus === "failed"}
      <span class="status-icon failed-icon"></span>
      <span class="status-text">
        {$t("local_failed")}
        {#if localCurrentFile}
          - {localCurrentFile}
        {/if}
      </span>
    {:else}
      <span class="status-icon idle-icon"></span>
      <span class="status-text">
        {$t("local_idle")}
      </span>
    {/if}
  </div>
</div>

<style>
  .local-gauge {
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

  .local-info {
    display: flex;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .local-label {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background-color: #81C784;
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

  .local-count {
    font-weight: 700;
    color: var(--text-primary);
    min-width: 80px;
  }

  .local-indicator {
    margin-left: auto;
  }

  .local-dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    transition: all 0.3s ease;
  }

  .local-dot.downloading {
    background-color: #81C784;
    animation: pulse 2s infinite;
  }

  .local-dot.waiting {
    background-color: #FF9800;
    animation: blink 1s infinite;
  }

  .local-dot.completed {
    background-color: var(--success-color);
  }

  .local-dot.failed {
    background-color: var(--danger-color);
  }

  .local-dot:not(.downloading):not(.waiting):not(.completed):not(.failed) {
    background-color: var(--text-secondary);
    opacity: 0.3;
  }

  .local-status {
    margin-top: 0.5rem;
    padding: 0.5rem 0.75rem;
    border-radius: 8px;
    font-size: 0.8rem;
    font-weight: 500;
    display: flex;
    align-items: center;
    gap: 0.5rem;
    transition: background-color 0.3s ease;
    background-color: var(--card-border);
    color: var(--text-primary);
    border: 1px solid var(--card-border);
  }

  .local-status.downloading {
    background-color: #81C784;
    color: white;
    border: 1px solid #81C784;
  }

  .local-status.waiting {
    background-color: #FF9800;
    color: white;
    border: 1px solid #FF9800;
  }

  .local-status.completed {
    background-color: var(--success-color);
    color: white;
    border: 1px solid var(--success-color);
  }

  .local-status.failed {
    background-color: var(--danger-color);
    color: white;
    border: 1px solid var(--danger-color);
  }

  .local-status.idle {
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
  
  .downloading-icon {
    border: 2px solid transparent;
    border-top: 2px solid currentColor;
    border-right: 2px solid currentColor;
    border-radius: 50%;
    animation: spin 1s linear infinite;
  }

  .waiting-icon {
    border: 2px solid currentColor;
    border-radius: 50%;
    animation: blink 1s infinite;
  }
  
  .completed-icon {
    position: relative;
    border-radius: 50%;
    background: currentColor;
  }
  
  .completed-icon::after {
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
  
  .local-status.downloading .status-text,
  .local-status.waiting .status-text,
  .local-status.completed .status-text,
  .local-status.failed .status-text {
    color: white;
  }
  
  .local-status.idle .status-text {
    color: var(--text-secondary);
  }

  .active-downloads {
    margin-top: 0.5rem;
    padding: 0.5rem;
    background-color: rgba(255, 255, 255, 0.1);
    border-radius: 6px;
    font-size: 0.75rem;
  }

  .download-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.25rem;
  }

  .download-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    margin-right: 0.5rem;
  }

  .download-progress {
    font-weight: 600;
    min-width: 40px;
    text-align: right;
  }

  .more-downloads {
    text-align: center;
    opacity: 0.7;
    font-style: italic;
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }

  @keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
  }

  /* Mobile responsiveness */
  @media (max-width: 768px) {
    .local-gauge {
      padding: 0.75rem;
      margin-bottom: 1rem;
    }
    
    .local-info {
      gap: 0.75rem;
    }
  }
</style>