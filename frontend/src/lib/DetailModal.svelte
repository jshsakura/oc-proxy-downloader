<script>
  import { createEventDispatcher } from "svelte";
  import { t, formatTimestamp } from "./i18n.js";
  import { modalFocus } from "./modal.js";
  import XIcon from "../icons/XIcon.svelte";
  import CopyIcon from "../icons/CopyIcon.svelte";
  import { toast } from "svelte-sonner";

  export let showModal = false;
  export let download = {};

  const dispatch = createEventDispatcher();

  $: status = (download.status || "pending").toLowerCase();
  $: isFichier = /(?:^|\/\/)1fichier\.com(?:\/|\?)/i.test(download.url || "");
  $: progress = download.total_size > 0
    ? Math.min(100, Math.round(((download.downloaded_size || 0) / download.total_size) * 100))
    : 0;

  // The backend stores "<message>\n<label>: <action>" as one string, with the
  // label in the user's language. Showing it as one paragraph made the cause and
  // the next step run together, so they are rendered as two blocks. Only a short
  // "label:" line counts as the action; any other multi-line text stays whole.
  const ACTION_LINE = /^[^:：\n]{1,20}[:：]\s*(\S[\s\S]*)$/;

  function splitErrorMessage(message) {
    const text = String(message || "").trim();
    const lineEnd = text.indexOf("\n");
    const action = lineEnd < 0 ? null : ACTION_LINE.exec(text.slice(lineEnd + 1).trim());
    if (!action) return { head: text, action: "" };
    return { head: text.slice(0, lineEnd).trim(), action: action[1].replace(/\s*\n\s*/g, " ") };
  }

  $: errorParts = splitErrorMessage(download.error_message);

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

  async function copyToClipboard(value) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        const input = document.createElement("textarea");
        input.value = value;
        input.style.position = "fixed";
        input.style.left = "-9999px";
        document.body.appendChild(input);
        input.select();
        document.execCommand("copy");
        input.remove();
      }
      toast.success($t("copy_success"));
    } catch (error) {
      console.error($t("clipboard_copy_failed"), error);
      toast.error($t("copy_failed"));
    }
  }
</script>

