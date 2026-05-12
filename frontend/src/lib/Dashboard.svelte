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
      <div class="dashboard-stat-card stat-total">
        <div class="stat-icon-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
        </div>
        <div class="stat-content">
          <div class="dashboard-stat-value">{(dashboardStats.total || 0).toLocaleString()}</div>
          <div class="dashboard-stat-label">{$t("dashboard_total_downloads")}</div>
        </div>
      </div>
      <div class="dashboard-stat-card stat-success">
        <div class="stat-icon-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        </div>
        <div class="stat-content">
          <div class="dashboard-stat-value">{(dashboardStats.success_rate || 0).toFixed(1)}%</div>
          <div class="dashboard-stat-label">{$t("dashboard_success_rate")}</div>
        </div>
      </div>
      <div class="dashboard-stat-card stat-data">
        <div class="stat-icon-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
        </div>
        <div class="stat-content">
          <div class="dashboard-stat-value">{formatBytes(dashboardStats.total_bytes || 0)}</div>
          <div class="dashboard-stat-label">{$t("dashboard_total_data")}</div>
        </div>
      </div>
      <div class="dashboard-stat-card stat-proxy">
        <div class="stat-icon-wrap">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2" ry="2"/><rect x="2" y="14" width="20" height="8" rx="2" ry="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
        </div>
        <div class="stat-content">
          <div class="dashboard-stat-value">
            <span class="proxy-val">{dashboardStats.proxy_count || 0}</span>
            <span class="proxy-sep">/</span>
            <span class="local-val">{dashboardStats.local_count || 0}</span>
          </div>
          <div class="dashboard-stat-label">{$t("dashboard_proxy_downloads")} / {$t("dashboard_local_downloads")}</div>
        </div>
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
    <div class="dashboard-empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" width="48" height="48" style="opacity:0.3"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg>
      <div>{$t("dashboard_no_data")}</div>
    </div>
  {/if}
</section>

<style>
  .dashboard-section {
    margin-bottom: 1rem;
  }

  .dashboard-stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.6rem;
    margin-bottom: 0.75rem;
  }

  .dashboard-stat-card {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    background: var(--dashboard-card-bg);
    border: 1px solid var(--dashboard-card-border);
    border-radius: 10px;
    padding: 0.65rem 0.75rem;
    box-shadow: var(--shadow-light);
    transition: box-shadow 0.2s ease, transform 0.2s ease;
  }

  .dashboard-stat-card:hover {
    box-shadow: var(--shadow-medium);
    transform: translateY(-1px);
  }

  .stat-icon-wrap {
    width: 36px;
    height: 36px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .stat-icon-wrap :global(svg) {
    width: 18px;
    height: 18px;
  }

  .stat-total .stat-icon-wrap {
    background: rgba(var(--primary-color-rgb, 99, 102, 241), 0.1);
    color: var(--primary-color);
  }
  .stat-success .stat-icon-wrap {
    background: rgba(52, 211, 153, 0.12);
    color: var(--success-color);
  }
  .stat-data .stat-icon-wrap {
    background: rgba(var(--primary-color-rgb, 99, 102, 241), 0.1);
    color: var(--primary-color);
  }
  .stat-proxy .stat-icon-wrap {
    background: rgba(var(--warning-color, #f59e0b), 0.1);
    color: var(--warning-color);
  }

  .stat-content {
    min-width: 0;
  }

  .dashboard-stat-value {
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--dashboard-stat-value);
    line-height: 1.2;
    font-variant-numeric: tabular-nums;
  }

  .dashboard-stat-label {
    font-size: 0.7rem;
    color: var(--dashboard-stat-label);
    margin-top: 0.1rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .proxy-val {
    color: var(--warning-color);
  }
  .proxy-sep {
    color: var(--text-secondary);
    margin: 0 0.1em;
  }
  .local-val {
    color: var(--primary-color);
  }

  .dashboard-charts-row {
    display: grid;
    grid-template-columns: 1.2fr 0.8fr;
    gap: 0.6rem;
    margin-bottom: 0.75rem;
  }

  .dashboard-chart-container {
    background: var(--dashboard-card-bg);
    border: 1px solid var(--dashboard-card-border);
    border-radius: 10px;
    padding: 0.75rem;
    box-shadow: var(--shadow-light);
  }

  .dashboard-chart-title {
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--text-secondary);
    margin-bottom: 0.5rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .dashboard-empty {
    text-align: center;
    padding: 2rem 1rem;
    color: var(--text-secondary);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
  }

  @media (max-width: 768px) {
    .dashboard-charts-row {
      grid-template-columns: 1fr;
    }
    .dashboard-stats-grid {
      grid-template-columns: repeat(2, 1fr);
    }
  }

  @media (max-width: 480px) {
    .dashboard-stats-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
