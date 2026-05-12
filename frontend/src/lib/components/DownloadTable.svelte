<script>
  import { t } from "../i18n.js";
  import { 
    formatBytes, 
    formatWaitTime, 
    formatSpeed, 
    formatDate, 
    getDownloadProgress 
  } from "../utils.js";
  import { api } from "../api.js";
  import { toast } from "svelte-sonner";
  
  import PauseIcon from "../../icons/PauseIcon.svelte";
  import StopIcon from "../../icons/StopIcon.svelte";
  import ResumeIcon from "../../icons/ResumeIcon.svelte";
  import RetryIcon from "../../icons/RetryIcon.svelte";
  import DeleteIcon from "../../icons/DeleteIcon.svelte";
  import InfoIcon from "../../icons/InfoIcon.svelte";
  import LinkCopyIcon from "../../icons/LinkCopyIcon.svelte";
  import ChevronLeftIcon from "../../icons/ChevronLeftIcon.svelte";
  import ChevronRightIcon from "../../icons/ChevronRightIcon.svelte";

  export let currentTab;
  export let paginatedDownloads;
  export let filteredDownloads;
  export let isDownloadsLoading;
  export let downloadProxyInfo;
  export let downloadWaitInfo;
  export let currentTime;
  export let currentPage;
  export let totalPages;
  export let itemsPerPage;
  export let goToPage;
  export let openDetailModal;
  export let deleteDownload;
  export let redownload;
  export let copyDownloadLink;
  export let callApi;
  export let getStatusTooltip;
  export let downloads; // For local update on toggle

  async function toggleProxy(download) {
    try {
      const result = await api.toggleProxy(download.id);
      // Update local state
      downloads = downloads.map((d) =>
        d.id === download.id
          ? { ...d, use_proxy: result.use_proxy }
          : d
      );
      toast.success($t("proxy_mode_changed"));
    } catch (error) {
      console.error("Proxy toggle error:", error);
      toast.error($t("proxy_mode_change_error"));
    }
  }

  function formatFullDateTime(dateString) {
    if (!dateString) return "-";
    return new Date(dateString).toLocaleString();
  }
</script>

<div
  class="table-container"
  class:empty-table={filteredDownloads.length === 0}
