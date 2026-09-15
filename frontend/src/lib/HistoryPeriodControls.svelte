<script>
  import { createEventDispatcher } from "svelte";
  import { t } from "./i18n.js";
  import SearchIcon from "../icons/SearchIcon.svelte";

  export let period = "custom";
  export let startDate = "";
  export let endDate = "";
  // Allow hiding "Today" in narrow areas (e.g. the settings modal).
  export let hideToday = false;

  const dispatch = createEventDispatcher();

  $: periods = [
    !hideToday && { key: "today", label: "history_period_today" },
    { key: "7d", label: "history_period_7d" },
    { key: "30d", label: "history_period_30d" },
    { key: "all", label: "history_period_all" },
    { key: "custom", label: "history_period_custom" },
  ].filter(Boolean);

  function toIsoDate(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${dd}`;
  }

  function selectPeriod(p) {
    period = p;
    if (p === "custom") {
      // On entering custom mode, auto-fill one month ago ~ today if empty
      if (!startDate || !endDate) {
        const today = new Date();
        const monthAgo = new Date();
        monthAgo.setMonth(monthAgo.getMonth() - 1);
        startDate = toIsoDate(monthAgo);
        endDate = toIsoDate(today);
      }
    }
    dispatch("periodChange", p);
  }

  function applyCustom() {
    dispatch("customApply");
  }
</script>

<div class="period-controls">
  <div
    class="period-segment"
    role="tablist"
    aria-label={$t("history_period_custom")}
  >
    {#each periods as p}
      <button
        type="button"
        class="period-seg-btn"
        class:active={period === p.key}
        role="tab"
        aria-selected={period === p.key}
        on:click={() => selectPeriod(p.key)}
      >
        {$t(p.label)}
      </button>
    {/each}
  </div>

  {#if period === "custom"}
    <div class="period-right-group">
      <div class="period-custom">
        <input
          type="date"
          lang="en-CA"
          class="period-date"
          bind:value={startDate}
          aria-label={$t("history_period_start")}
        />
        <span class="period-date-sep">–</span>
        <input
          type="date"
          lang="en-CA"
          class="period-date"
          bind:value={endDate}
          aria-label={$t("history_period_end")}
        />
      </div>
      <button type="button" class="period-apply" on:click={applyCustom}>
        <SearchIcon />
        <span>{$t("history_period_apply")}</span>
      </button>
    </div>
  {/if}
</div>

<style>
  /* One responsive rule set (task 5). The previous style block carried the
   * desktop rules twice: verbatim again inside the mobile media query, plus
   * !important height locks patching the duplication. The period selector is
   * intentionally more prominent than the compact date/apply controls, and
   * only the reflow changes at the breakpoint. The mobile reflow follows
   * DESIGN.md 4.3: the
   * segment goes full width and the custom dates + apply button take the
   * next full-width row, which requires the row itself to wrap. */

  .period-controls {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    flex-wrap: nowrap;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }

  .period-right-group {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-left: auto;
  }

  .period-segment {
    display: flex;
    align-items: center;
    height: 38px;
    padding: 3px;
    box-sizing: border-box;
    background: var(--bg-secondary, var(--card-background));
    border: 1px solid var(--card-border);
    border-radius: 8px; /* Standardize with other inputs instead of pill */
    box-shadow: var(--shadow-light);
  }

  .period-seg-btn {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-size: 0.82rem;
    font-weight: 600;
    padding: 0 0.7rem;
    border-radius: 6px;
    cursor: pointer;
    transition: background-color 0.2s ease, color 0.2s ease;
  }

  .period-seg-btn:hover {
    color: var(--text-primary);
    background: color-mix(in srgb, var(--primary-color) 8%, transparent);
  }

  .period-seg-btn:focus-visible {
    outline: none;
    box-shadow: 0 0 0 3px
      color-mix(in srgb, var(--primary-color) 35%, transparent);
  }

  .period-seg-btn.active {
    background: var(--primary-color);
    color: #fff;
  }

  .period-custom {
    display: flex;
    align-items: center;
    height: 32px;
    box-sizing: border-box;
    gap: 0.5rem;
    padding: 0 0.75rem;
    border: 1px solid var(--card-border);
    border-radius: 8px; /* Match segment */
    background: var(--card-background);
  }

  .period-date {
    height: 100%;
    border: none;
    background: transparent;
    color: var(--text-primary);
    font-size: 0.82rem;
    padding: 0;
    font-family: inherit;
    outline: none;
    width: 120px;
    text-align: center;
  }

  .period-apply {
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.35rem;
    border: none;
    background: var(--primary-color);
    color: #fff;
    font-size: 0.82rem;
    font-weight: 600;
    padding: 0 0.75rem;
    border-radius: 8px; /* Match segment */
    cursor: pointer;
    transition: background-color 0.2s ease;
  }

  .period-apply :global(svg) {
    width: 13px;
    height: 13px;
    flex: 0 0 auto;
  }

  .period-apply:hover {
    background: var(--primary-hover);
  }

  .period-apply:focus-visible {
    outline: none;
    box-shadow: 0 0 0 3px
      color-mix(in srgb, var(--primary-color) 35%, transparent);
  }

  /* Mobile (DESIGN.md 4.3): full-width segment; when the custom range is
   * active, the date pair and apply button take the next full-width row. */
  @media (max-width: 768px) {
    .period-controls {
      flex-wrap: wrap;
    }

    .period-right-group {
      width: 100%;
      flex-wrap: wrap;
      margin-left: 0;
    }

    .period-segment {
      width: 100%;
      flex: 1 1 100%;
      justify-content: space-between;
      padding: 4px;
    }

    .period-seg-btn {
      flex: 1 1 0;
      padding: 0 0.2rem;
      text-align: center;
    }

    .period-custom {
      width: 100%;
      flex: 1 1 100%;
      justify-content: space-between;
      gap: 0.3rem;
      padding: 0 0.5rem;
    }

    .period-date {
      flex: 1 1 0;
      min-width: 0;
      padding: 0.4rem 0.3rem;
    }

    .period-apply {
      flex: 1 1 100%;
      width: 100%;
    }
  }
</style>
