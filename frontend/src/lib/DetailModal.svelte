<script>
  import { createEventDispatcher } from "svelte";
  import { t, formatTimestamp } from "./i18n.js";
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
        document.execCommand("copy");
        textArea.remove();
      }
      showToastMsg($t("copy_success"));
    } catch (err) {
      console.error($t("clipboard_copy_failed"), err);
      showToastMsg($t("copy_failed"));
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
    class="modern-backdrop"
    role="dialog"
    aria-label="Download Details"
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
      <!-- 모던 헤더 -->
      <div class="modal-header">
        <div class="header-content">
          <div class="title-section">
            <div class="icon-wrapper">
              <InfoIcon />
            </div>
            <div class="title-text">
              <h2>{$t("detail_modal_title")}</h2>
              <p class="subtitle">
                {download.file_name || $t("detail_not_available")}
              </p>
            </div>
          </div>
          <button class="close-button" on:click={closeModal}>
            <XIcon />
          </button>
        </div>
      </div>

      <!-- 모던 본문 -->
      <div class="modal-body">
        <table class="detail-table">
          <tbody>
            <tr>
              <th>{$t("detail_original_url")}</th>
              <td>
                <div class="url-container">
                  <span class="url-text" title={download.url}
                    >{download.url}</span
                  >
                  <button
                    class="copy-button"
                    on:click={() => copyToClipboard(download.url)}
                    title={$t("copy_url")}
                  >
                    <CopyIcon />
                  </button>
                </div>
              </td>
            </tr>
            <tr>
              <th>{$t("detail_download_path")}</th>
              <td>
                {#if download.save_path}
                  <div class="url-container">
                    <span class="url-text" title={download.save_path}
                      >{download.save_path}</span
                    >
                    <button
                      class="copy-button"
                      on:click={() => copyToClipboard(download.save_path)}
                      title={$t("copy_path")}
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
              <th>{$t("detail_requested_at")}</th>
              <td>
                {#if download.requested_at}
                  {formatTimestamp(download.requested_at)}
                {:else}
                  {$t("detail_not_available")}
                {/if}
              </td>
            </tr>
            <tr>
              <th>{$t("detail_status")}</th>
              <td>
                <span class="status status-{download.status?.toLowerCase()}">
                  {$t(`download_${download.status?.toLowerCase()}`)}
                </span>
              </td>
            </tr>
            <tr>
              <th>{$t("detail_file_name")}</th>
              <td>
                {#if download.file_name}
                  <div class="url-container">
                    <span class="url-text" title={download.file_name}
                      >{download.file_name}</span
                    >
                    <button
                      class="copy-button"
                      on:click={() => copyToClipboard(download.file_name)}
                      title={$t("copy_filename")}
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
              <th>{$t("detail_total_size")}</th>
              <td>
                {download.total_size
                  ? formatBytes(download.total_size)
                  : $t("detail_not_available")}
              </td>
            </tr>
            <tr>
              <th>{$t("detail_finished_at")}</th>
              <td>
                {#if download.finished_at}
                  {formatTimestamp(download.finished_at)}
                {:else}
                  {$t("detail_not_available")}
                {/if}
              </td>
            </tr>
            <tr>
              <th>{$t("detail_error_message")}</th>
              <td>
                <div class="error-message-container">
                  <span class="error-text" title={download.error || ""}>
                    {download.error || $t("detail_no_error")}
                  </span>
                  {#if download.error}
                    <button
                      class="copy-button"
                      on:click={() => copyToClipboard(download.error)}
                      title={$t("copy_error")}
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

      <!-- 모던 푸터 -->
      <div class="modal-footer">
        <div class="footer-left">
          <div class="status-info">
            <span class="status-badge status-{download.status?.toLowerCase()}">
              {$t(`download_${download.status?.toLowerCase()}`)}
            </span>
            {#if download.requested_at}
              <span class="timestamp">
                {formatTimestamp(download.requested_at)}
              </span>
            {/if}
          </div>
        </div>
        <div class="footer-right">
          <button on:click={closeModal} class="button button-primary">
            {$t("close")}
          </button>
        </div>
      </div>
    </div>
  </div>
{/if}

<style>
  /* 모던 백드롭 */
  .modern-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(8px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
    padding: 20px;
    animation: backdropFadeIn 0.3s ease-out;
  }

  @keyframes backdropFadeIn {
    from {
      opacity: 0;
      backdrop-filter: blur(0px);
    }
    to {
      opacity: 1;
      backdrop-filter: blur(8px);
    }
  }

  /* 모던 모달 컨테이너 */
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
    display: flex;
    flex-direction: column;
    backdrop-filter: blur(16px);
    animation: modalSlideIn 0.4s cubic-bezier(0.16, 1, 0.3, 1);
    resize: none;
  }

  @keyframes modalSlideIn {
    from {
      opacity: 0;
      transform: scale(0.95) translateY(20px);
    }
    to {
      opacity: 1;
      transform: scale(1) translateY(0);
    }
  }

  /* 모던 헤더 */
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
    position: relative;
  }

  .title-section {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex: 1;
  }

  .icon-wrapper {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2.5rem;
    height: 2.5rem;
    background: rgba(255, 255, 255, 0.15);
    border-radius: 8px;
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.2);
  }

  .icon-wrapper :global(svg) {
    width: 1.25rem;
    height: 1.25rem;
    color: white;
  }

  .title-text h2 {
    margin: 0;
    font-size: 1.5rem;
    font-weight: 600;
    color: white;
    line-height: 1.2;
    letter-spacing: 0.05em;
  }

  .subtitle {
    margin: 0.25rem 0 0 0;
    font-size: 0.85rem;
    color: rgba(255, 255, 255, 0.85);
    font-weight: 600;
    letter-spacing: 0.05em;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 300px;
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

  /* 모델 본문 - 스크롤 방식 변경 */
  .modal-body {
    flex: 1;
    overflow: auto;
    padding: 0;
    background: var(--card-background);
    width: 100%;
    resize: none;
    position: relative;
  }

  .modal-body * {
    resize: none !important;
  }

  .error-message-container,
  .url-container {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    width: 100%;
    min-width: 200px;
  }

  .error-text,
  .url-text {
    flex: 1;
    line-height: 1.4;
    color: var(--text-primary, #1f2937);
    font-family: "Courier New", monospace;
    font-size: 13px;
    word-break: break-all;
    min-width: 0;
    max-width: calc(100% - 40px);
    overflow: hidden;
  }

  .copy-button {
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
  }

  .copy-button:hover {
    background-color: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
    transform: scale(1.05);
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
  }

  .copy-button:active {
    transform: scale(0.95);
  }

  .copy-button :global(svg) {
    width: 14px;
    height: 14px;
  }

  /* 모던 푸터 */
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

  .status-info {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  /* 메인 그리드와 동일한 상태 스타일 */
  .status {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.3rem 0.6rem;
    border-radius: 20px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.025em;
    min-width: 70px;
    justify-content: center;
    position: relative;
  }

  .status::before {
    content: "";
    width: 5px;
    height: 5px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .status-pending {
    color: var(--text-primary);
    background-color: var(--card-border);
    border: 1px solid var(--input-border);
  }
  .status-pending::before {
    background-color: #f97316; /* 주황색 도트 */
    animation: pendingPulse 2s infinite; /* 반짝 효과 */
  }

  @keyframes pendingPulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.3;
    }
  }

  .status-downloading {
    color: #fff;
    background-color: var(--primary-color);
  }
  .status-downloading::before {
    background-color: #fff;
    animation: pulse 2s infinite;
  }

  .status-done {
    color: #fff;
    background-color: var(--success-color);
  }
  .status-done::before {
    background-color: #fff;
  }

  .status-failed {
    color: #fff;
    background-color: var(--danger-color);
  }
  .status-failed::before {
    background-color: #fff;
  }

  .status-parsing {
    color: #fff;
    background-color: var(--warning-color); /* Same as proxying */
  }
  .status-parsing::before {
    background-color: #fff;
    animation: pulse 2s infinite;
  }

  .status-proxying {
    color: #fff;
    background-color: var(--warning-color);
  }
  .status-proxying::before {
    background-color: #fff;
    animation: pulse 2s infinite;
  }

  .status-paused,
  .status-stopped {
    color: #fff;
    background-color: #6b7280;
  }
  .status-paused::before,
  .status-stopped::before {
    background-color: #fff;
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

  .status-badge {
    display: inline-flex;
    align-items: center;
    padding: 6px 12px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }

  .status-badge.status-done {
    background: var(--success-color);
    color: white;
  }

  .status-badge.status-parsing {
    background: var(--warning-color);
    color: white;
  }

  .status-badge.status-downloading,
  .status-badge.status-proxying {
    background: var(--primary-color);
    color: white;
  }

  .status-badge.status-failed {
    background: var(--danger-color);
    color: white;
  }

  .status-badge.status-stopped,
  .status-badge.status-pending {
    background: var(--warning-color);
    color: white;
  }

  .timestamp {
    font-size: 0.8rem;
    color: var(--text-secondary);
    font-weight: 500;
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

  /* 테마별 푸터 스타일 */
  :global(body.dark) .modal-footer {
    background: #1f2937;
    border-top-color: #374151;
  }

  :global(body.dark) .timestamp {
    color: #9ca3af;
  }

  :global(body.dracula) .modal-footer {
    background: #282a36;
    border-top-color: #44475a;
  }

  :global(body.dracula) .timestamp {
    color: #6272a4;
  }

  /* 테이블 - 최소 크기 보장 */
  .detail-table {
    display: block;
    width: 100%;
    min-width: 100%;
    overflow: visible;
    resize: none;
    user-select: none;
  }

  .detail-table tbody {
    display: block;
    width: 100%;
    min-width: 100%;
  }

  .detail-table tr {
    display: flex;
    width: 100%;
    min-width: 100%;
    margin: 0;
    padding: 0;
  }

  .detail-table th,
  .detail-table td {
    padding: 12px 16px;
    margin: 0;
    border-bottom: 1px solid var(--card-border);
    font-size: 0.85em;
    overflow: hidden;
    word-break: break-all;
    resize: none;
  }

  .detail-table th {
    flex: 0 0 180px;
    font-weight: 600;
    color: var(--text-secondary);
    text-align: center;
    white-space: nowrap;
    text-overflow: ellipsis;
  }

  .detail-table td {
    flex: 1;
    color: var(--text-primary);
    word-break: break-all;
    word-wrap: break-word;
    min-width: 200px;
  }

  /* 테마별 스타일 */
  :global(body.dark) .detail-table th {
    background-color: transparent;
    color: #9ca3af;
  }

  :global(body.dark) .detail-table td {
    background-color: #1f2937;
    color: #f3f4f6;
  }

  :global(body.dark) .detail-table th,
  :global(body.dark) .detail-table td {
    border-bottom-color: #4b5563;
  }

  /* 드라큘라 테마 */
  :global(body.dracula) .detail-table th {
    background-color: transparent;
    color: #6272a4;
  }

  :global(body.dracula) .detail-table td {
    background-color: #282a36;
    color: #f8f8f2;
  }

  :global(body.dracula) .detail-table th,
  :global(body.dracula) .detail-table td {
    border-bottom-color: #44475a;
  }

  /* 호버 효과 */
  .detail-table tr:hover td {
    background-color: var(--bg-secondary);
  }

  :global(body.dark) .detail-table tr:hover td {
    background-color: #374151;
  }

  :global(body.dracula) .detail-table tr:hover td {
    background-color: #44475a;
  }

  /* 첫 번째 행 상단 테두리 제거 (모달 테두리와 일체화) */
  .detail-table tr:first-child th,
  .detail-table tr:first-child td {
    border-top: none;
  }

  /* 모바일 반응형 스타일 */
  @media (max-width: 480px) {
    .modern-backdrop {
      padding: 10px;
    }

    .modern-modal {
      width: 100%;
      max-width: 100vw;
      height: 90vh;
      max-height: 90vh;
      border-radius: 12px;
    }

    .modal-header {
      padding: 1rem;
    }

    .header-content {
      /* Keep normal flex layout - don't change to column */
      align-items: center;
      gap: 0.75rem;
    }

    .title-section {
      /* Keep normal flex layout */
      flex: 1;
      gap: 0.5rem;
    }

    .icon-wrapper {
      width: 2rem;
      height: 2rem;
    }

    .icon-wrapper :global(svg) {
      width: 1rem;
      height: 1rem;
    }

    .title-text h2 {
      font-size: 1.1rem;
    }

    .subtitle {
      max-width: 200px;
      font-size: 0.75rem;
    }

    .close-button {
      /* Keep normal positioning - don't make absolute */
      width: 2rem;
      height: 2rem;
      flex-shrink: 0;
    }

    .close-button :global(svg) {
      width: 1rem;
      height: 1rem;
    }

    .detail-table th {
      flex: 0 0 120px;
      font-size: 0.75rem;
      padding: 8px 12px;
    }

    .detail-table td {
      padding: 8px 12px;
      font-size: 0.75rem;
      min-width: 0;
    }

    .modal-footer {
      padding: 1rem;
      flex-direction: column-reverse;
      align-items: stretch;
      gap: 1rem;
    }

    .footer-left,
    .footer-right {
      width: 100%;
      justify-content: center;
    }

    .status-info {
      text-align: center;
    }

    .button {
      width: 100%;
      min-width: unset;
    }
  }

  /* 마지막 행 하단 테두리 제거 (모달 테두리와 일체화) */
  .detail-table tr:last-child th,
  .detail-table tr:last-child td {
    border-bottom: none;
  }

  /* 페이지네이션 스타일 */
  .pagination {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 8px;
    padding: 16px 20px;
    border-top: 1px solid var(--card-border);
    background: var(--bg-primary);
  }

  .page-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border: 1px solid var(--card-border);
    background: var(--card-background);
    color: var(--text-primary);
    border-radius: 6px;
    cursor: pointer;
    font-size: 14px;
    font-weight: 500;
    transition: all 0.2s ease;
  }

  .page-btn:hover:not(:disabled) {
    background: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
  }

  .page-btn.active {
    background: var(--primary-color);
    color: white;
    border-color: var(--primary-color);
  }

  .page-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    background: var(--card-border);
  }

  /* 테마별 페이지네이션 스타일 */
  :global(body.dark) .pagination {
    background: #1f2937;
    border-top-color: #374151;
  }

  :global(body.dark) .page-btn {
    background: #374151;
    border-color: #4b5563;
    color: #f3f4f6;
  }

  :global(body.dark) .page-btn:disabled {
    background: #4b5563;
  }

  :global(body.dracula) .pagination {
    background: #282a36;
    border-top-color: #44475a;
  }

  :global(body.dracula) .page-btn {
    background: #44475a;
    border-color: #6272a4;
    color: #f8f8f2;
  }

  :global(body.dracula) .page-btn:disabled {
    background: #6272a4;
  }

  /* 컨테이너가 있는 셀은 정상 표시 */

  /* 모바일 반응형 스타일 */
  @media (max-width: 768px) {
    .modern-modal {
      width: 95vw;
      height: 85vh;
      max-height: 500px;
      min-height: 350px;
      margin: 10px;
    }

    .modal-header {
      padding: 20px 16px;
    }

    .header-content {
      flex-direction: column;
      align-items: flex-start;
      gap: 16px;
    }

    .title-section {
      margin-right: 0;
      width: 100%;
    }

    .close-button {
      position: absolute;
      right: 16px;
      width: 32px;
      height: 32px;
    }

    .close-button :global(svg) {
      width: 16px;
      height: 16px;
    }

    .icon-wrapper {
      width: 40px;
      height: 40px;
    }

    .icon-wrapper :global(svg) {
      width: 20px;
      height: 20px;
    }

    .title-text h2 {
      font-size: 1.25rem;
    }

    .subtitle {
      max-width: 250px;
    }

    .detail-table th,
    .detail-table td {
      padding: 12px 16px;
      font-size: 0.85rem;
    }

    .detail-table th,
    .detail-table td {
      padding: 8px 12px;
      font-size: 0.8rem;
    }

    .detail-table th {
      width: 120px;
    }

    .copy-button {
      min-width: 24px;
      height: 24px;
      padding: 4px;
    }

    .copy-button :global(svg) {
      width: 12px;
      height: 12px;
    }

    .modal-footer {
      padding: 16px;
    }

    .footer-content {
      flex-direction: column;
      gap: 12px;
      align-items: stretch;
    }

    .status-info {
      justify-content: center;
      flex-wrap: wrap;
    }

    .footer-actions {
      justify-content: center;
    }

    .modern-button {
      width: 100%;
      min-width: auto;
    }
  }
</style>
