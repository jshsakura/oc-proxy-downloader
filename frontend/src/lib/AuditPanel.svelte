<script>
  import { createEventDispatcher } from "svelte";
  import { t } from "./i18n.js";
  import CheckCircleIcon from "../icons/CheckCircleIcon.svelte";
  import SearchIcon from "../icons/SearchIcon.svelte";

  export let auditRunning = false;
  export let preselectKinds = [];

  const dispatch = createEventDispatcher();
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

  let selectedKinds = new Set(preselectKinds || []);
  let selectedStatuses = new Set(["failed", "stopped"]);
  let since = "";
  let until = "";
  let limit = "";

  $: allKinds = selectedKinds.size === 0;
  $: allPeriod = !since && !until;

  function toggleKind(kind) {
    if (selectedKinds.has(kind)) selectedKinds.delete(kind);
    else selectedKinds.add(kind);
    selectedKinds = new Set(selectedKinds);
  }

  function toggleStatus(status) {
    if (selectedStatuses.has(status)) selectedStatuses.delete(status);
    else selectedStatuses.add(status);
    selectedStatuses = new Set(selectedStatuses);
  }

  function start() {
    const payload = { status_filter: Array.from(selectedStatuses) };
    if (selectedKinds.size) payload.failure_kinds = Array.from(selectedKinds);
    if (since) payload.since = new Date(since).toISOString();
    if (until) payload.until = new Date(until).toISOString();
    const parsedLimit = parseInt(limit, 10);
    if (!isNaN(parsedLimit) && parsedLimit > 0) payload.limit = parsedLimit;
    dispatch("start", payload);
  }
</script>

<div class="audit-panel">
  <section class="field">
    <header class="field-header">
      <span class="field-label">{$t("audit_modal_kinds_label")}</span>
      <button type="button" class="link-button" class:active={allKinds} aria-pressed={allKinds} on:click={() => (selectedKinds = new Set())}>
        <CheckCircleIcon /><span>{$t("audit_modal_kinds_all")}</span>
      </button>
    </header>
    <div class="chips">
      {#each ALL_KINDS as kind}
        <button type="button" class="chip" class:selected={selectedKinds.has(kind)} aria-pressed={selectedKinds.has(kind)} on:click={() => toggleKind(kind)}>
          <CheckCircleIcon /><span>{$t("kind_" + kind)}</span>
        </button>
      {/each}
    </div>
  </section>

  <section class="field">
    <header class="field-header">
      <span class="field-label">{$t("audit_modal_statuses_label")}</span>
      <span class="hint">{$t("audit_modal_statuses_all")}</span>
    </header>
    <div class="chips">
      {#each ALL_STATUSES as status}
        <button type="button" class="chip" class:selected={selectedStatuses.has(status)} aria-pressed={selectedStatuses.has(status)} on:click={() => toggleStatus(status)}>
          <CheckCircleIcon /><span>{$t("download_" + status)}</span>
        </button>
      {/each}
    </div>
  </section>

  <section class="field">
    <header class="field-header">
      <span class="field-label">{$t("audit_modal_period_label")}</span>
      <button type="button" class="link-button" class:active={allPeriod} aria-pressed={allPeriod} on:click={() => { since = ""; until = ""; }}>
        <CheckCircleIcon /><span>{$t("audit_modal_period_all")}</span>
      </button>
    </header>
    <div class="period-inputs">
      <input type="date" bind:value={since} aria-label={$t("audit_modal_period_label")} />
      <span class="period-sep">~</span>
      <input type="date" bind:value={until} aria-label={$t("audit_modal_period_label")} />
    </div>
  </section>

  <section class="field">
    <label class="field-label" for="audit-limit">{$t("audit_modal_limit_label")}</label>
    <input id="audit-limit" class="limit-input" type="number" min="1" placeholder={$t("audit_modal_limit_placeholder")} bind:value={limit} />
  </section>

  <div class="audit-actions">
    <button type="button" class="button button-primary" on:click={start} disabled={auditRunning}>
      <SearchIcon />
      <span>{auditRunning ? $t("audit_already_running") : $t("audit_modal_start")}</span>
    </button>
  </div>
</div>

<style>
  .audit-panel { display: flex; flex-direction: column; gap: 1rem; min-height: 100%; }
  .hint { color: var(--text-secondary); font-size: 0.72rem; }
  .field-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.4rem; }
  .field-label { display: block; color: var(--text-primary); font-size: 0.825rem; font-weight: 600; margin-bottom: 0.4rem; }
  .field-header .field-label { margin-bottom: 0; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.35rem; }
  .chip, .link-button { display: inline-flex; align-items: center; gap: 0.3rem; cursor: pointer; color: var(--text-secondary); }
  .chip { padding: 0.28rem 0.6rem; border: 1px solid var(--card-border); border-radius: 999px; background: transparent; font-size: 0.75rem; }
  .chip.selected { color: var(--text-primary); border-color: var(--primary-color); background: var(--bg-secondary); }
  .link-button { padding: 0.15rem 0.35rem; border: 0; border-radius: 4px; background: transparent; font-size: 0.75rem; }
  .link-button.active { color: var(--primary-color); font-weight: 600; }
  .chip :global(svg), .link-button :global(svg) { width: 12px; height: 12px; opacity: 0.35; }
  .chip.selected :global(svg), .link-button.active :global(svg) { opacity: 1; }
  .period-inputs { display: flex; align-items: center; gap: 0.5rem; }
  .period-inputs input, .limit-input { box-sizing: border-box; padding: 0.45rem 0.6rem; border: 1px solid var(--card-border); border-radius: 6px; background: var(--input-inner-bg, var(--card-background)); color: var(--text-primary); font-size: 0.825rem; }
  .period-inputs input { min-width: 0; flex: 1; }
  .period-sep { color: var(--text-secondary); }
  .limit-input { width: 100%; }
  .audit-actions { display: flex; justify-content: flex-end; margin-top: auto; padding-top: 0.75rem; border-top: 1px solid var(--card-border); }
  .audit-actions .button { display: inline-flex; align-items: center; gap: 0.4rem; }
  .audit-actions :global(svg) { width: 14px; height: 14px; }
  @media (max-width: 520px) { .period-inputs { align-items: stretch; flex-direction: column; } .period-sep { display: none; } }
</style>
