<script>
  import { t } from "./i18n.js";

  export let period = "30d";
  export let startDate = "";
  export let endDate = "";

  const periods = [
    { key: "today", label: "history_period_today" },
    { key: "7d", label: "history_period_7d" },
    { key: "30d", label: "history_period_30d" },
    { key: "all", label: "history_period_all" },
    { key: "custom", label: "history_period_custom" },
  ];

  import { createEventDispatcher } from "svelte";
  const dispatch = createEventDispatcher();

  function selectPeriod(p) {
    period = p;
    dispatch("periodChange", p);
  }

  function applyCustom() {
    dispatch("customApply");
  }
</script>

<div class="dashboard-period-controls">
  {#each periods as p}
    <button
      class="dashboard-period-btn"
      class:active={period === p.key}
      on:click={() => selectPeriod(p.key)}
    >
      {$t(p.label)}
    </button>
  {/each}

  {#if period === "custom"}
    <div class="dashboard-period-custom">
      <input
        type="date"
        bind:value={startDate}
        aria-label={$t("history_period_start")}
      />
      <input
        type="date"
        bind:value={endDate}
        aria-label={$t("history_period_end")}
      />
      <button on:click={applyCustom}>
        {$t("history_period_apply")}
      </button>
    </div>
  {/if}
</div>
