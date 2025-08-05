<script>
  import { createEventDispatcher } from "svelte";
  import { t } from "./i18n.js";
  import InfoIcon from "../icons/InfoIcon.svelte";
  import XIcon from "../icons/XIcon.svelte";
  import CopyIcon from "../icons/CopyIcon.svelte";
  import { onMount, onDestroy } from "svelte";
  import { showToastMsg } from "./toast.js";

  export let showModal = false;
  export let download = {};

  const dispatch = createEventDispatcher();

  function closeModal() {
    showModal = false;
    dispatch("close");
  }

  function formatBytes(bytes, decimals = 2) {
    if (!bytes || bytes === 0) return "0 Bytes";
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ["Bytes", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
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
    } catch (err) {
      console.error("클립보드 복사 실패:", err);
      showToastMsg($t("copy_failed") || "복사에 실패했습니다", "error");
    }
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
    aria-label="Download Details"
    aria-modal="true"
    tabindex="0"
    on:click={closeModal}
    on:keydown={(e) => {
      if (e.key === "Escape") closeModal();
    }}
  >
    <div class="modal" on:click|stopPropagation>
      <div class="modal-header">
        <div class="modal-title-group">
          <InfoIcon />
          <h2>{$t("detail_modal_title")}</h2>
        </div>
        <button class="button-icon close-button" on:click={closeModal}>
          <XIcon />
        </button>
      </div>
      <div class="modal-body">
        <table>
          <tbody>
            <tr>
              <th>{$t("detail_original_url")}:</th>
              <td>
                <div class="url-container">
                  <span class="url-text">{download.url}</span>
                  <button 
                    class="copy-button"
                    on:click={() => copyToClipboard(download.url)}
                    title={$t("copy_url") || "URL 복사"}
                  >
                    <CopyIcon />
                  </button>
                </div>
              </td>
            </tr>
            <tr>
              <th>{$t("detail_actual_file_url")}:</th>
              <td>
                {#if download.direct_link}
                  <div class="url-container">
                    <span class="url-text">{download.direct_link}</span>
                    <button 
                      class="copy-button"
                      on:click={() => copyToClipboard(download.direct_link)}
                      title={$t("copy_url") || "URL 복사"}
                    >
                      <CopyIcon />
                    </button>
                  </div>
                {:else}
                  {$t("detail_not_available")}
                {/if}
              </td>
            </tr>
            <tr>
              <th>{$t("detail_download_path")}:</th>
              <td>{download.save_path || $t("detail_not_available")}</td>
            </tr>
            <tr>
              <th>{$t("detail_requested_at")}:</th>
              <td>
                {#if download.requested_at}
                  {new Date(download.requested_at).toLocaleString()}
                {:else}
                  {$t("detail_not_available")}
                {/if}
              </td>
            </tr>
            <tr>
              <th>{$t("detail_status")}:</th>
              <td>{$t(`download_${download.status.toLowerCase()}`)}</td>
            </tr>
            <tr>
              <th>{$t("detail_file_name")}:</th>
              <td>{download.file_name || $t("detail_not_available")}</td>
            </tr>
            <tr>
              <th>{$t("detail_total_size")}:</th>
              <td>
                {download.total_size
                  ? formatBytes(download.total_size)
                  : $t("detail_not_available")}
              </td>
            </tr>
            <tr>
              <th>{$t("detail_downloaded_size")}:</th>
              <td>
                {download.downloaded_size
                  ? formatBytes(download.downloaded_size)
                  : $t("detail_not_available")}
              </td>
            </tr>
            <tr>
              <th>{$t("detail_finished_at")}:</th>
              <td>
                {#if download.finished_at}
                  {new Date(download.finished_at).toLocaleString()}
                {:else}
                  {$t("detail_not_available")}
                {/if}
              </td>
            </tr>
            <tr>
              <th>{$t("detail_error_message")}:</th>
              <td>
                <div class="error-message-container">
                  <span class="error-text">{download.error || $t("detail_no_error")}</span>
                  {#if download.error}
                    <button 
                      class="copy-button"
                      on:click={() => copyToClipboard(download.error)}
                      title={$t("copy_error") || "에러 메시지 복사"}
                    >
                      <CopyIcon />
                    </button>
                  {/if}
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="modal-actions">
        <button on:click={closeModal} class="button button-secondary"
          >{$t("close")}</button
        >
      </div>
    </div>
  </div>
{/if}

<style>
  .modal {
    max-height: 90vh;
    overflow-y: auto;
  }

  .error-message-container,
  .url-container {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    max-width: 100%;
  }

  .error-text,
  .url-text {
    flex: 1;
    word-break: break-all;
    white-space: pre-wrap;
    line-height: 1.4;
    color: var(--text-primary, #1f2937);
    font-family: 'Courier New', monospace;
    font-size: 13px;
  }

  .copy-button {
    background: none;
    border: 1px solid var(--border-color, #e1e5e9);
    border-radius: 4px;
    padding: 4px;
    cursor: pointer;
    color: var(--text-secondary, #6b7280);
    transition: all 0.2s ease;
    flex-shrink: 0;
    min-width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .copy-button:hover {
    background-color: var(--bg-secondary, #f3f4f6);
    color: var(--text-primary, #1f2937);
    border-color: var(--border-color-hover, #d1d5db);
  }

  .copy-button:active {
    transform: scale(0.95);
  }
</style>
