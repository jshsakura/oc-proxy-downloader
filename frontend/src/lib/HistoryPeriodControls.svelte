<script>
  import { t } from "./i18n.js";

  export let period = "30d";
  export let startDate = "";
  export let endDate = "";
  // 좁은 영역(설정 모달 등) 에서는 "오늘" 을 숨길 수 있도록.
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
      // 사용자 지정 진입 시 비어 있으면 한 달 전 ~ 오늘 자동 채움
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
      <button type="button" class="period-apply" on:click={applyCustom}>
        {$t("history_period_apply")}
      </button>
    </div>
  {/if}
</div>

<style>
  .period-controls {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
  }

  .period-segment {
    display: inline-flex;
    align-items: stretch;
    padding: 3px;
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
    padding: 0.45rem 0.85rem;
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
    gap: 0.4rem;
    padding: 0.25rem 0.5rem;
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
    border: none;
    background: var(--primary-color);
    color: #fff;
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.4rem 0.8rem;
    border-radius: 999px;
    cursor: pointer;
    transition: background-color 0.18s ease, box-shadow 0.18s ease;
  }

  .period-apply:hover {
    background: var(--primary-hover, var(--primary-color));
    box-shadow: 0 2px 8px rgba(var(--primary-color-rgb, 99, 102, 241), 0.35);
  }

  /* 모바일 — 컴포넌트 자체 풀폭 풀어주는 게 가장 확실. 부모 wrapper 의 :global 보다
   * scoped 가 강하다. 좌측 정렬 안되게 1) controls 가 row 100%, 2) segment 가
   * 풀폭, 3) 버튼이 균등 1fr 로 펴짐. 사용자 지정 영역도 다음 줄 풀폭. */
  @media (max-width: 720px) {
    .period-controls {
      width: 100%;
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
      padding: 0.6rem 0.2rem;
      font-size: 0.78rem;
      text-align: center;
    }
    .period-custom {
      display: flex;
      width: 100%;
      flex: 1 1 100%;
      justify-content: space-between;
      gap: 0.3rem;
      padding: 0.3rem 0.5rem;
    }
    .period-date {
      flex: 1 1 0;
      min-width: 0;
      font-size: 0.82rem;
      padding: 0.4rem 0.3rem;
    }
    .period-apply {
      padding: 0.45rem 0.9rem;
      font-size: 0.78rem;
    }
  }
</style>
