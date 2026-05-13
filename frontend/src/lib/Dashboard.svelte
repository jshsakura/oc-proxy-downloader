<script>
  import { t } from "./i18n.js";

  export let systemStats = null;
  // 기간(조회 조건) 은 그리드 헤더로 이동. Dashboard 는 라이브 상태 + 시스템
  // 모니터링만 책임짐.

  // 시스템 모니터링 스파크라인용 슬라이딩 버퍼.
  // systemStats 가 5 초마다 갱신될 때 마지막 N 포인트만 유지해 라이브 차트로 보여줌.
  const SPARK_POINTS = 40;
  let cpuSeries = [];
  let ramSeries = [];
  let netDownSeries = [];
  let netUpSeries = [];

  // bytes_sent/recv 은 누적값이므로 이전 값과 차이를 받아 throughput 으로 환산.
  let prevNet = null;
  let prevTs = 0;

  function pushSeries(series, value) {
    // 첫 샘플이면 SPARK_POINTS 만큼 같은 값으로 prefill — 그래야 페이지 진입 즉시
    // 평탄선이라도 그려져서 카드가 휑해 보이지 않는다.
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
      // 첫 진입 — 다음 샘플이 와야 throughput 계산 가능. 일단 0 평탄선으로 채워둠.
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

  // 모바일용 — 단위는 CSS 로 숨길 수 있도록 숫자/단위 두 span 으로 분리해서 노출.
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

  // 0..1 진행도 + r 반지름 → SVG 도넛 stroke-dasharray 두 값을 반환.
  // 모든 게이지가 같은 공식을 쓰도록 한 곳에 모아둠.
  function arcDash(pct, r) {
    const C = 2 * Math.PI * r;
    const filled = Math.max(0, Math.min(1, pct)) * C;
    return `${filled} ${C - filled}`;
  }

  // 라인 차트용 path (스파크라인). 컨테이너 가로폭에 맞게 0..W 스케일.
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

  // 게이지 공통 파라미터
  const GAUGE_R = 36;
  const GAUGE_CX = 50;
  const GAUGE_CY = 50;

  function gaugeColor(pct) {
    // 65% 이하 — primary(보통), 88% 이하 — warning, 그 이상 — danger.
    // 임계가 너무 낮으면 idle 시스템도 경고색이라 색이 산만해짐.
    if (pct >= 88) return "var(--danger-color, #ef4444)";
    if (pct >= 65) return "var(--warning-color, #f59e0b)";
    return "var(--primary-color)";
  }

  $: cpuPct = (systemStats && systemStats.cpu && systemStats.cpu.percent) || 0;
  $: ramPct = (systemStats && systemStats.memory && systemStats.memory.percent) || 0;
  $: diskPct = (systemStats && systemStats.disk && systemStats.disk.percent) || 0;

  $: currentDown = netDownSeries.length ? netDownSeries[netDownSeries.length - 1] : 0;
  $: currentUp = netUpSeries.length ? netUpSeries[netUpSeries.length - 1] : 0;
</script>

<section class="dashboard-section">
  <!-- 조회 조건(기간) 은 그리드(다운로드 목록) 쪽으로 이동. Dashboard 는 라이브
       상태와 시스템 모니터링만 노출. -->
  <!-- 부모(App.svelte) 가 ProxyGauge/LocalGauge 를 합본 카드로 주입. -->
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
              {cpuPct.toFixed(0)}<tspan style="font-size:10px;fill:var(--chart-muted);">%</tspan>
            </text>
            <text x={GAUGE_CX} y={GAUGE_CY + 14} text-anchor="middle"
              dominant-baseline="middle"
              style="font-size:8px;fill:var(--chart-muted);letter-spacing:0.08em;">
              LOAD {systemStats.cpu.load_avg_1}
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
          <!-- 디스크는 짧은 시간 변화량이 적어서 스파크라인 대신 used/free 정적 바를 노출 -->
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
  {/if}

  <!-- 기간 선택 / 트렌드 / 상태 도넛 / 프록시-로컬 분포는 설정 모달의 "통계" 탭으로
       이동했음. 메인 대시보드는 실시간 (gauges + 시스템 모니터링) 만 노출. -->
</section>

<style>
  .dashboard-section {
    margin-bottom: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  /* dash-header 제거 — 조회 조건은 그리드로 이동. */

  /* ── 시스템 모니터링: PC 4 컬럼, 그래프/게이지 위주 ── */
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
    grid-template-columns: 86px 1fr;
    align-items: center;
    gap: 0.7rem;
    flex: 1;
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

  /* 모바일 대응 — 시스템 모니터링 그리드는 좁아질수록 컬럼 줄이고 그래프는
   * 점차 숨김. 작은 화면일수록 그래프 대신 핵심 숫자 + 작은 게이지만 노출. */
  @media (max-width: 900px) {
    .monitor-grid {
      grid-template-columns: repeat(2, 1fr);
    }
  }
  /* 모바일(≤600px) — 게이지 3 개(CPU/RAM/Disk) + 네트워크 속도까지 한 줄로 압축.
   * 그래프(스파크라인 / 디스크 막대 / 네트워크 스파크) 는 모두 숨김. */
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
    /* head 의 메타(코어수 / RAM 용량 / free 등) 도 좁은 폭에선 생략 */
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
    /* 게이지를 카드 중앙에 단독으로 — 좌·우 그리드 대신 single column */
    .monitor-body {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0;
    }
    .gauge { width: 56px; height: 56px; }
    .gauge-lg { width: 56px; height: 56px; }

    /* 네트워크 카드 — 게이지가 없으니 ↓/↑ 속도를 세로로 컴팩트 노출.
     * 단위(B/s, KB/s 등) 는 모바일에서 줄바뀜 유발해서 숫자만 노출.
     * 카드 전체 중앙 정렬. 좌측에 화살표 + 숫자가 가운데 모이게. */
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
