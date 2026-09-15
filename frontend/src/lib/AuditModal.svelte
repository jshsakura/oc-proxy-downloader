<script>
  import { createEventDispatcher } from "svelte";
  import { t } from "./i18n.js";
  import { modalFocus } from "./modal.js";
  import XIcon from "../icons/XIcon.svelte";

  export let showModal = false;
  // The "category currently being viewed" that the parent provides up front — the modal presets to it.
  export let preselectKinds = [];

  const dispatch = createEventDispatcher();

  // Classification candidates — in sync with the backend KIND_*. 'alive' is an audit result, not meaningful as a start filter, so it is excluded.
  const ALL_KINDS = [
    "dead",
    "auth_required",
    "rate_limited",
    "cloudflare",
    "proxy_blocked",
    "blocked",
    "transient",
    "unknown",
    "unknown_terminal",
  ];
  const ALL_STATUSES = ["failed", "stopped", "pending", "done"];

  let selectedKinds = new Set();
  let selectedStatuses = new Set(["failed", "stopped"]);
  let since = "";
  let until = "";
  let limit = "";
  let allKinds = true;
  let allPeriod = true;
  let estimateCount = null;
  let estimating = false;

  $: if (showModal) {
    // Apply the parent preselect each time the modal opens. If empty, "All".
    selectedKinds = new Set(preselectKinds || []);
    allKinds = selectedKinds.size === 0;
  }

  function toggleKind(k) {
    if (selectedKinds.has(k)) selectedKinds.delete(k);
    else selectedKinds.add(k);
    selectedKinds = new Set(selectedKinds); // svelte reactivity
    allKinds = selectedKinds.size === 0;
  }

  function toggleStatus(s) {
    if (selectedStatuses.has(s)) selectedStatuses.delete(s);
    else selectedStatuses.add(s);
    selectedStatuses = new Set(selectedStatuses);
  }

  function clearAllKinds() {
    selectedKinds = new Set();
    allKinds = true;
  }

  function clearPeriod() {
    since = "";
    until = "";
    allPeriod = true;
  }

  function buildPayload() {
    const payload = {
      status_filter: Array.from(selectedStatuses),
    };
    if (selectedKinds.size > 0) {
      payload.failure_kinds = Array.from(selectedKinds);
    }
    if (since) {
      payload.since = new Date(since).toISOString();
      allPeriod = false;
    }
    if (until) {
      payload.until = new Date(until).toISOString();
      allPeriod = false;
    }
    const limitNum = parseInt(limit, 10);
    if (!isNaN(limitNum) && limitNum > 0) {
      payload.limit = limitNum;
    }
    return payload;
  }

  async function estimate() {
    estimating = true;
    try {
      // The backend has no separate estimate endpoint yet, so for now we rely on
      // the audit-start call reporting total in its response. To show an estimate
      // inside the modal, instead of a preview call we guide the user to press "Start".
      // (If a GET /downloads/audit/preview?... is added later, call it here.)
      estimateCount = null;
    } finally {
      estimating = false;
    }
  }

  function start() {
    dispatch("start", buildPayload());
    showModal = false;
  }

  function cancel() {
    dispatch("cancel");
    showModal = false;
  }
</script>

