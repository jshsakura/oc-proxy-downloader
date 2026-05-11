<script>
  import { t } from "./i18n.js";
  import HistoryPeriodControls from "./HistoryPeriodControls.svelte";
  import TrendChart from "./TrendChart.svelte";
  import StatusDonutChart from "./StatusDonutChart.svelte";

  export let dashboardStats = null;
  export let dashboardPeriod = "30d";
  export let dashboardStartDate = "";
  export let dashboardEndDate = "";
  export let dashboardHistory = [];
  export let dashboardTotalPages = 0;
  export let dashboardCurrentPage = 1;

  import { createEventDispatcher } from "svelte";
  const dispatch = createEventDispatcher();

  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    const val = bytes / Math.pow(1024, i);
    return val.toFixed(i === 0 ? 0 : 1) + " " + units[i];
  }

  $: dailyTrend = (dashboardStats && dashboardStats.daily_trend) || [];
  $: byStatus = (dashboardStats && dashboardStats.by_status) || {};
  $: hasData = dashboardStats && dashboardStats.total > 0;

  function onPeriodChange(e) {
    dispatch("periodChange", e.detail);
  }
  function onCustomApply() {
    dispatch("customApply");
  }
  function onPageChange(p) {
    dispatch("pageChange", p);
  }
</script>

<section class="dashboard-section">
  <HistoryPeriodControls
    bind:period={dashboardPeriod}
    bind:startDate={dashboardStartDate}
    bind:endDate={dashboardEndDate}
    on:periodChange={onPeriodChange}
    on:customApply={onCustomApply}
  />

  {#if hasData}
    <div class="dashboard-stats-grid">
      <div class="dashboard-stat-card">
        <div class="dashboard-stat-value">{(dashboardStats.total || 0).toLocaleString()}</div>
        <div class="dashboard-stat-label">{$t("dashboard_total_downloads")}</div>
      </div>
      <div class="dashboard-stat-card">
        <div class="dashboard-stat-value">{(dashboardStats.success_rate || 0).toFixed(1)}%</div>
        <div class="dashboard-stat-label">{$t("dashboard_success_rate")}</div>
      </div>
      <div class="dashboard-stat-card">
        <div class="dashboard-stat-value">{formatBytes(dashboardStats.total_bytes || 0)}</div>
        <div class="dashboard-stat-label">{$t("dashboard_total_data")}</div>
      </div>
      <div class="dashboard-stat-card">
        <div class="dashboard-stat-value">
          <span style="color:var(--warning-color);">{dashboardStats.proxy_count || 0}</span>
          /
          <span style="color:var(--primary-color);">{dashboardStats.local_count || 0}</span>
        </div>
        <div class="dashboard-stat-label">{$t("dashboard_proxy_downloads")} / {$t("dashboard_local_downloads")}</div>
      </div>
    </div>

    <div class="dashboard-charts-row">
      <div class="dashboard-chart-container">
        <div class="dashboard-chart-title">{$t("dashboard_trend_title")}</div>
        <TrendChart data={dailyTrend} />
      </div>
      <div class="dashboard-chart-container">
        <div class="dashboard-chart-title">{$t("dashboard_status_distribution")}</div>
        <StatusDonutChart {byStatus} />
      </div>
    </div>
  {:else}
    <div style="text-align:center;padding:2rem;color:var(--text-secondary);">
      {$t("dashboard_no_data")}
    </div>
  {/if}
</section>
