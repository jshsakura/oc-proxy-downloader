<script>
  import { t } from "./i18n.js";

  export let byStatus = {};

  const CX = 100;
  const CY = 100;
  const R = 80;
  const R_INNER = 55;
  const C = 2 * Math.PI * R;

  const statusOrder = [
    { key: "done", color: "var(--chart-color-1)", label: "dashboard_status_done" },
    { key: "failed", color: "var(--chart-color-2)", label: "dashboard_status_failed" },
    { key: "stopped", color: "var(--chart-color-3)", label: "dashboard_status_stopped" },
    { key: "downloading", color: "var(--chart-muted)", label: "dashboard_status_downloading" },
    { key: "pending", color: "var(--warning-color)", label: "status_pending" },
  ];

  let hoveredSeg = -1;

  $: total = computeTotal(byStatus);
  $: segments = buildSegments(byStatus, total);
  $: successPct = total > 0 && byStatus.done ? Math.round((byStatus.done / total) * 100) : 0;

  function computeTotal(bs) {
    if (!bs) return 0;
    return Object.values(bs).reduce((s, v) => s + (v || 0), 0);
  }

  function buildSegments(bs, tot) {
    if (!bs || tot === 0) return [];
    const segs = [];
    let offset = 0;
    for (const s of statusOrder) {
      const count = bs[s.key] || 0;
      if (count === 0) continue;
      const pct = count / tot;
      const dash = pct * C;
      const gap = segments_total_gap(segs.length, bs, tot);
      segs.push({
        ...s,
        count,
        dashArray: `${Math.max(0, dash - gap)} ${C - dash + gap}`,
        dashOffset: -offset * C + gap / 2,
        pctStr: Math.round(pct * 100) + "%",
        pct,
      });
      offset += pct;
    }
    return segs;
  }

  function segments_total_gap(count, bs, tot) {
    return count > 0 ? 3 : 0;
  }

  $: label = $t("dashboard_status_distribution");
  $: emptyLabel = $t("dashboard_no_data");
</script>

<div class="donut-wrap">
  <svg
    viewBox="0 0 200 200"
    preserveAspectRatio="xMidYMid meet"
    role="img"
    aria-label={label}
    style="width:100%;max-width:200px;height:auto;display:block;margin:0 auto;"
  >
    <defs>
      <filter id="donutGlow">
        <feGaussianBlur stdDeviation="2" result="coloredBlur" />
        <feMerge>
          <feMergeNode in="coloredBlur" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
    </defs>

    {#if total > 0 && segments.length > 0}
      <circle
        cx={CX}
        cy={CY}
        r={R}
        fill="none"
        stroke="var(--chart-grid)"
        stroke-width={R - R_INNER}
        opacity="0.3"
      />
      {#each segments as seg, i}
        <circle
          cx={CX}
          cy={CY}
          r={R}
          fill="none"
          stroke={seg.color}
          stroke-width={hoveredSeg === i ? R - R_INNER + 6 : R - R_INNER}
          stroke-dasharray={seg.dashArray}
          stroke-dashoffset={seg.dashOffset}
          transform="rotate(-90 {CX} {CY})"
          stroke-linecap="butt"
          filter={hoveredSeg === i ? "url(#donutGlow)" : ""}
          style="transition: stroke-width 0.2s ease, filter 0.2s ease; cursor: pointer;"
          on:mouseenter={() => hoveredSeg = i}
          on:mouseleave={() => hoveredSeg = -1}
        />
      {/each}

      <text
        x={CX}
        y={CY - 8}
        text-anchor="middle"
        dominant-baseline="middle"
        style="font-size:28px;font-weight:800;fill:var(--dashboard-stat-value);"
      >
        {successPct}%
      </text>
      <text
        x={CX}
        y={CY + 12}
        text-anchor="middle"
        dominant-baseline="middle"
        style="font-size:9px;fill:var(--chart-muted);letter-spacing:0.1em;text-transform:uppercase;"
      >
        success
      </text>
    {:else}
      <text
        x={CX}
        y={CY}
        text-anchor="middle"
        dominant-baseline="middle"
        style="font-size:14px;fill:var(--chart-muted);"
      >
        {emptyLabel}
      </text>
    {/if}
  </svg>

  {#if total > 0 && segments.length > 0}
    <div class="donut-legend">
      {#each segments as seg, i}
        <div
          class="legend-item"
          class:hovered={hoveredSeg === i}
          on:mouseenter={() => hoveredSeg = i}
          on:mouseleave={() => hoveredSeg = -1}
        >
          <span class="legend-dot" style="background:{seg.color}"></span>
          <span class="legend-label">{$t(seg.label)}</span>
          <span class="legend-value">{seg.count}</span>
          <span class="legend-pct">{seg.pctStr}</span>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .donut-wrap {
    width: 100%;
  }
  .donut-legend {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.3rem 0.8rem;
    margin-top: 0.75rem;
  }
  .legend-item {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: 0.75rem;
    color: var(--text-secondary);
    padding: 0.25rem 0.4rem;
    border-radius: 6px;
    transition: background 0.15s ease;
    cursor: default;
  }
  .legend-item.hovered {
    background: rgba(var(--primary-color-rgb, 99, 102, 241), 0.08);
    color: var(--text-primary);
  }
  .legend-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .legend-label {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .legend-value {
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }
  .legend-pct {
    color: var(--chart-muted);
    font-size: 0.7rem;
    min-width: 2.2em;
    text-align: right;
  }
</style>