>
  <table>
    <thead>
      <tr>
        <th>{$t("table_header_file_name")}</th>
        <th class="center-align">{$t("table_header_status")}</th>
        <th class="center-align">{$t("table_header_size")}</th>
        <th class="center-align">{$t("table_header_progress")}</th>
        {#if currentTab !== "completed"}
          <th class="center-align">{$t("table_header_speed")}</th>
        {/if}
        <th class="center-align">{$t("table_header_requested_date")}</th>
        <th class="center-align">{$t("table_header_proxy")}</th>
        <th class="center-align actions-header"
          >{$t("table_header_actions")}</th
        >
      </tr>
    </thead>
    <tbody>
      {#if isDownloadsLoading}
        <tr>
          <td colspan={currentTab === "completed" ? 7 : 8}>
            <div class="table-loading-container">
              <div class="modal-spinner"></div>
              <div class="modal-loading-text">{$t("loading")}</div>
            </div>
          </td>
        </tr>
      {:else if filteredDownloads.length === 0}
        <tr class="empty-row">
          <td colspan={currentTab === "completed" ? 7 : 8} class="center-align">
            {currentTab === "working"
              ? $t("no_working_downloads")
              : $t("no_completed_downloads")}
          </td>
        </tr>
      {:else}
        {#each paginatedDownloads as download (download.id)}
          <tr class="status-{download.status?.toLowerCase()}">
            <td class="filename-cell">
              <button
                type="button"
                class="filename-wrapper-btn"
                on:click={() => openDetailModal(download)}
                title={download.filename || $t("file_name_na")}
              >
                <span class="filename-text"
                  >{download.filename || $t("file_name_na")}</span
                >
              </button>
            </td>
            <td class="center-align">
              <span
                class="status-badge status-{download.status?.toLowerCase()}"
                title={getStatusTooltip(download)}
              >
                {$t(`status_${download.status?.toLowerCase()}`) || download.status}
                {#if download.status?.toLowerCase() === "waiting" && downloadWaitInfo[download.id]}
                  ({formatWaitTime(
                    Math.max(0, (downloadWaitInfo[download.id] - currentTime) / 1000)
                  )})
                {/if}
              </span>
            </td>
            <td class="center-align">
              {formatBytes(download.total_size || download.file_size)}
            </td>
            <td class="center-align">
              <div class="progress-container">
                <div
                  class="progress-bar"
                  style="width: {getDownloadProgress(download)}%"
                ></div>
                <span class="progress-text"
                  >{getDownloadProgress(download)}%</span
                >
              </div>
            </td>
            {#if currentTab !== "completed"}
              <td class="center-align speed-cell">
                {#if download.status?.toLowerCase() === "downloading"}
                  <span class="speed-text"
                    >{formatSpeed(download.download_speed)}</span
                  >
                {:else if download.status?.toLowerCase() === "proxying" || download.status?.toLowerCase() === "parsing"}
                  <span
                    class="speed-text parsing-indicator {download.use_proxy
                      ? 'proxy-loading'
                      : 'local-loading'}"
                  >
                    <span class="parsing-dots">•••</span>
                  </span>
                {:else}
                  <span class="speed-text-empty">-</span>
                {/if}
              </td>
            {/if}
            <td
              class="center-align"
              title={formatFullDateTime(download.created_at)}
            >
              {formatDate(download.created_at)}
            </td>
            <td class="proxy-toggle-cell">
              <button
                type="button"
                class="grid-proxy-toggle {download.use_proxy
                  ? 'proxy'
                  : 'local'}"
                disabled={!["stopped", "failed"].includes(download.status?.toLowerCase())}
                title={download.use_proxy
                  ? $t("proxy_mode")
                  : $t("local_mode")}
                on:click={() => toggleProxy(download)}
                aria-label={download.use_proxy
                  ? $t("proxy_mode")
                  : $t("local_mode")}
              >
                <div class="grid-toggle-slider"></div>
                <div class="grid-toggle-icons"></div>
              </button>
            </td>
            <td class="actions-cell">
              {#if currentTab === "completed"}
                <button
                  class="button-icon"
                  title={$t("redownload")}
                  on:click={() => redownload(download)}
                  aria-label={$t("redownload")}
                >
                  <RetryIcon />
                </button>
                <button
                  class="button-icon"
                  title={$t("copy_download_link")}
                  on:click={() => copyDownloadLink(download)}
                  aria-label={$t("copy_download_link")}
                >
                  <LinkCopyIcon />
                </button>
                <button
                  class="button-icon"
                  title={$t("action_details")}
                  on:click={() => openDetailModal(download)}
                  aria-label={$t("action_details")}
                >
                  <InfoIcon />
                </button>
                <button
                  class="button-icon"
                  title={$t("action_delete")}
                  on:click={() => deleteDownload(download.id)}
                  aria-label={$t("action_delete")}
                >
                  <DeleteIcon />
                </button>
              {:else}
                {#if ["downloading", "proxying", "pending", "parsing", "waiting"].includes(download.status?.toLowerCase())}
                  <button
                    class="button-icon"
                    title={$t("action_pause")}
                    on:click={() => callApi(`/api/downloads/stop/${download.id}`)}
                    aria-label={$t("action_pause")}
                  >
                    <StopIcon />
                  </button>
                {:else if ["stopped"].includes(download.status?.toLowerCase())}
                  <button
                    class="button-icon"
                    title={download.progress > 0
                      ? $t("action_resume")
                      : $t("action_start")}
                    on:click={() => callApi(`/api/downloads/start/${download.id}`)}
                    aria-label={download.progress > 0
                      ? $t("action_resume")
                      : $t("action_start")}
                  >
                    <ResumeIcon />
                  </button>
                {/if}
                {#if download.status?.toLowerCase() === "failed"}
                  <button
                    class="button-icon"
                    title={$t("action_retry")}
                    on:click={() => callApi(`/api/retry/${download.id}`)}
                    aria-label={$t("action_retry")}
                  >
                    <RetryIcon />
                  </button>
                {/if}
                <button
                  class="button-icon"
                  title={$t("copy_download_link")}
                  on:click={() => copyDownloadLink(download)}
                  aria-label={$t("copy_download_link")}
                >
                  <LinkCopyIcon />
                </button>
                <button
                  class="button-icon"
                  title={$t("action_details")}
                  on:click={() => openDetailModal(download)}
                  aria-label={$t("action_details")}
                >
                  <InfoIcon />
                </button>
                <button
                  class="button-icon"
                  title={$t("action_delete")}
                  on:click={() => deleteDownload(download.id)}
                  aria-label={$t("action_delete")}
                >
                  <DeleteIcon />
                </button>
              {/if}
            </td>
          </tr>
        {/each}
      {/if}
    </tbody>
  </table>
</div>

<!-- 페이지네이션 - 항상 표시 -->
<div class="pagination-footer">
  <div class="page-info">
    {#if totalPages > 1}
      <div>{$t("pagination_page_info", { currentPage, totalPages })}</div>
    {/if}
    <div class="items-info">
      {#if filteredDownloads.length > 0}
        {$t("pagination_items_info", {
          total: filteredDownloads.length,
          start: (currentPage - 1) * itemsPerPage + 1,
          end: Math.min(
            currentPage * itemsPerPage,
            filteredDownloads.length
          ),
        })}
      {/if}
    </div>
  </div>
  {#if totalPages > 1}
    <div class="pagination-buttons">
      <!-- 데스크톱용 스마트 페이지네이션 -->
      <div class="pagination-desktop">
        <button
          class="page-number-btn prev-next-btn"
          on:click={() => goToPage(currentPage - 1)}
          disabled={currentPage <= 1}
        >
          <ChevronLeftIcon />
        </button>

        <!-- 스마트 페이지 번호 버튼들 -->
        {#if totalPages <= 7}
          {#each Array(totalPages) as _, i}
            {@const pageNum = i + 1}
            <button
              class="page-number-btn"
              class:active={currentPage === pageNum}
              on:click={() => goToPage(pageNum)}
            >
              {pageNum}
            </button>
          {/each}
        {:else}
          {#if currentPage <= 4}
            {#each [1,2,3,4,5] as pageNum}
              <button
                class="page-number-btn"
                class:active={currentPage === pageNum}
                on:click={() => goToPage(pageNum)}
              >
                {pageNum}
              </button>
            {/each}
            <span class="page-dots">...</span>
            <button
              class="page-number-btn"
              on:click={() => goToPage(totalPages)}
            >
              {totalPages}
            </button>
          {:else if currentPage >= totalPages - 3}
            <button
              class="page-number-btn"
              on:click={() => goToPage(1)}
            >
              1
            </button>
            <span class="page-dots">...</span>
            {#each [totalPages-4, totalPages-3, totalPages-2, totalPages-1, totalPages] as pageNum}
              <button
                class="page-number-btn"
                class:active={currentPage === pageNum}
                on:click={() => goToPage(pageNum)}
              >
                {pageNum}
              </button>
            {/each}
          {:else}
            <button
              class="page-number-btn"
              on:click={() => goToPage(1)}
            >
              1
            </button>
            <span class="page-dots">...</span>
            {#each [currentPage-2, currentPage-1, currentPage, currentPage+1, currentPage+2] as pageNum}
              <button
                class="page-number-btn"
                class:active={currentPage === pageNum}
                on:click={() => goToPage(pageNum)}
              >
                {pageNum}
              </button>
            {/each}
            <span class="page-dots">...</span>
            <button
              class="page-number-btn"
              on:click={() => goToPage(totalPages)}
            >
              {totalPages}
            </button>
          {/if}
        {/if}

        <button
          class="page-number-btn prev-next-btn"
          on:click={() => goToPage(currentPage + 1)}
          disabled={currentPage >= totalPages}
        >
          <ChevronRightIcon />
        </button>
      </div>

      <!-- 모바일용 간단한 페이지네이션 -->
      <div class="pagination-mobile">
        <button
          class="page-number-btn prev-next-btn"
          on:click={() => goToPage(currentPage - 1)}
          disabled={currentPage <= 1}
        >
          <ChevronLeftIcon />
        </button>
        <span class="mobile-page-indicator">{currentPage} / {totalPages}</span>
        <button
          class="page-number-btn prev-next-btn"
          on:click={() => goToPage(currentPage + 1)}
          disabled={currentPage >= totalPages}
        >
          <ChevronRightIcon />
        </button>
      </div>
    </div>
  {/if}
</div>