{#if showModal}
  <div class="modal-backdrop">
    <div
      class="modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="audit-modal-title"
      tabindex="-1"
      use:modalFocus={{ onEscape: cancel }}
    >
      <div class="modal-header">
        <h2 id="audit-modal-title">{$t("audit_modal_title")}</h2>
        <button class="button-icon close-button" on:click={cancel} aria-label={$t("audit_modal_cancel")}>
          <XIcon />
        </button>
      </div>

      <div class="modal-body">
        <!-- Classification -->
        <section class="field">
          <header class="field-header">
            <span class="field-label">{$t("audit_modal_kinds_label")}</span>
            <button class="link-button" on:click={clearAllKinds} class:active={allKinds}>
              {$t("audit_modal_kinds_all")}
            </button>
          </header>
          <div class="chips">
            {#each ALL_KINDS as k}
              <button
                type="button"
                class="chip kind-chip kind-chip-{k}"
                class:selected={selectedKinds.has(k)}
                on:click={() => toggleKind(k)}
              >
                {$t("kind_" + k)}
              </button>
            {/each}
          </div>
        </section>

        <!-- Status -->
        <section class="field">
          <header class="field-header">
            <span class="field-label">{$t("audit_modal_statuses_label")}</span>
            <span class="hint">{$t("audit_modal_statuses_all")}</span>
          </header>
          <div class="chips">
            {#each ALL_STATUSES as s}
              <button
                type="button"
                class="chip status-chip"
                class:selected={selectedStatuses.has(s)}
                on:click={() => toggleStatus(s)}
              >
                {$t("download_" + s)}
              </button>
            {/each}
          </div>
        </section>

        <!-- Period -->
        <section class="field">
          <header class="field-header">
            <span class="field-label">{$t("audit_modal_period_label")}</span>
            <button class="link-button" on:click={clearPeriod} class:active={allPeriod && !since && !until}>
              {$t("audit_modal_period_all")}
            </button>
          </header>
          <div class="period-inputs">
            <input
              type="date"
              bind:value={since}
              on:change={() => (allPeriod = false)}
            />
            <span class="period-sep">~</span>
            <input
              type="date"
              bind:value={until}
              on:change={() => (allPeriod = false)}
            />
          </div>
        </section>

        <!-- limit -->
        <section class="field">
          <header class="field-header">
            <span class="field-label">{$t("audit_modal_limit_label")}</span>
          </header>
          <input
            class="limit-input"
            type="number"
            min="1"
            placeholder={$t("audit_modal_limit_placeholder")}
            bind:value={limit}
          />
        </section>
      </div>

      <div class="modal-actions">
        <button class="button button-secondary" on:click={cancel}>
          {$t("audit_modal_cancel")}
        </button>
        <button class="button button-primary" on:click={start}>
          {$t("audit_modal_start")}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .modal-backdrop {
    position: fixed;
    top: 0; left: 0;
    width: 100%; height: 100%;
    background: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 20000;
  }
  .modal {
    background: var(--card-background);
    border-radius: 12px;
    box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25);
    width: 90vw;
    max-width: 560px;
    max-height: 92vh;
    overflow-y: auto;
  }
  .modal-header {
    padding: 0.75rem 1.25rem;
    border-bottom: 1px solid var(--card-border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .modal-header h2 {
    margin: 0;
    font-size: 1.05rem;
    font-weight: 600;
    color: var(--text-primary);
  }
  .close-button {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--text-secondary);
    padding: 4px;
    width: 28px;
    height: 28px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 6px;
    transition: all 0.2s ease;
  }
  .close-button:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }
  .close-button :global(svg) {
    width: 14px;
    height: 14px;
  }
  .modal-body {
    padding: 1rem 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }
  .field-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 0.4rem;
  }
  .field-label {
    font-size: 0.825rem;
    font-weight: 600;
    color: var(--text-primary);
  }
  .hint {
    font-size: 0.72rem;
    color: var(--text-secondary);
  }
  .link-button {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.75rem;
    color: var(--text-secondary);
    padding: 0.15rem 0.35rem;
    border-radius: 4px;
  }
  .link-button.active {
    color: var(--primary-color);
    font-weight: 600;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
  }
  .chip {
    padding: 0.25rem 0.6rem;
    border-radius: 999px;
    font-size: 0.75rem;
    border: 1px solid var(--card-border);
    background: transparent;
    color: var(--text-secondary);
    cursor: pointer;
    transition: filter 0.15s;
  }
  .chip.selected {
    filter: brightness(1.15);
    border-color: var(--primary-color);
    color: var(--text-primary);
    background: var(--bg-secondary);
  }
  .period-inputs {
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }
  .period-inputs input {
    padding: 0.4rem 0.55rem;
    border-radius: 6px;
    border: 1px solid var(--card-border);
    background: var(--input-inner-bg, var(--card-background));
    color: var(--text-primary);
    font-size: 0.825rem;
  }
  .period-sep {
    color: var(--text-secondary);
  }
  .limit-input {
    width: 100%;
    padding: 0.4rem 0.6rem;
    border-radius: 6px;
    border: 1px solid var(--card-border);
    background: var(--input-inner-bg, var(--card-background));
    color: var(--text-primary);
    font-size: 0.85rem;
  }
  .modal-actions {
    padding: 0.65rem 1.25rem 0.85rem;
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
    border-top: 1px solid var(--card-border);
  }
</style>
