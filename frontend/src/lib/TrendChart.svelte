<script>
  import { t } from "./i18n.js";

  export let data = [];

  const W = 520;
  const H = 220;
  const PAD_L = 44;
  const PAD_R = 12;
  const PAD_T = 12;
  const PAD_B = 28;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;

  let hoveredIdx = -1;
  let svgEl;

  $: points = buildPoints(data);
  $: smoothLine = buildSmoothPath(points);
  $: smoothArea = buildSmoothArea(points);
  $: yTicks = buildYTicks(data);
  $: xLabels = buildXLabels(data);
  $: tooltipData = hoveredIdx >= 0 && data[hoveredIdx] ? data[hoveredIdx] : null;
  $: tooltipPos = hoveredIdx >= 0 && points[hoveredIdx] ? points[hoveredIdx] : null;

  function maxCount(d) {
    if (!d || d.length === 0) return 0;
    return Math.max(...d.map((r) => r.count || 0), 1);
  }

  function buildPoints(d) {
    if (!d || d.length === 0) return [];
    const mx = maxCount(d);
    return d.map((row, i) => {
      const x = PAD_L + (d.length === 1 ? plotW / 2 : (i / (d.length - 1)) * plotW);
      const y = PAD_T + plotH - ((row.count || 0) / mx) * plotH;
      return { x, y, count: row.count || 0 };
    });
  }

  function buildSmoothPath(pts) {
    if (pts.length < 2) return pts.length === 1 ? `M${pts[0].x},${pts[0].y}` : "";
    let d = `M${pts[0].x},${pts[0].y}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[Math.max(0, i - 1)];
      const p1 = pts[i];
      const p2 = pts[i + 1];
      const p3 = pts[Math.min(pts.length - 1, i + 2)];
      const cp1x = p1.x + (p2.x - p0.x) / 6;
      const cp1y = p1.y + (p2.y - p0.y) / 6;
      const cp2x = p2.x - (p3.x - p1.x) / 6;
      const cp2y = p2.y - (p3.y - p1.y) / 6;
      d += ` C${cp1x},${cp1y} ${cp2x},${cp2y} ${p2.x},${p2.y}`;
    }
    return d;
  }

  function buildSmoothArea(pts) {
    if (pts.length < 2) return "";
    const base = PAD_T + plotH;
    const line = buildSmoothPath(pts);
    const last = pts[pts.length - 1];
    const first = pts[0];
    return `${line} L${last.x},${base} L${first.x},${base} Z`;
  }

  function buildYTicks(d) {
    if (!d || d.length === 0) return [];
    const mx = maxCount(d);
    const ticks = [];
    const steps = 4;
    for (let i = 0; i <= steps; i++) {
      const val = Math.round((mx / steps) * i);
      const y = PAD_T + plotH - (i / steps) * plotH;
      ticks.push({ val, y });
    }
    return ticks;
  }

  function buildXLabels(d) {
    if (!d || d.length === 0) return [];
    const maxLabels = 8;
    const step = Math.max(1, Math.ceil(d.length / maxLabels));
    return d
      .map((row, i) => {
        if (i % step !== 0 && i !== d.length - 1) return null;
        const x = PAD_L + (d.length === 1 ? plotW / 2 : (i / (d.length - 1)) * plotW);
        const label = row.date ? row.date.slice(5) : "";
        return { x, label };
      })
      .filter(Boolean);
  }

  function handleMouseMove(e) {
    if (!svgEl || !data || data.length === 0) return;
    const rect = svgEl.getBoundingClientRect();
    const scaleX = W / rect.width;
    const mx = (e.clientX - rect.left) * scaleX;
    let closest = -1;
    let minDist = Infinity;
    for (let i = 0; i < points.length; i++) {
      const dist = Math.abs(points[i].x - mx);
      if (dist < minDist) {
        minDist = dist;
        closest = i;
      }
    }
    hoveredIdx = closest;
  }

  function handleMouseLeave() {
    hoveredIdx = -1;
  }

  $: label = $t("dashboard_trend_title");
  $: emptyLabel = $t("dashboard_no_data");
</script>

<div class="trend-chart-wrap">
  <svg
    bind:this={svgEl}
    viewBox="0 0 {W} {H}"
    preserveAspectRatio="xMidYMid meet"
    role="img"
    aria-label={label}
    on:mousemove={handleMouseMove}
    on:mouseleave={handleMouseLeave}
  >
    <defs>
      <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="var(--chart-color-1)" stop-opacity="0.35" />
        <stop offset="100%" stop-color="var(--chart-color-1)" stop-opacity="0.02" />
      </linearGradient>
      <linearGradient id="lineGradient" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="var(--chart-color-1)" stop-opacity="0.6" />
        <stop offset="50%" stop-color="var(--chart-color-1)" stop-opacity="1" />
        <stop offset="100%" stop-color="var(--chart-color-1)" stop-opacity="0.6" />
      </linearGradient>
      <filter id="glow">
        <feGaussianBlur stdDeviation="3" result="coloredBlur" />
        <feMerge>
          <feMergeNode in="coloredBlur" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
    </defs>

    {#if data && data.length > 0}
      {#each yTicks as tick}
        <line
          x1={PAD_L}
          y1={tick.y}
          x2={W - PAD_R}
          y2={tick.y}
          stroke="var(--chart-grid)"
          stroke-width="0.5"
          stroke-dasharray="4,4"
        />
        <text
          x={PAD_L - 8}
          y={tick.y + 4}
          text-anchor="end"
          style="font-size:10px;fill:var(--chart-muted);"
        >
          {tick.val}
        </text>
      {/each}

      {#each xLabels as xl}
        <text
          x={xl.x}
          y={H - 4}
          text-anchor="middle"
          style="font-size:9px;fill:var(--chart-muted);"
        >
          {xl.label}
        </text>
      {/each}

      <path d={smoothArea} fill="url(#areaGradient)" stroke="none">
        <animate attributeName="opacity" from="0" to="1" dur="0.8s" fill="freeze" />
      </path>

      <path
        d={smoothLine}
        fill="none"
        stroke="url(#lineGradient)"
        stroke-width="2.5"
        stroke-linejoin="round"
        stroke-linecap="round"
        filter="url(#glow)"
      >
        <animate attributeName="stroke-dashoffset" from="2000" to="0" dur="1.2s" fill="freeze" />
        <animate attributeName="stroke-dasharray" from="2000" to="2000" dur="0.01s" fill="freeze" />
      </path>

      {#if hoveredIdx >= 0 && points[hoveredIdx]}
        {@const pt = points[hoveredIdx]}
        <line
          x1={pt.x}
          y1={PAD_T}
          x2={pt.x}
          y2={PAD_T + plotH}
          stroke="var(--chart-color-1)"
          stroke-width="1"
          stroke-dasharray="3,3"
          stroke-opacity="0.5"
        />
        <circle
          cx={pt.x}
          cy={pt.y}
          r="5"
          fill="var(--chart-color-1)"
          stroke="var(--card-background)"
          stroke-width="2.5"
        />
        <circle
          cx={pt.x}
          cy={pt.y}
          r="10"
          fill="var(--chart-color-1)"
          fill-opacity="0.15"
        />
      {/if}
    {:else}
      <text
        x={W / 2}
        y={H / 2}
        text-anchor="middle"
        dominant-baseline="middle"
        style="font-size:14px;fill:var(--chart-muted);"
      >
        {emptyLabel}
      </text>
    {/if}
  </svg>

  {#if hoveredIdx >= 0 && tooltipData && tooltipPos}
    <div
      class="chart-tooltip"
      style="left:{tooltipPos.x / W * 100}%;top:{tooltipPos.y / H * 100}%"
    >
      <div class="tooltip-date">{tooltipData.date || ''}</div>
      <div class="tooltip-value">{tooltipData.count || 0}</div>
    </div>
  {/if}
</div>

<style>
  .trend-chart-wrap {
    position: relative;
    width: 100%;
  }
  .chart-tooltip {
    position: absolute;
    transform: translate(-50%, -120%);
    background: var(--card-background);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 0.4rem 0.7rem;
    box-shadow: var(--shadow-medium);
    pointer-events: none;
    z-index: 10;
    white-space: nowrap;
    text-align: center;
  }
  .tooltip-date {
    font-size: 0.7rem;
    color: var(--text-secondary);
    margin-bottom: 0.1rem;
  }
  .tooltip-value {
    font-size: 0.95rem;
    font-weight: 700;
    color: var(--primary-color);
  }
</style>
