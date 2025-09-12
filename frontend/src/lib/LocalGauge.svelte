<script>
  import { t } from "./i18n.js";
  import FolderIcon from "../icons/FolderIcon.svelte";

  export let localDownloadCount = 0;
  export let localStatus = ""; // "downloading", "waiting", "completed", "failed"
</script>

<div class="local-gauge">
  <div class="local-info">
    <div class="local-label">
      <span class="label-icon"><FolderIcon /></span>
      <span class="label-text">{$t("local_title")}</span>
    </div>
    <span class="local-count"
      >{$t("local_progress_text", { count: localDownloadCount })}</span
    >
    <div class="local-indicator">
      <div class="local-dot {localStatus}"></div>
    </div>
  </div>

  <div
    class="local-status"
    class:downloading={localStatus === "downloading"}
    class:waiting={localStatus === "waiting"}
    class:completed={localStatus === "completed"}
    class:failed={localStatus === "failed"}
    class:idle={!localStatus || localDownloadCount === 0}
  >
    {#if localStatus === "waiting"}
      <span class="status-icon idle-icon"></span>
      <span class="status-text">
        {$t("local_waiting")}
      </span>
    {:else if localStatus === "downloading"}
      <span class="status-icon downloading-icon"></span>
      <span class="status-text">
        {$t("local_downloading")}
      </span>
    {:else if localStatus === "completed"}
      <span class="status-icon completed-icon"></span>
      <span class="status-text">
        {$t("local_completed")}
      </span>
    {:else if localStatus === "failed"}
      <span class="status-icon failed-icon"></span>
      <span class="status-text">
        {$t("local_failed")}
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
    transition:
      background-color 0.3s ease,
      border-color 0.3s ease,
      box-shadow 0.3s ease;
    font-size: 0.85rem;
  }

  .local-info {
    min-height: 30px;
    display: flex;
    align-items: center;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .local-label {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background-color: var(--success-color);
    color: white;
    padding: 4px 15px;
    border-radius: 15px;
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
    color: var(--text-secondary);
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
    background-color: #81c784;
    animation: pulse 2s infinite;
  }

  .local-dot.waiting {
    background-color: var(--success-color);
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

  .completed-icon {
    position: relative;
    border-radius: 50%;
    background: currentColor;
  }

  .completed-icon::after {
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

  .failed-icon {
    position: relative;
    border-radius: 50%;
    background: currentColor;
  }

  .failed-icon::before,
  .failed-icon::after {
    content: "";
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
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }

  @keyframes pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.5;
    }
  }

  @keyframes blink {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.3;
    }
  }

  /* Mobile responsiveness */
  /* Mobile responsiveness - 759px 이하에서 세로 배치 */
  @media (max-width: 759px) {
    .local-gauge {
      padding: 0.75rem;
      margin-bottom: 1rem;
    }

    .local-info {
      gap: 0.75rem;
    }
  }
</style>