{#if showModal}
  <div class="modern-backdrop">
    <div
      class="modern-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="detail-modal-title"
      tabindex="-1"
      use:modalFocus={{ onEscape: closeModal }}
    >
      <header class="modal-header">
        <div class="title-section">
          <span class="eyebrow">{$t("detail_modal_title")}</span>
          <div class="file-title-row">
            <h2 id="detail-modal-title">{download.filename || $t("detail_not_available")}</h2>
            {#if download.filename}
              <button
                type="button"
                class="copy-button"
                on:click={() => copyToClipboard(download.filename)}
                aria-label={$t("copy_filename")}
                title={$t("copy_filename")}
              ><CopyIcon /></button>
            {/if}
          </div>
        </div>
        <button type="button" class="close-button" on:click={closeModal} aria-label={$t("close")} title={$t("close")}><XIcon /></button>
      </header>

      <div class="modal-body">
        <section class="overview" aria-label={$t("detail_status")}>
          <div class="overview-line">
            <span class="status-badge status-{status}">{$t(`download_${status}`)}</span>
            {#if download.total_size}
              <span class="file-size">{formatBytes(download.total_size)}</span>
            {/if}
          </div>
          {#if status === "downloading" && download.total_size}
            <div class="progress-line">
              <span>{formatBytes(download.downloaded_size || 0)} / {formatBytes(download.total_size)}</span>
              <strong>{progress}%</strong>
            </div>
            <div class="progress-track" role="progressbar" aria-label={$t("download_downloading")} aria-valuenow={progress} aria-valuemin="0" aria-valuemax="100">
              <span style:width="{progress}%"></span>
            </div>
          {/if}
          {#if status === "pending" && isFichier}
            <p class="queue-note">{$t("detail_fichier_queue_note")}</p>
          {/if}
        </section>

        {#if download.error_message}
          <section class="detail-section error-section" aria-label={$t("detail_error_message")}>
            <h3>{$t("detail_error_message")}</h3>
            <div class="value-line">
              <span class="error-text-block">{errorParts.head}</span>
              <button type="button" class="copy-button" on:click={() => copyToClipboard(download.error_message)} aria-label={$t("copy_error")} title={$t("copy_error")}><CopyIcon /></button>
            </div>
            {#if errorParts.action}
              <div class="error-action">
                <span class="error-action-label">{$t("detail_error_action")}</span>
                <span class="error-action-text">{errorParts.action}</span>
              </div>
            {/if}
          </section>
        {/if}

        <section class="detail-section" aria-label={$t("detail_download_url")}>
          <h3>{$t("detail_download_url")}</h3>
          <div class="value-line">
            <span class="long-value">{download.url || $t("detail_not_available")}</span>
            {#if download.url}
              <button type="button" class="copy-button" on:click={() => copyToClipboard(download.url)} aria-label={$t("copy_url")} title={$t("copy_url")}><CopyIcon /></button>
            {/if}
          </div>
        </section>

        {#if download.original_url && download.original_url !== download.url}
          <section class="detail-section" aria-label={$t("detail_parsed_link")}>
            <h3>{$t("detail_parsed_link")}</h3>
            <div class="value-line">
              <span class="long-value">{download.original_url}</span>
              <button type="button" class="copy-button" on:click={() => copyToClipboard(download.original_url)} aria-label={$t("copy_url")} title={$t("copy_url")}><CopyIcon /></button>
            </div>
          </section>
        {/if}

        {#if download.save_path}
          <section class="detail-section" aria-label={$t("detail_download_path")}>
            <h3>{$t("detail_download_path")}</h3>
            <div class="value-line">
              <span class="long-value">{download.save_path}</span>
              <button type="button" class="copy-button" on:click={() => copyToClipboard(download.save_path)} aria-label={$t("copy_path")} title={$t("copy_path")}><CopyIcon /></button>
            </div>
          </section>
        {/if}

        <dl class="time-list">
          <div>
            <dt>{$t("detail_requested_at")}</dt>
            <dd>{download.created_at ? formatTimestamp(download.created_at) : $t("detail_not_available")}</dd>
          </div>
          {#if download.finished_at}
            <div>
              <dt>{$t("detail_finished_at")}</dt>
              <dd>{formatTimestamp(download.finished_at)}</dd>
            </div>
          {/if}
        </dl>

      </div>

      <footer class="modal-footer">
        <button type="button" on:click={closeModal} class="button button-primary">{$t("close")}</button>
      </footer>
    </div>
  </div>
{/if}

<style>
  .modern-backdrop {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 20px;
    background: rgba(0, 0, 0, 0.68);
    backdrop-filter: blur(6px);
  }

  .modern-modal {
    width: min(100%, 720px);
    max-height: min(88dvh, 760px);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: var(--card-background);
    color: var(--text-primary);
    border: 1px solid var(--card-border);
    border-radius: 14px;
    box-shadow: 0 24px 60px rgba(0, 0, 0, 0.32);
  }

  .modern-modal:focus { outline: none; }

  .modal-header {
    display: flex;
    align-items: flex-start;
    gap: 20px;
    padding: 24px 28px 20px;
    border-bottom: 1px solid var(--card-border);
  }

  .title-section { flex: 1; min-width: 0; }
  .eyebrow {
    display: block;
    margin-bottom: 8px;
    color: var(--text-secondary);
    font-size: 12px;
    font-weight: 600;
  }
  .file-title-row { display: flex; align-items: flex-start; gap: 10px; min-width: 0; }
  h2 {
    min-width: 0;
    margin: 0;
    font-size: 18px;
    font-weight: 700;
    line-height: 1.45;
    overflow-wrap: anywhere;
  }
  h3 {
    margin: 0 0 9px;
    color: var(--text-secondary);
    font-size: 12px;
    font-weight: 600;
  }

  .close-button, .copy-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: none;
    width: 32px;
    height: 32px;
    padding: 0;
    border: 1px solid var(--card-border);
    border-radius: 8px;
    background: var(--bg-secondary);
    color: var(--text-secondary);
    cursor: pointer;
  }
  .close-button:hover, .copy-button:hover {
    color: var(--text-primary);
    border-color: var(--primary-color);
  }
  .close-button:focus-visible, .copy-button:focus-visible, .modal-footer button:focus-visible {
    outline: 2px solid var(--primary-color);
    outline-offset: 2px;
  }
  .close-button :global(svg), .copy-button :global(svg) { width: 16px; height: 16px; }

  .modal-body {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 24px 28px;
  }
  /* Every block is its own card instead of rows divided by hairlines. */
  .overview, .detail-section, .time-list, .error-section {
    box-sizing: border-box;
    padding: 16px 18px;
    border: 1px solid var(--card-border);
    border-radius: 12px;
    background: var(--bg-secondary);
  }
  .overview-line { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
  .status-badge {
    --status-color: var(--status-pending-border);
    --status-text: var(--status-pending-text);
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 5px 10px;
    border: 1px solid color-mix(in srgb, var(--status-color) 45%, transparent);
    border-radius: 999px;
    color: var(--status-text);
    background: color-mix(in srgb, var(--status-color) 14%, transparent);
    font-size: 12px;
    font-weight: 700;
  }
  .status-badge::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--status-color); }
  .status-badge.status-downloading { --status-color: var(--status-downloading-border); --status-text: var(--status-downloading-text); }
  .status-badge.status-done { --status-color: var(--status-done-border); --status-text: var(--status-done-text); }
  .status-badge.status-parsing { --status-color: var(--status-parsing-border); --status-text: var(--status-parsing-text); }
  .status-badge.status-failed { --status-color: var(--status-failed-border); --status-text: var(--status-failed-text); }
  .status-badge.status-stopped { --status-color: var(--status-stopped-border); --status-text: var(--status-stopped-text); }
  .file-size { color: var(--text-secondary); font-size: 14px; }
  .progress-line { display: flex; justify-content: space-between; gap: 12px; margin-top: 18px; color: var(--text-secondary); font-size: 12px; }
  .progress-line strong { color: var(--text-primary); }
  .progress-track { height: 5px; margin-top: 8px; overflow: hidden; border-radius: 999px; background: var(--bg-secondary); }
  .progress-track span { display: block; height: 100%; background: var(--primary-color); }
  .queue-note { margin: 14px 0 0; color: var(--text-secondary); font-size: 13px; line-height: 1.55; }

  .value-line { display: flex; align-items: flex-start; gap: 12px; min-width: 0; }
  .long-value, .error-text-block {
    flex: 1;
    min-width: 0;
    color: var(--text-primary);
    font-size: 13px;
    line-height: 1.6;
    overflow-wrap: anywhere;
    white-space: pre-wrap;
  }
  .long-value { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  .error-section {
    border-color: color-mix(in srgb, var(--status-failed-border) 55%, var(--card-border));
    background: color-mix(in srgb, var(--status-failed-border) 8%, var(--bg-secondary));
  }
  .error-section h3 { color: var(--status-failed-text); }
  .error-text-block { font-weight: 600; font-size: 14px; }
  .error-action {
    display: flex;
    gap: 12px;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px dashed var(--card-border);
    font-size: 13px;
    line-height: 1.6;
  }
  .error-action-label {
    flex: none;
    align-self: flex-start;
    padding: 1px 9px;
    border-radius: 999px;
    background: color-mix(in srgb, var(--status-failed-border) 18%, transparent);
    color: var(--status-failed-text);
    font-size: 12px;
    font-weight: 700;
    line-height: 1.7;
  }
  .error-action-text { min-width: 0; overflow-wrap: anywhere; }

  .time-list { display: flex; flex-wrap: wrap; gap: 14px 36px; margin: 0; }
  .time-list > div { min-width: 180px; }
  .time-list dt { margin-bottom: 7px; color: var(--text-secondary); font-size: 12px; font-weight: 600; }
  .time-list dd { margin: 0; font-size: 13px; }

  .modal-footer { display: flex; justify-content: flex-end; padding: 16px 28px; border-top: 1px solid var(--card-border); }

  @media (max-width: 600px) {
    .modern-backdrop { padding: 10px; align-items: flex-end; }
    .modern-modal { width: 100%; max-height: 92dvh; box-sizing: border-box; border-radius: 12px; }
    .modal-header { padding: 18px; gap: 12px; }
    .modal-body { padding: 18px; gap: 12px; }
    .modal-footer { padding: 14px 18px; }
    .modal-footer button { width: 100%; }
    h2 { font-size: 16px; }
    .close-button { flex-shrink: 0; }
  }
</style>
