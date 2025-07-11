<script>
  import { createEventDispatcher } from "svelte";
  import { t } from "./i18n.js";
  import InfoIcon from "../icons/InfoIcon.svelte";
  import XIcon from "../icons/XIcon.svelte";
  import { onMount, onDestroy } from "svelte";

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
              <td>{download.url}</td>
            </tr>
            <tr>
              <th>{$t("detail_actual_file_url")}:</th>
              <td>
                {#if download.direct_link}
                  <a
                    href={download.direct_link}
                    target="_blank"
                    rel="noopener noreferrer">{download.direct_link}</a
                  >
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
              <td>{download.error || $t("detail_no_error")}</td>
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
</style>
