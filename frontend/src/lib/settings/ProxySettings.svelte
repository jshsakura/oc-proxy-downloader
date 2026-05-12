<script>
  import { t } from "../i18n.js";
  import CopyIcon from "../../icons/CopyIcon.svelte";

  export let userProxies;
  export let newProxyAddress;
  export let newProxyDescription;
  export let isAddingProxy;
  export let currentPage;
  export let itemsPerPage;
  export let totalPages;
  export let paginatedProxies;
  export let addProxy;
  export let deleteProxy;
  export let toggleProxy;
</script>

<div class="form-group proxy-management">
  <div class="proxy-management-title">{$t("proxy_management")}</div>
</div>

<div class="form-group proxy-form-section">
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
      {isAddingProxy ? $t("adding_proxy") : $t("proxy_add_button")}
    </button>
  </div>
</div>

<div class="form-group proxy-list-section">
  {#if userProxies.length === 0}
    <div class="proxy-empty-state">
      <p>{$t("proxy_empty_message")}</p>
      <small>{$t("proxy_empty_description")}</small>
    </div>
  {:else}
    <div class="proxy-table-container">
      <div class="proxy-table-wrapper">
        <table class="proxy-table">
          <thead>
            <tr>
              <th class="text-center">{$t("proxy_address")}</th>
              <th class="text-center">{$t("proxy_type")}</th>
              <th class="text-center">{$t("proxy_status")}</th>
              <th class="text-center">{$t("proxy_added_date")}</th>
              <th class="text-center">{$t("proxy_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {#each paginatedProxies as proxy, i (proxy.id || i)}
              <tr class="proxy-row {proxy.is_active ? 'active' : 'inactive'}">
                <td class="proxy-address" title={proxy.address}>
                  <div class="proxy-address-content">
                    <span class="proxy-url">{proxy.address}</span>
                    <button
                      class="copy-proxy-button"
                      on:click={() => navigator.clipboard?.writeText(proxy.address)}
                      title="Copy address"
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
                    {proxy.proxy_type === "list"
                      ? $t("proxy_type_list")
                      : $t("proxy_type_single")}
                  </span>
                </td>
                <td class="text-center">
                  <span
                    class="proxy-status-badge {proxy.is_active
                      ? 'active'
                      : 'inactive'}"
                  >
                    {proxy.is_active
                      ? $t("proxy_status_active")
                      : $t("proxy_status_inactive")}
                  </span>
                </td>
                <td class="proxy-date text-center">
                  {proxy.added_at
                    ? new Date(proxy.added_at).toLocaleDateString()
                    : "-"}
                </td>
                <td class="proxy-actions">
                  <div class="proxy-action-buttons">
                    <button
                      class="proxy-action-btn toggle-btn {proxy.is_active
                        ? 'active'
                        : 'inactive'}"
                      on:click={() => toggleProxy(proxy.id)}
                      title={proxy.is_active
                        ? $t("proxy_toggle_inactive")
                        : $t("proxy_toggle_active")}
                      aria-label={proxy.is_active
                        ? $t("proxy_toggle_inactive")
                        : $t("proxy_toggle_active")}
                      type="button"
                    >
                      {#if proxy.is_active}
                        <svg
                          width="12"
                          height="12"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        >
                          <rect x="6" y="4" width="4" height="16"></rect>
                          <rect x="14" y="4" width="4" height="16"></rect>
                        </svg>
                      {:else}
                        <svg
                          width="12"
                          height="12"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        >
                          <polygon points="5,3 19,12 5,21"></polygon>
                        </svg>
                      {/if}
                    </button>
                    <button
                      class="proxy-action-btn delete-btn"
                      on:click={() => deleteProxy(proxy.id)}
                      title={$t("proxy_delete")}
                      aria-label={$t("proxy_delete")}
                      type="button"
                    >
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      >
                        <polyline points="3,6 5,6 21,6"></polyline>
                        <path
                          d="m19,6v14a2,2 0 0,1 -2,2H7a2,2 0 0,1 -2,-2V6m3,0V4a2,2 0 0,1 2,-2h4a2,2 0 0,1 2,2v2"
                        ></path>
                        <line x1="10" y1="11" x2="10" y2="17"></line>
                        <line x1="14" y1="11" x2="14" y2="17"></line>
                      </svg>
                    </button>
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>

    <!-- 프록시 테이블 푸터 -->
    <div class="proxy-table-footer">
      <div class="proxy-footer-info">
        <div class="proxy-count-info">
          {$t("total_proxies", { count: userProxies.length })}
        </div>
        {#if totalPages > 1}
          <div class="proxy-page-info">
            {(currentPage - 1) * itemsPerPage + 1}~{Math.min(
              currentPage * itemsPerPage,
              userProxies.length
            )} 표시
          </div>
        {/if}
      </div>

      {#if totalPages > 1}
        <div class="proxy-pagination-buttons">
          <button
            class="proxy-page-number-btn proxy-prev-next-btn"
            on:click={() => (currentPage = currentPage - 1)}
            disabled={currentPage <= 1}
          >
            ←
          </button>

          <!-- 페이지 번호 버튼들 - 최대 5개 표시 -->
          {#each Array(Math.min(totalPages, 5)) as _, i}
            {@const pageNum = Math.max(1, currentPage - 2) + i}
            {#if pageNum <= totalPages}
              <button
                class="proxy-page-number-btn"
                class:active={currentPage === pageNum}
                on:click={() => (currentPage = pageNum)}
              >
                {pageNum}
              </button>
            {/if}
          {/each}

          <button
            class="proxy-page-number-btn proxy-prev-next-btn"
            on:click={() => (currentPage = currentPage + 1)}
            disabled={currentPage >= totalPages}
          >
            →
          </button>
        </div>
      {/if}
    </div>
  {/if}
</div>
