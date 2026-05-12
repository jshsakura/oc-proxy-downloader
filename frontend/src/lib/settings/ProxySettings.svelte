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

<style>
  .form-group {
    margin-bottom: 1.5rem;
  }

  .proxy-management-title {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 600;
    font-size: 0.875rem;
    color: var(--text-primary);
    text-transform: uppercase;
    letter-spacing: 0.025em;
  }

  .input {
    width: 100%;
    padding: 0.875rem 1rem;
    border: 2px solid var(--card-border, #e5e7eb);
    border-radius: 12px;
    background-color: var(--input-bg, #ffffff);
    color: var(--text-primary);
    font-size: 0.875rem;
    font-weight: 500;
    transition: all 0.2s ease;
  }

  .input:focus {
    outline: none;
    border-color: var(--primary-color);
  }

  .proxy-input-group {
    display: grid;
    grid-template-columns: 2fr 1fr auto;
    gap: 0.5rem;
    align-items: end;
  }

  .proxy-add-button {
    white-space: nowrap;
    padding: 0.75rem 1rem;
    height: auto;
    min-height: 2.5rem;
  }

  .proxy-empty-state {
    text-align: center;
    padding: 2rem;
    background: var(--bg-secondary, #f8f9fa);
    border-radius: 8px;
    color: var(--text-secondary);
  }

  .proxy-table-container {
    max-height: 250px;
    min-height: 60px;
    overflow-y: auto;
    overflow-x: hidden;
    border: 1px solid var(--card-border);
    border-radius: 8px;
    width: 100%;
  }

  .proxy-table-wrapper {
    overflow-x: auto;
    width: 100%;
  }

  .proxy-table {
    width: 100%;
    min-width: 700px;
    border-collapse: collapse;
    display: table !important;
  }

  .proxy-table th, .proxy-table td {
    padding: 0.4rem 0.5rem;
    text-align: left;
    border-bottom: 1px solid var(--card-border);
    font-size: 0.85rem;
    vertical-align: middle;
    white-space: nowrap;
  }

  .proxy-table th {
    background: var(--bg-secondary);
    font-weight: 600;
    position: sticky;
    top: 0;
    text-align: center;
    border-bottom: 2px solid var(--card-border) !important;
  }

  .proxy-table th:first-child { text-align: left; }
  .proxy-table td:first-child { min-width: 200px; max-width: 300px; }

  .text-center { text-align: center !important; }

  .proxy-address-content {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .proxy-url {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .copy-proxy-button {
    background: var(--card-background);
    border: 1px solid var(--card-border);
    border-radius: 6px;
    padding: 6px;
    cursor: pointer;
    color: var(--text-secondary);
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .copy-proxy-button:hover {
    background-color: var(--primary-color);
    color: white;
  }

  .proxy-description {
    display: block;
    opacity: 0.7;
    font-style: italic;
    margin-top: 0.25rem;
  }

  .proxy-action-buttons {
    display: flex;
    gap: 0.25rem;
    justify-content: center;
  }

  .proxy-action-btn {
    background: none;
    border: none;
    cursor: pointer;
    padding: 0.25rem;
    border-radius: 4px;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .toggle-btn.active { color: #22c55e; }
  .toggle-btn.inactive { color: #9ca3af; }
  .delete-btn { color: #ef4444; }
  .delete-btn:hover { background-color: #ef4444; color: white; }

  .proxy-type-badge, .proxy-status-badge {
    display: inline-block;
    padding: 0.2rem 0.8rem;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 500;
  }

  .proxy-type-badge.list { background: #e1f5fe; color: #0277bd; }
  .proxy-type-badge.single { background: #f3e5f5; color: #7b1fa2; }
  .proxy-status-badge.active { background: #e8f5e8; color: #2e7d32; }
  .proxy-status-badge.inactive { background: #fafafa; color: #616161; }

  .proxy-table-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 1.5rem;
    background-color: var(--card-background);
    border: 1px solid var(--card-border);
    border-top: none;
    border-radius: 0 0 8px 8px;
    gap: 1rem;
  }

  .proxy-footer-info { display: flex; flex-direction: column; }
  .proxy-pagination-buttons { display: flex; align-items: center; gap: 0.5rem; }

  .proxy-page-number-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 36px;
    height: 36px;
    border: 1px solid var(--card-border);
    background: var(--card-background);
    color: var(--text-primary);
    border-radius: 6px;
    cursor: pointer;
  }

  .proxy-page-number-btn.active { background: var(--primary-color); color: white; }
  .proxy-page-number-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  @media (max-width: 768px) {
    .proxy-input-group { grid-template-columns: 1fr; }
    .proxy-table-footer { flex-direction: column; }
    .proxy-table-container { font-size: 0.75rem; }
  }
</style>
