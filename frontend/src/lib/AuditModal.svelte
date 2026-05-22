<script>
  import { createEventDispatcher, onMount } from "svelte";
  import { t } from "./i18n.js";
  import XIcon from "../icons/XIcon.svelte";

  export let showModal = false;
  // 부모가 미리 알려주는 "현재 보기에서 보고 있는 카테고리" — 모달이 그 값으로 프리셋.
  export let preselectKinds = [];

  const dispatch = createEventDispatcher();

  // 분류 후보 — 백엔드 KIND_* 와 동기. 'alive' 는 검수 결과이지 시작 필터로는 의미 없어 제외.
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
    // 모달이 열릴 때마다 부모 preselect 반영. 비어있으면 "전체".
    selectedKinds = new Set(preselectKinds || []);
    allKinds = selectedKinds.size === 0;
  }

  function toggleKind(k) {
    if (selectedKinds.has(k)) selectedKinds.delete(k);
    else selectedKinds.add(k);
    selectedKinds = new Set(selectedKinds); // svelte 반응성
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
      // 백엔드가 별도 estimate 엔드포인트를 안 가진 상태라, 일단은 검수 시작 호출이
      // 응답으로 total 을 알려주는 구조에 의존. 모달 안에서는 추정치를 표시하기
      // 위해 미리보기 호출 대신 사용자에게 "시작" 누르도록 안내.
      // (향후 GET /downloads/audit/preview?... 추가하면 여기서 부르면 됨.)
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
  <div class="modal-backdrop" role="dialog" aria-modal="true" tabindex="0">
    <div
      class="modal"
      on:click|stopPropagation
      on:keydown={() => {}}
      role="dialog"
      tabindex="-1"
    >
      <div class="modal-header">
        <h2>{$t("audit_modal_title")}</h2>
        <button class="button-icon close-button" on:click={cancel} aria-label={$t("audit_modal_cancel")}>
          <XIcon />
        </button>
      </div>

      <div class="modal-body">
        <!-- 분류 -->
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

        <!-- 상태 -->
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
                {s}
              </button>
            {/each}
          </div>
        </section>

        <!-- 기간 -->
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
    padding: 1rem 1rem 1rem 1.5rem;
    border-bottom: 1px solid var(--card-border);
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .modal-header h2 {
    margin: 0;
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--text-primary);
  }
  .close-button {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--text-secondary);
    padding: 0.5rem;
    border-radius: 6px;
  }
  .close-button:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }
  .modal-body {
    padding: 1.25rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }
  .field-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 0.4rem;
  }
  .field-label {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--text-primary);
  }
  .hint {
    font-size: 0.75rem;
    color: var(--text-secondary);
  }
  .link-button {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.78rem;
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
    gap: 0.4rem;
  }
  .chip {
    padding: 0.35rem 0.7rem;
    border-radius: 999px;
    font-size: 0.78rem;
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
    padding: 0.45rem 0.6rem;
    border-radius: 6px;
    border: 1px solid var(--card-border);
    background: var(--input-inner-bg, var(--card-background));
    color: var(--text-primary);
    font-size: 0.85rem;
  }
  .period-sep {
    color: var(--text-secondary);
  }
  .limit-input {
    width: 100%;
    padding: 0.5rem 0.7rem;
    border-radius: 6px;
    border: 1px solid var(--card-border);
    background: var(--input-inner-bg, var(--card-background));
    color: var(--text-primary);
    font-size: 0.9rem;
  }
  .modal-actions {
    padding: 1rem 1.5rem 1.25rem;
    display: flex;
    gap: 0.75rem;
    justify-content: flex-end;
    border-top: 1px solid var(--card-border);
  }
  .button {
    padding: 0.6rem 1.2rem;
    border-radius: 8px;
    font-size: 0.875rem;
    font-weight: 500;
    cursor: pointer;
    border: 1px solid transparent;
  }
  .button-secondary {
    background: var(--card-background);
    color: var(--text-secondary);
    border-color: var(--card-border);
  }
  .button-secondary:hover {
    background: var(--bg-secondary);
    color: var(--text-primary);
  }
  .button-primary {
    background: var(--primary-color);
    color: white;
  }
  .button-primary:hover {
    background: var(--primary-hover);
  }
</style>
