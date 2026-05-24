<script>
  import { t } from "./i18n.js";
  import Skeleton from "./Skeleton.svelte";

  export let systemStats = null;
  // The period (query condition) moved to the grid header. The Dashboard is
  // responsible only for live status + system monitoring.

  // Sliding buffer for the system-monitoring sparklines.
  // As systemStats refreshes every 5 seconds, keep only the last N points to show as a live chart.
  const SPARK_POINTS = 40;
  let cpuSeries = [];
  let ramSeries = [];
  let netDownSeries = [];
  let netUpSeries = [];

  // bytes_sent/recv are cumulative, so derive throughput from the difference vs the previous value.
  let prevNet = null;
  let prevTs = 0;

  function pushSeries(series, value) {
    // For the first sample, prefill SPARK_POINTS with the same value — so that even
    // a flat line is drawn immediately on page entry and the card does not look empty.
    if (series.length === 0) {
      return Array(SPARK_POINTS).fill(value);
    }
    const next = series.slice(-SPARK_POINTS + 1);
    next.push(value);
    return next;
  }

  $: if (systemStats && systemStats.cpu) {
    cpuSeries = pushSeries(cpuSeries, systemStats.cpu.percent || 0);
    ramSeries = pushSeries(ramSeries, systemStats.memory?.percent || 0);

    const now = Date.now();
    if (prevNet && prevTs && now > prevTs) {
      const dt = (now - prevTs) / 1000;
      const dDown = Math.max(0, (systemStats.network.bytes_recv - prevNet.bytes_recv) / dt);
      const dUp = Math.max(0, (systemStats.network.bytes_sent - prevNet.bytes_sent) / dt);
      netDownSeries = pushSeries(netDownSeries, dDown);
      netUpSeries = pushSeries(netUpSeries, dUp);
    } else if (netDownSeries.length === 0) {
      // First entry — throughput can only be computed once the next sample arrives. Fill with a flat 0 line for now.
      netDownSeries = Array(SPARK_POINTS).fill(0);
      netUpSeries = Array(SPARK_POINTS).fill(0);
    }
    prevNet = { ...systemStats.network };
    prevTs = now;
  }

  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    const val = bytes / Math.pow(1024, i);
    return val.toFixed(i === 0 ? 0 : 1) + " " + units[i];
  }

  function formatRate(bytesPerSec) {
    if (!bytesPerSec || bytesPerSec === 0) return "0 B/s";
    const units = ["B/s", "KB/s", "MB/s", "GB/s"];
    const i = Math.floor(Math.log(bytesPerSec) / Math.log(1024));
    const val = bytesPerSec / Math.pow(1024, i);
    return val.toFixed(i === 0 ? 0 : 1) + " " + units[i];
  }

  // For mobile — expose the number and unit as two separate spans so the unit can be hidden via CSS.
  function rateParts(bytesPerSec) {
    if (!bytesPerSec || bytesPerSec === 0) return { num: "0", unit: "B/s" };
    const units = ["B/s", "KB/s", "MB/s", "GB/s"];
    const i = Math.floor(Math.log(bytesPerSec) / Math.log(1024));
    const val = bytesPerSec / Math.pow(1024, i);
    return { num: val.toFixed(i === 0 ? 0 : 1), unit: units[i] };
  }

  function formatUptime(seconds) {
    if (!seconds) return "0s";
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return d + "d " + h + "h";
    if (h > 0) return h + "h " + m + "m";
    return m + "m";
  }

  // 0..1 progress + radius r → returns the two SVG donut stroke-dasharray values.
  // Centralized so all gauges use the same formula.
  function arcDash(pct, r) {
    const C = 2 * Math.PI * r;
    const filled = Math.max(0, Math.min(1, pct)) * C;
    return `${filled} ${C - filled}`;
  }

  // Path for the line chart (sparkline). Scaled 0..W to fit the container width.
  function sparkPath(values, W, H, padTop = 2, padBot = 2) {
    if (!values || values.length < 2) return "";
    const max = Math.max(1, ...values);
    const min = 0;
    const span = max - min || 1;
    const stepX = W / (values.length - 1);
    const usableH = H - padTop - padBot;
    return values
      .map((v, i) => {
        const x = i * stepX;
        const y = padTop + usableH - ((v - min) / span) * usableH;
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }

  function sparkArea(values, W, H, padTop = 2, padBot = 2) {
    const line = sparkPath(values, W, H, padTop, padBot);
    if (!line) return "";
    return `${line} L${W},${H} L0,${H} Z`;
  }

  $: hasSystem = systemStats !== null;

  // Common gauge parameters
  const GAUGE_R = 36;
  const GAUGE_CX = 50;
  const GAUGE_CY = 50;

  function gaugeColor(pct) {
    // <= 65% — primary (normal), <= 88% — warning, above that — danger.
    // If the threshold is too low, even an idle system shows a warning color, making colors noisy.
    if (pct >= 88) return "var(--danger-color, #ef4444)";
    if (pct >= 65) return "var(--warning-color, #f59e0b)";
    return "var(--primary-color)";
  }

  function formatCpuPercent(pct) {
    if (pct < 10) return pct.toFixed(1);
    return pct.toFixed(0);
  }

  $: cpuPct = (systemStats && systemStats.cpu && systemStats.cpu.percent) || 0;
  $: appCpuPct = (systemStats && systemStats.process && systemStats.process.cpu_percent) || 0;
  $: ramPct = (systemStats && systemStats.memory && systemStats.memory.percent) || 0;
  $: diskPct = (systemStats && systemStats.disk && systemStats.disk.percent) || 0;

  $: currentDown = netDownSeries.length ? netDownSeries[netDownSeries.length - 1] : 0;
  $: currentUp = netUpSeries.length ? netUpSeries[netUpSeries.length - 1] : 0;
</script>

<section class="dashboard-section">
  <!-- The query condition (period) moved to the grid (download list) side. The Dashboard
       shows only live status and system monitoring. -->
  <!-- The parent (App.svelte) injects ProxyGauge/LocalGauge as a combined card. -->
  <slot name="gauges" />

  {#if hasSystem}
    <div class="monitor-grid">
      <!-- CPU -->
      <div class="monitor-card">
        <div class="monitor-head">
          <div class="monitor-title">CPU</div>
          <div class="monitor-meta">
            {systemStats.cpu.count_physical}C / {systemStats.cpu.count_logical}T
          </div>
        </div>
        <div class="monitor-body">
          <svg class="gauge" viewBox="0 0 100 100" aria-hidden="true">
            <circle cx={GAUGE_CX} cy={GAUGE_CY} r={GAUGE_R} fill="none"
              stroke="var(--chart-grid)" stroke-width="8" />
            <circle cx={GAUGE_CX} cy={GAUGE_CY} r={GAUGE_R} fill="none"
              stroke={gaugeColor(cpuPct)} stroke-width="8" stroke-linecap="round"
              stroke-dasharray={arcDash(cpuPct / 100, GAUGE_R)}
              transform="rotate(-90 {GAUGE_CX} {GAUGE_CY})"
              style="transition: stroke-dasharray 0.6s ease, stroke 0.4s ease;" />
            <text x={GAUGE_CX} y={GAUGE_CY - 2} text-anchor="middle"
              dominant-baseline="middle"
              style="font-size:18px;font-weight:700;fill:var(--dashboard-stat-value);">
              {formatCpuPercent(cpuPct)}<tspan style="font-size:10px;fill:var(--chart-muted);">%</tspan>
            </text>
            <text x={GAUGE_CX} y={GAUGE_CY + 14} text-anchor="middle"
              dominant-baseline="middle"
              style="font-size:8px;fill:var(--chart-muted);letter-spacing:0.08em;">
              APP {formatCpuPercent(appCpuPct)}%
            </text>
          </svg>
          <div class="spark">
            <svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
              <defs>
                <linearGradient id="cpu-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color={gaugeColor(cpuPct)} stop-opacity="0.4" />
                  <stop offset="100%" stop-color={gaugeColor(cpuPct)} stop-opacity="0" />
                </linearGradient>
              </defs>
              <path d={sparkArea(cpuSeries, 100, 30)} fill="url(#cpu-grad)" />
              <path d={sparkPath(cpuSeries, 100, 30)} fill="none"
                stroke={gaugeColor(cpuPct)} stroke-width="1.4"
                stroke-linejoin="round" vector-effect="non-scaling-stroke" />
            </svg>
          </div>
        </div>
      </div>

      <!-- RAM -->
      <div class="monitor-card">
        <div class="monitor-head">
          <div class="monitor-title">RAM</div>
          <div class="monitor-meta">
            {formatBytes(systemStats.memory.used)} / {formatBytes(systemStats.memory.total)}
          </div>
        </div>
        <div class="monitor-body">
          <svg class="gauge" viewBox="0 0 100 100" aria-hidden="true">
            <circle cx={GAUGE_CX} cy={GAUGE_CY} r={GAUGE_R} fill="none"
              stroke="var(--chart-grid)" stroke-width="8" />
            <circle cx={GAUGE_CX} cy={GAUGE_CY} r={GAUGE_R} fill="none"
              stroke={gaugeColor(ramPct)} stroke-width="8" stroke-linecap="round"
              stroke-dasharray={arcDash(ramPct / 100, GAUGE_R)}
              transform="rotate(-90 {GAUGE_CX} {GAUGE_CY})"
              style="transition: stroke-dasharray 0.6s ease, stroke 0.4s ease;" />
            <text x={GAUGE_CX} y={GAUGE_CY - 2} text-anchor="middle"
              dominant-baseline="middle"
              style="font-size:18px;font-weight:700;fill:var(--dashboard-stat-value);">
              {ramPct.toFixed(0)}<tspan style="font-size:10px;fill:var(--chart-muted);">%</tspan>
            </text>
            <text x={GAUGE_CX} y={GAUGE_CY + 14} text-anchor="middle"
              dominant-baseline="middle"
              style="font-size:8px;fill:var(--chart-muted);letter-spacing:0.08em;">
              {formatBytes(systemStats.memory.available)} FREE
            </text>
          </svg>
          <div class="spark">
            <svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
              <defs>
                <linearGradient id="ram-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color={gaugeColor(ramPct)} stop-opacity="0.4" />
                  <stop offset="100%" stop-color={gaugeColor(ramPct)} stop-opacity="0" />
                </linearGradient>
              </defs>
              <path d={sparkArea(ramSeries, 100, 30)} fill="url(#ram-grad)" />
              <path d={sparkPath(ramSeries, 100, 30)} fill="none"
                stroke={gaugeColor(ramPct)} stroke-width="1.4"
                stroke-linejoin="round" vector-effect="non-scaling-stroke" />
            </svg>
          </div>
        </div>
      </div>

      <!-- DISK -->
      <div class="monitor-card">
        <div class="monitor-head">
          <div class="monitor-title">{$t("sys_disk")}</div>
          <div class="monitor-meta">
            {formatBytes(systemStats.disk.free)} free
          </div>
        </div>
        <div class="monitor-body">
          <svg class="gauge" viewBox="0 0 100 100" aria-hidden="true">
            <circle cx={GAUGE_CX} cy={GAUGE_CY} r={GAUGE_R} fill="none"
              stroke="var(--chart-grid)" stroke-width="8" />
            <circle cx={GAUGE_CX} cy={GAUGE_CY} r={GAUGE_R} fill="none"
              stroke={gaugeColor(diskPct)} stroke-width="8" stroke-linecap="round"
              stroke-dasharray={arcDash(diskPct / 100, GAUGE_R)}
              transform="rotate(-90 {GAUGE_CX} {GAUGE_CY})"
              style="transition: stroke-dasharray 0.6s ease, stroke 0.4s ease;" />
            <text x={GAUGE_CX} y={GAUGE_CY - 2} text-anchor="middle"
              dominant-baseline="middle"
              style="font-size:18px;font-weight:700;fill:var(--dashboard-stat-value);">
              {diskPct.toFixed(0)}<tspan style="font-size:10px;fill:var(--chart-muted);">%</tspan>
            </text>
            <text x={GAUGE_CX} y={GAUGE_CY + 14} text-anchor="middle"
              dominant-baseline="middle"
              style="font-size:8px;fill:var(--chart-muted);letter-spacing:0.08em;">
              {formatBytes(systemStats.disk.used)}
            </text>
          </svg>
          <!-- Disk changes little over short intervals, so show a static used/free bar instead of a sparkline -->
          <div class="disk-bar">
            <div class="disk-bar-row">
              <span class="disk-bar-lbl">used</span>
              <div class="disk-bar-track">
                <div class="disk-bar-fill" style="width:{diskPct}%;background:{gaugeColor(diskPct)}"></div>
              </div>
              <span class="disk-bar-val">{formatBytes(systemStats.disk.used)}</span>
            </div>
            <div class="disk-bar-row">
              <span class="disk-bar-lbl">total</span>
              <div class="disk-bar-track">
                <div class="disk-bar-fill" style="width:100%;background:var(--chart-grid)"></div>
              </div>
              <span class="disk-bar-val">{formatBytes(systemStats.disk.total)}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- NETWORK -->
      <div class="monitor-card monitor-net">
        <div class="monitor-head">
          <div class="monitor-title">{$t("sys_network")}</div>
          <div class="monitor-meta">{$t("sys_uptime")} {formatUptime(systemStats.uptime)}</div>
        </div>
        <div class="net-rates">
          <div class="net-rate">
            <span class="net-rate-arrow net-rate-down">↓</span>
            <span class="net-rate-val">
              <span class="net-rate-num">{rateParts(currentDown).num}</span>
              <span class="net-rate-unit"> {rateParts(currentDown).unit}</span>
            </span>
            <span class="net-rate-total">Σ {formatBytes(systemStats.network.bytes_recv)}</span>
          </div>
          <div class="net-rate">
            <span class="net-rate-arrow net-rate-up">↑</span>
            <span class="net-rate-val">
              <span class="net-rate-num">{rateParts(currentUp).num}</span>
              <span class="net-rate-unit"> {rateParts(currentUp).unit}</span>
            </span>
            <span class="net-rate-total">Σ {formatBytes(systemStats.network.bytes_sent)}</span>
          </div>
        </div>
        <div class="net-spark">
          <svg viewBox="0 0 100 36" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient id="net-down-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="var(--chart-color-1)" stop-opacity="0.4" />
                <stop offset="100%" stop-color="var(--chart-color-1)" stop-opacity="0" />
              </linearGradient>
              <linearGradient id="net-up-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="var(--warning-color, #f59e0b)" stop-opacity="0.35" />
                <stop offset="100%" stop-color="var(--warning-color, #f59e0b)" stop-opacity="0" />
              </linearGradient>
            </defs>
            <path d={sparkArea(netDownSeries, 100, 36)} fill="url(#net-down-grad)" />
            <path d={sparkPath(netDownSeries, 100, 36)} fill="none"
              stroke="var(--chart-color-1)" stroke-width="1.4"
              stroke-linejoin="round" vector-effect="non-scaling-stroke" />
            <path d={sparkArea(netUpSeries, 100, 36)} fill="url(#net-up-grad)" />
            <path d={sparkPath(netUpSeries, 100, 36)} fill="none"
              stroke="var(--warning-color, #f59e0b)" stroke-width="1.4"
              stroke-linejoin="round" vector-effect="non-scaling-stroke"
              stroke-dasharray="2 2" />
          </svg>
        </div>
      </div>
    </div>
  {:else}
    <div class="monitor-grid">
      {#each Array(4) as _}
        <div class="monitor-card">
          <div class="monitor-head">
            <Skeleton width="45%" height="11px" radius="3px" />
            <Skeleton width="30%" height="10px" radius="3px" />
          </div>
          <div class="monitor-body">
            <Skeleton width="86px" height="86px" circle={true} />
            <Skeleton width="100%" height="44px" radius="4px" />
          </div>
        </div>
      {/each}
    </div>
  {/if}

  <!-- The period selector / trend / status donut / proxy-local distribution moved to
       the "Stats" tab of the settings modal. The main dashboard shows only real-time
       data (gauges + system monitoring). -->
</section>

<style>
  .dashboard-section {
    margin-bottom: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  /* Removed dash-header — the query condition moved to the grid. */

  /* ── System monitoring: 4 columns on desktop, graph/gauge focused ── */
  .monitor-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.6rem;
    margin-bottom: 0.75rem;
  }

  .monitor-card {
    background: var(--dashboard-card-bg);
    border: 1px solid var(--dashboard-card-border);
    border-radius: 12px;
    padding: 0.65rem 0.75rem 0.5rem;
    box-shadow: var(--shadow-light);
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    min-height: 110px;
    /* Allow the grid track to shrink so wide content (numbers/sparkline) stays
       inside the card instead of overflowing the grid. */
    min-width: 0;
    overflow: hidden;
  }

  .monitor-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
  }

  .monitor-title {
    font-size: 0.7rem;
    font-weight: 700;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .monitor-meta {
    font-size: 0.62rem;
    color: var(--chart-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 60%;
  }

  .monitor-body {
    display: grid;
    grid-template-columns: 86px minmax(0, 1fr);
    align-items: center;
    gap: 0.7rem;
    flex: 1;
    min-width: 0;
  }

  .monitor-body-stacked {
    grid-template-columns: 1fr;
    justify-items: center;
  }

  .disk-bar {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    width: 100%;
  }
  .disk-bar-row {
    display: grid;
    grid-template-columns: 36px 1fr auto;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.62rem;
    color: var(--chart-muted);
  }
  .disk-bar-lbl {
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .disk-bar-track {
    height: 4px;
    background: var(--chart-grid);
    border-radius: 999px;
    overflow: hidden;
  }
  .disk-bar-fill {
    height: 100%;
    border-radius: 999px;
    transition: width 0.6s ease, background-color 0.4s ease;
  }
  .disk-bar-val {
    font-variant-numeric: tabular-nums;
    color: var(--text-secondary);
    font-weight: 600;
  }

  .gauge {
    width: 86px;
    height: 86px;
    display: block;
  }
  .gauge-lg {
    width: 96px;
    height: 96px;
  }

  .spark {
    width: 100%;
    height: 44px;
  }
  .spark svg {
    width: 100%;
    height: 100%;
    display: block;
  }

  .monitor-net {
    grid-row: span 1;
  }

  .net-rates {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }

  .net-rate {
    display: grid;
    grid-template-columns: 14px 1fr auto;
    align-items: baseline;
    gap: 0.4rem;
    font-size: 0.75rem;
  }
  .net-rate-arrow {
    font-weight: 700;
    width: 14px;
    text-align: center;
  }
  .net-rate-down {
    color: var(--chart-color-1);
  }
  .net-rate-up {
    color: var(--warning-color, #f59e0b);
  }
  .net-rate-val {
    font-weight: 700;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
  }
  .net-rate-total {
    font-size: 0.62rem;
    color: var(--chart-muted);
    font-variant-numeric: tabular-nums;
  }
  .net-spark {
    width: 100%;
    height: 40px;
  }
  .net-spark svg {
    width: 100%;
    height: 100%;
    display: block;
  }

  /* Mobile support — the system-monitoring grid drops columns as it narrows and
   * progressively hides graphs. On smaller screens, show only the key numbers + a small gauge instead of graphs. */
  @media (max-width: 900px) {
    .monitor-grid {
      grid-template-columns: repeat(2, 1fr);
    }
  }
  /* Mobile (≤600px) — compress the 3 gauges (CPU/RAM/Disk) + network speed into one row.
   * Hide all graphs (sparkline / disk bar / network spark). */
  @media (max-width: 600px) {
    .monitor-grid {
      grid-template-columns: repeat(4, 1fr);
      gap: 0.4rem;
    }
    .monitor-card {
      min-height: 0;
      padding: 0.45rem 0.4rem;
      gap: 0.2rem;
    }
    .spark,
    .net-spark,
    .disk-bar {
      display: none;
    }
    /* The head's meta (core count / RAM size / free, etc.) is also omitted at narrow widths */
    .monitor-meta {
      display: none;
    }
    .monitor-head {
      justify-content: center;
    }
    .monitor-title {
      font-size: 0.6rem;
      letter-spacing: 0.05em;
    }
    /* Gauge alone in the center of the card — a single column instead of a left/right grid */
    .monitor-body {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0;
    }
    .gauge { width: 56px; height: 56px; }
    .gauge-lg { width: 56px; height: 56px; }

    /* Network card — with no gauge, show the ↓/↑ speeds compactly and vertically.
     * Units (B/s, KB/s, etc.) cause line breaks on mobile, so show only the numbers.
     * Center the whole card, with the arrow + numbers grouped in the middle. */
    .monitor-net .net-rates {
      flex-direction: column;
      gap: 0.15rem;
      width: 100%;
      align-items: center;
      justify-content: center;
    }
    .monitor-net .net-rate {
      display: inline-flex;
      gap: 0.3rem;
      align-items: baseline;
      justify-content: center;
      font-size: 0.78rem;
      width: auto;
    }
    .net-rate-val {
      font-size: 0.82rem;
      font-weight: 700;
      white-space: nowrap;
    }
    .net-rate-num {
      font-variant-numeric: tabular-nums;
    }
    .net-rate-unit,
    .net-rate-total {
      display: none;
    }
  }
</style>
