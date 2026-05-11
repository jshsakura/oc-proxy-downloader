<script>
  import { t } from "./i18n.js";

  export let data = [];

  const W = 500;
  const H = 200;
  const PAD_L = 40;
  const PAD_R = 10;
  const PAD_T = 10;
  const PAD_B = 30;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;

  $: points = buildPoints(data);
  $: areaPath = buildAreaPath(points, plotH);
  $: linePath = buildLinePath(points);
  $: yTicks = buildYTicks(data);
  $: xLabels = buildXLabels(data);

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

  function buildLinePath(pts) {
    if (pts.length === 0) return "";
    return pts.map((p, i) => (i === 0 ? `M${p.x},${p.y}` : `L${p.x},${p.y}`)).join(" ");
  }

  function buildAreaPath(pts, h) {
    if (pts.length === 0) return "";
    const base = PAD_T + h;
    const line = pts.map((p, i) => (i === 0 ? `M${p.x},${p.y}` : `L${p.x},${p.y}`)).join(" ");
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

  $: label = $t("dashboard_trend_title");
  $: emptyLabel = $t("dashboard_no_data");
</script>

<svg
  viewBox="0 0 {W} {H}"
  preserveAspectRatio="xMidYMid meet"
  role="img"
  aria-label={label}
  style="width:100%;height:auto;"
>
  <title>{label}</title>

  {#if data && data.length > 0}
    <!-- Grid lines -->
    {#each yTicks as tick}
      <line
        x1={PAD_L}
        y1={tick.y}
        x2={W - PAD_R}
        y2={tick.y}
        stroke="var(--chart-grid)"
        stroke-width="1"
      />
      <text
        x={PAD_L - 6}
        y={tick.y + 4}
        text-anchor="end"
        style="color: var(--chart-muted); font-size: 10px; fill: var(--chart-muted);"
      >
        {tick.val}
      </text>
    {/each}

    <!-- X axis labels -->
    {#each xLabels as xl}
      <text
        x={xl.x}
        y={H - 4}
        text-anchor="middle"
        style="color: var(--chart-muted); font-size: 9px; fill: var(--chart-muted);"
      >
        {xl.label}
      </text>
    {/each}

    <!-- Area fill -->
    <path d={areaPath} fill="var(--chart-color-1)" fill-opacity="0.15" stroke="none" />

    <!-- Line -->
    <path d={linePath} fill="none" stroke="var(--chart-color-1)" stroke-width="2" stroke-linejoin="round" />
  {:else}
    <text
      x={W / 2}
      y={H / 2}
      text-anchor="middle"
      dominant-baseline="middle"
      style="color: var(--chart-muted); font-size: 14px; fill: var(--chart-muted);"
    >
      {emptyLabel}
    </text>
  {/if}
</svg>
