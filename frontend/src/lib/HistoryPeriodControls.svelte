<script>
  import { t } from "./i18n.js";

  export let period = "30d";
  export let startDate = "";
  export let endDate = "";
  // Allow hiding "Today" in narrow areas (e.g. the settings modal).
  export let hideToday = false;

  $: periods = [
    !hideToday && { key: "today", label: "history_period_today" },
    { key: "7d", label: "history_period_7d" },
    { key: "30d", label: "history_period_30d" },
    { key: "all", label: "history_period_all" },
    { key: "custom", label: "history_period_custom" },
  ].filter(Boolean);

  import { createEventDispatcher } from "svelte";
  const dispatch = createEventDispatcher();

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
  <div class="period-segment" role="tablist" aria-label="period">
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
    <div class="period-custom">
      <input
        type="date"
        class="period-date"
        bind:value={startDate}
        aria-label={$t("history_period_start")}
      />
      <span class="period-date-sep">–</span>
      <input
        type="date"
        class="period-date"
        bind:value={endDate}
        aria-label={$t("history_period_end")}
      />
    </div>
    <button type="button" class="period-apply" on:click={applyCustom}>
      {$t("history_period_apply")}
    </button>
  {/if}
</div>

<style>
  /* Shared control height so every control (segment, date inputs, apply)
   * lines up on a single baseline. */
  :root {
    --period-control-height: 34px;
  }

  .period-controls {
    display: flex;
    align-items: center;
    /* Left-aligned on desktop; centered only on mobile (see media query). */
    justify-content: flex-start;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }

  .period-segment {
    display: inline-flex;
    align-items: stretch;
    height: var(--period-control-height);
    padding: 3px;
    box-sizing: border-box;
    background: var(--bg-secondary, var(--card-background));
    border: 1px solid var(--card-border);
    border-radius: 999px;
    box-shadow: var(--shadow-light);
  }

  .period-seg-btn {
    appearance: none;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-size: 0.78rem;
    font-weight: 600;
    line-height: 1;
    padding: 0 0.85rem;
    border-radius: 999px;
    cursor: pointer;
    transition: background-color 0.18s ease, color 0.18s ease;
    letter-spacing: 0.01em;
  }

  .period-seg-btn:hover:not(.active) {
    color: var(--text-primary);
    background: rgba(var(--primary-color-rgb, 99, 102, 241), 0.08);
  }

  .period-seg-btn.active {
    background: var(--primary-color);
    color: #fff;
    box-shadow: 0 1px 3px rgba(var(--primary-color-rgb, 99, 102, 241), 0.35);
  }

  .period-custom {
    display: inline-flex;
    align-items: center;
    height: var(--period-control-height);
    box-sizing: border-box;
    gap: 0.4rem;
    padding: 0 0.5rem;
    border: 1px solid var(--card-border);
    border-radius: 999px;
    background: var(--card-background);
  }

  .period-date {
    appearance: none;
    border: none;
    background: transparent;
    color: var(--text-primary);
    font-size: 0.78rem;
    line-height: 1;
    padding: 0.25rem 0.35rem;
    border-radius: 6px;
    color-scheme: light dark;
    font-family: inherit;
  }

  .period-date:focus {
    outline: 2px solid rgba(var(--primary-color-rgb, 99, 102, 241), 0.35);
    outline-offset: -2px;
  }

  .period-date-sep {
    color: var(--text-secondary);
    font-size: 0.85rem;
    user-select: none;
  }

  .period-apply {
    appearance: none;
    border: 1px solid var(--card-border);
    height: var(--period-control-height);
    box-sizing: border-box;
    background: var(--primary-color);
    color: #fff;
    font-size: 0.78rem;
    font-weight: 600;
    line-height: 1;
    padding: 0 0.9rem;
    border-radius: 999px;
    cursor: pointer;
    transition: background-color 0.18s ease, box-shadow 0.18s ease;
  }

  .period-apply:hover {
    background: var(--primary-hover, var(--primary-color));
    box-shadow: 0 2px 8px rgba(var(--primary-color-rgb, 99, 102, 241), 0.35);
  }

  /* Mobile — making the component itself full-width is the most reliable. Scoped
   * styles win over the parent wrapper's :global. To prevent left alignment: 1) controls
   * is a row at 100%, 2) the segment is full-width, 3) buttons stretch evenly at 1fr.
   * The custom area is also full-width on the next line. */
  /* Mobile — center the control group and let it span full width. */
  @media (max-width: 768px) {
    .period-controls {
      width: 100%;
      justify-content: center;
      gap: 0.4rem;
      margin-bottom: 0;
    }
    .period-segment {
      display: flex;
      width: 100%;
      flex: 1 1 100%;
      justify-content: space-between;
      padding: 4px;
    }
    .period-seg-btn {
      flex: 1 1 0;
      padding: 0 0.2rem;
      font-size: 0.78rem;
      text-align: center;
    }
    .period-custom {
      display: flex;
      width: 100%;
      flex: 1 1 100%;
      justify-content: space-between;
      gap: 0.3rem;
      padding: 0 0.5rem;
    }
    .period-date {
      flex: 1 1 0;
      min-width: 0;
      font-size: 0.82rem;
      padding: 0.4rem 0.3rem;
    }
    .period-apply {
      flex: 1 1 100%;
      width: 100%;
    }
  }
</style>
