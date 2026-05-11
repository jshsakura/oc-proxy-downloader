<script>
  import { t } from "./i18n.js";

  export let byStatus = {};

  const CX = 100;
  const CY = 90;
  const R = 70;
  const R_INNER = 45;
  const C = 2 * Math.PI * R;

  const statusOrder = [
    { key: "done", color: "var(--chart-color-1)", label: "dashboard_status_done" },
    { key: "failed", color: "var(--chart-color-2)", label: "dashboard_status_failed" },
    { key: "stopped", color: "var(--chart-color-3)", label: "dashboard_status_stopped" },
    { key: "downloading", color: "var(--chart-color-muted, var(--chart-muted))", label: "dashboard_status_downloading" },
  ];

  $: total = computeTotal(byStatus);
  $: segments = buildSegments(byStatus, total);

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
      segs.push({
        ...s,
        count,
        dashArray: `${dash} ${C - dash}`,
        dashOffset: -offset * C,
        pctStr: Math.round(pct * 100) + "%",
      });
      offset += pct;
    }
    return segs;
  }

  $: label = $t("dashboard_status_distribution");
  $: emptyLabel = $t("dashboard_no_data");
</script>

<div>
  <svg
    viewBox="0 0 200 200"
    preserveAspectRatio="xMidYMid meet"
    role="img"
    aria-label={label}
    style="width:100%;max-width:200px;height:auto;display:block;margin:0 auto;"
  >
    <title>{label}</title>

    {#if total > 0 && segments.length > 0}
      <circle
        cx={CX}
        cy={CY}
        r={R}
        fill="none"
        stroke="var(--chart-grid)"
        stroke-width={R - R_INNER}
      />
      {#each segments as seg}
        <circle
          cx={CX}
          cy={CY}
          r={R}
          fill="none"
          stroke={seg.color}
          stroke-width={R - R_INNER}
          stroke-dasharray={seg.dashArray}
          stroke-dashoffset={seg.dashOffset}
          transform="rotate(-90 {CX} {CY})"
          stroke-linecap="butt"
        />
      {/each}
      <text
        x={CX}
        y={CY - 4}
        text-anchor="middle"
        dominant-baseline="middle"
        style="font-size:24px;font-weight:700;fill:var(--dashboard-stat-value);"
      >
        {total}
      </text>
      <text
        x={CX}
        y={CY + 14}
        text-anchor="middle"
        dominant-baseline="middle"
        style="font-size:10px;fill:var(--chart-muted);"
      >
        total
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
    <div style="display:flex;flex-wrap:wrap;gap:0.5rem 1rem;justify-content:center;margin-top:0.5rem;">
      {#each segments as seg}
        <div style="display:flex;align-items:center;gap:0.3rem;font-size:0.8rem;color:var(--text-secondary);">
          <span style="width:10px;height:10px;border-radius:50%;background:{seg.color};display:inline-block;flex-shrink:0;"></span>
          {$t(seg.label)} ({seg.count})
        </div>
      {/each}
    </div>
  {/if}
</div>
