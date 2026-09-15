<script>
  import { onMount, onDestroy, createEventDispatcher } from "svelte";
  import {
    createGrid,
    ModuleRegistry,
    AllCommunityModule
  } from "ag-grid-community";
  import "ag-grid-community/styles/ag-grid.css";
  import "ag-grid-community/styles/ag-theme-quartz.css";
  import { t } from "./i18n.js";
  import { truncateMiddle } from "./grid.js";
  import { theme } from "./theme.js";

  import ChevronLeftIcon from "../icons/ChevronLeftIcon.svelte";
  import ChevronRightIcon from "../icons/ChevronRightIcon.svelte";

  ModuleRegistry.registerModules([AllCommunityModule]);

  export let downloads = [];
  export let currentTab = "working"; // "working" | "completed"
  export let selectedIds = new Set();
  export let auditingIds = new Set();
  export let downloadWaitInfo = {};
  export let downloadProxyInfo = {};
  export let currentTime = Date.now();
  export let isDownloadsLoading = false;
  // Truthy when the last grid fetch failed (D-02): kept distinct from a
  // genuinely empty list so an outage never reads as "no downloads".
  export let gridError = null;
  export let currentPage = 1;
  export let totalPages = 1;
  export let itemsPerPage = 10;
  export let totalCount = 0;
  // AG Grid renderers are plain DOM classes. A direct callback avoids routing
  // the details action through a component CustomEvent boundary.
  export let onDetails = null;

  const dispatch = createEventDispatcher();

  let gridContainer;
  let gridApi = null;

  // One density authority (DESIGN.md 4.1/4.2): 44px rows, 40px header,
  // grid height clamped to 350-500px below 640px and 400-800px above.
  const GRID_ROW_HEIGHT = 44;
  const GRID_HEADER_HEIGHT = 40;

  // Speed history buffer per download ID: maps id -> number[] (up to 16 points)
  const speedHistories = new Map();

  function openDetails(download) {
    if (typeof onDetails === "function") {
      onDetails(download);
      return;
    }
    // Keep the event as a compatibility fallback for other consumers.
    dispatch("details", { download });
  }

  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    const val = bytes / Math.pow(1024, i);
    return val.toFixed(i === 0 ? 0 : 1) + " " + units[i];
  }

  function formatSpeed(bytesPerSec) {
    if (!bytesPerSec || bytesPerSec === 0) return "0 B/s";
    const units = ["B/s", "KB/s", "MB/s", "GB/s"];
    const i = Math.floor(Math.log(bytesPerSec) / Math.log(1024));
    const val = bytesPerSec / Math.pow(1024, i);
    return val.toFixed(i === 0 ? 0 : 1) + " " + units[i];
  }

  function formatWaitTime(seconds) {
    if (!seconds || seconds <= 0) return "0:00";
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s < 10 ? "0" : ""}${s}`;
  }

  function formatEta(seconds) {
    if (!seconds || seconds <= 0 || !isFinite(seconds)) return "";
    if (seconds < 60) return `~${Math.round(seconds)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    if (m < 60) return `~${m}m ${s > 0 ? s + "s" : ""}`.trim();
    const h = Math.floor(m / 60);
    const remM = m % 60;
    return `~${h}h ${remM > 0 ? remM + "m" : ""}`.trim();
  }

  function formatDate(isoStr) {
    if (!isoStr) return "-";
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return "-";
      return `${d.getMonth() + 1}/${d.getDate()}`;
    } catch {
      return "-";
    }
  }

  function formatFullDateTime(isoStr) {
    if (!isoStr) return "";
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return "";
      return d.toLocaleString();
    } catch {
      return "";
    }
  }

  function isPlaceholderName(name) {
    if (!name) return true;
    const n = name.trim().toLowerCase();
    const placeholders = [
      $t("file_name_fetching"),
      $t("file_name_queued"),
      $t("file_name_na"),
    ].map((s) => s.trim().toLowerCase());
    return (
      placeholders.includes(n) ||
      n.startsWith("1fichier:") ||
      n.startsWith("mega:")
    );
  }

  function getDisplayFileName(download) {
    const name = download?.filename;
    if (name && !isPlaceholderName(name)) return truncateMiddle(name, 56);
    const st = (download?.status || "").toLowerCase();
    if (st === "pending") return $t("file_name_queued");
    if (["parsing", "proxying", "downloading", "waiting"].includes(st))
      return $t("file_name_fetching");
    if (st === "failed" || st === "stopped") return $t("file_name_failed");
    if (st === "done") return $t("file_name_unresolved");
    const m = (name || "").trim().match(/^(?:1fichier|mega):(.+)$/i);
    return m ? m[1] : $t("file_name_na");
  }

  function getDownloadProgress(download) {
    if (currentTab === "completed") return 100;
    if (download.progress !== undefined && download.progress !== null) {
      return Math.min(100, Math.max(0, Math.round(download.progress)));
    }
    if (download.downloaded_size && download.total_size) {
      return Math.min(
        100,
        Math.max(
          0,
          Math.round((download.downloaded_size / download.total_size) * 100)
        )
      );
    }
    return 0;
  }

  function getStatusTooltip(download) {
    const proxyInfo = downloadProxyInfo[download.id];
    if (
      download.status?.toLowerCase() === "pending" &&
      download.error_message &&
      download.error_message.includes($t("auto_retry_in_progress"))
    ) {
      return download.error_message + "\n" + $t("auto_retry_interval_notice");
    }
    if (download.status?.toLowerCase() === "failed" && download.error_message) {
      let retryNote = "";
      if (
        download.next_retry_at &&
        new Date(download.next_retry_at).getTime() > Date.now()
      ) {
        retryNote =
          "\n" +
          $t("retry_cooldown", {
            when: new Date(download.next_retry_at).toLocaleTimeString()
          });
        if (download.attempt_count) retryNote += ` (↻${download.attempt_count})`;
      } else if (download.attempt_count) {
        retryNote = "\n" + $t("retry_exhausted");
      }
      return download.error_message + retryNote;
    }
    return `${$t("table_header_status")}: ${$t("download_" + download.status?.toLowerCase()) || download.status}`;
  }

  // Generate SVG Sparkline Path
  function generateSparkline(values, W = 46, H = 18) {
    if (!values || values.length < 2) {
      return {
        line: `M 0,${H - 2} L ${W},${H - 2}`,
        area: `M 0,${H - 2} L ${W},${H - 2} L ${W},${H} L 0,${H} Z`
      };
    }
    const max = Math.max(1, ...values);
    const min = 0;
    const span = max - min || 1;
    const stepX = W / (values.length - 1);
    const usableH = H - 4;
    const padTop = 2;

    const line = values
      .map((v, i) => {
        const x = i * stepX;
        const y = padTop + usableH - ((v - min) / span) * usableH;
        return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");

    const area = `${line} L${W},${H} L0,${H} Z`;
    return { line, area };
  }

  // Update speed history buffer
  function recordSpeed(download) {
    if (!download || !download.id) return;
    const st = (download.status || "").toLowerCase();
    const isLive = ["downloading", "proxying", "parsing"].includes(st);
    const spd = isLive ? (download.download_speed || 0) : 0;

    let history = speedHistories.get(download.id);
    if (!history) {
      history = Array(8).fill(spd);
      speedHistories.set(download.id, history);
    } else {
      history.push(spd);
      if (history.length > 16) history.shift();
    }
  }

  // ---- Custom Cell Renderers ----

  class SelectHeaderRenderer {
    init(params) {
      this.params = params;
      this.eGui = document.createElement("div");
      this.eGui.className = "ag-custom-checkbox-wrap header-checkbox";
      this.checkbox = document.createElement("input");
      this.checkbox.type = "checkbox";
      this.checkbox.className = "ag-custom-checkbox";

      this.checkbox.addEventListener("change", () => {
        dispatch("toggleSelectAll");
      });

      this.eGui.appendChild(this.checkbox);
      this.updateState();
    }
    getGui() {
      return this.eGui;
    }
    updateState() {
      const allCount = downloads.length;
      const selCount = downloads.filter((d) => selectedIds.has(d.id)).length;
      if (allCount > 0 && selCount === allCount) {
        this.checkbox.checked = true;
        this.checkbox.indeterminate = false;
      } else if (selCount > 0) {
        this.checkbox.checked = false;
        this.checkbox.indeterminate = true;
      } else {
        this.checkbox.checked = false;
        this.checkbox.indeterminate = false;
      }
      // Localized name (D-15): reuses the "all {count}" vocabulary until the
      // D-07 locale decision lands; the checkbox state itself is native.
      const label = $t("all_downloads_short", { count: allCount });
      this.checkbox.setAttribute("aria-label", label);
      this.checkbox.title = label;
    }
    refresh() {
      this.updateState();
      return true;
    }
  }

  class SelectCellRenderer {
    init(params) {
      this.params = params;
      this.eGui = document.createElement("div");
      this.eGui.className = "ag-custom-checkbox-wrap";
      this.checkbox = document.createElement("input");
      this.checkbox.type = "checkbox";
      this.checkbox.className = "ag-custom-checkbox";
      this.checkbox.checked = selectedIds.has(params.data?.id);

      this.checkbox.addEventListener("change", (e) => {
        e.stopPropagation();
        dispatch("toggleSelect", { id: this.params.data?.id });
      });

      this.eGui.appendChild(this.checkbox);
      this.applyName(params);
    }
    getGui() {
      return this.eGui;
    }
    applyName(params) {
      const d = params.data;
      const label = `${$t("table_header_file_name")}: ${
        d?.filename || d?.url || d?.id || ""
      }`;
      this.checkbox.setAttribute("aria-label", label);
      this.checkbox.title = label;
    }
    refresh(params) {
      this.params = params;
      this.checkbox.checked = selectedIds.has(params.data?.id);
      this.applyName(params);
      return true;
    }
  }

  class FilenameCellRenderer {
    init(params) {
      this.params = params;
      this.eGui = document.createElement("div");
      this.eGui.className = "filename-cell ag-filename-cell";
      // Real button (D-35): filename details are keyboard reachable, and the
      // full value rides along as the accessible name since the text truncates.
      this.btn = document.createElement("button");
      this.btn.type = "button";
      this.btn.className = "ag-filename-button";
      this.nameSpan = document.createElement("span");
      this.nameSpan.className = "filename-text ag-filename-text";
      this.btn.appendChild(this.nameSpan);

      this.btn.addEventListener("click", () => {
        if (this.params.data) {
          openDetails(this.params.data);
        }
      });

      this.eGui.appendChild(this.btn);
      this.update(params);
    }
    getGui() {
      return this.eGui;
    }
    refresh(params) {
      this.params = params;
      this.update(params);
      return true;
    }
    update(params) {
      const d = params.data;
      if (!d) return;
      this.nameSpan.textContent = getDisplayFileName(d);
      const full = d.filename || d.url || "";
      this.btn.title = full;
      this.btn.setAttribute("aria-label", full || getDisplayFileName(d));
    }
  }

  class StatusCellRenderer {
    init(params) {
      this.params = params;
      this.eGui = document.createElement("div");
      this.eGui.className = "ag-status-cell-wrap";
      this.pill = document.createElement("span");
      this.eGui.appendChild(this.pill);
      this.update(params);
    }
    getGui() {
      return this.eGui;
    }
    refresh(params) {
      this.params = params;
      this.update(params);
      return true;
    }
    update(params) {
      const d = params.data;
      if (!d) return;

      const st = (d.status || "").toLowerCase();
      const isProxy = !!d.use_proxy;
      const isAuditing = auditingIds.has(d.id);
      const wait = downloadWaitInfo[d.id];

      this.pill.className = `status status-${st} interactive-status ${
        isProxy ? "proxy-status" : "local-status"
      }`;
      this.pill.title = getStatusTooltip(d);

      if (isAuditing) {
        this.pill.innerHTML = `<span class="audit-loading"><span class="row-audit-spinner"></span>${$t("action_audit_running")}</span>`;
      } else if (
        wait &&
        wait.remaining_time > 0 &&
        ["waiting", "parsing", "proxying", "pending"].includes(st)
      ) {
        this.pill.innerHTML = `<span class="wait-countdown">${$t("download_waiting_time")} (${formatWaitTime(
          wait.remaining_time
        )})<span class="wait-indicator wait-indicator-waiting"></span></span>`;
      } else if (st === "downloading" && !d.progress) {
        this.pill.innerHTML = `<span class="wait-countdown">${$t("download_downloading")}<span class="wait-indicator wait-indicator-${st}"></span></span>`;
      } else if (st === "failed" && d.failure_kind) {
        if (d.next_retry_at && new Date(d.next_retry_at).getTime() > currentTime) {
          const remSec = Math.max(0, (new Date(d.next_retry_at).getTime() - currentTime) / 1000);
          this.pill.innerHTML = `${$t("download_retry_pending")} <span class="wait-countdown">(${formatWaitTime(
            remSec
          )})</span>`;
        } else if (d.attempt_count) {
          this.pill.innerHTML = `<span class="status-exhausted">${$t("kind_" + d.failure_kind)}</span>`;
        } else {
          this.pill.textContent = $t("kind_" + d.failure_kind);
        }
      } else {
        const label = $t(`download_${st}`) || st;
        const liveDot = ["proxying", "parsing", "downloading"].includes(st)
          ? `<span class="proxy-indicator proxy-indicator-${st}"></span>`
          : "";
        this.pill.innerHTML = `${label}${liveDot}`;
      }
    }
  }

  class SizeCellRenderer {
    init(params) {
      this.eGui = document.createElement("span");
      this.eGui.className = "ag-size-text";
      this.update(params);
    }
    getGui() {
      return this.eGui;
    }
    refresh(params) {
      this.update(params);
      return true;
    }
    update(params) {
      const d = params.data;
      if (!d) return;
      this.eGui.textContent = d.total_size
        ? formatBytes(d.total_size)
        : d.file_size || "-";
    }
  }

  class ProgressCellRenderer {
    init(params) {
      this.eGui = document.createElement("div");
      this.eGui.className = "ag-progress-cell";

      this.track = document.createElement("div");
      this.track.className = "ag-progress-track";

      this.bar = document.createElement("div");
      this.bar.className = "ag-progress-bar";

      this.text = document.createElement("span");
      this.text.className = "ag-progress-val";

      this.track.appendChild(this.bar);
      this.eGui.appendChild(this.track);
      this.eGui.appendChild(this.text);
      this.update(params);
    }
    getGui() {
      return this.eGui;
    }
    refresh(params) {
      this.update(params);
      return true;
    }
    update(params) {
      const d = params.data;
      if (!d) return;
      const pct = getDownloadProgress(d);
      this.bar.style.width = `${pct}%`;

      if (pct === 100 || currentTab === "completed") {
        this.bar.className = "ag-progress-bar is-complete";
        this.text.className = "ag-progress-val is-complete";
        this.text.textContent = "100% ✓";
      } else {
        this.bar.className = "ag-progress-bar";
        this.text.className = "ag-progress-val";
        this.text.textContent = `${pct}%`;
      }
    }
  }

  class SpeedGraphCellRenderer {
    init(params) {
      this.params = params;
      this.eGui = document.createElement("div");
      this.eGui.className = "ag-speed-graph-cell";

      this.textContainer = document.createElement("div");
      this.textContainer.className = "ag-speed-text-container";

      this.speedLabel = document.createElement("span");
      this.speedLabel.className = "ag-speed-label";

      this.etaLabel = document.createElement("span");
      this.etaLabel.className = "ag-speed-eta";

      this.textContainer.appendChild(this.speedLabel);
      this.textContainer.appendChild(this.etaLabel);

      // SVG Sparkline container
      this.svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      this.svg.setAttribute("class", "ag-sparkline-svg");
      this.svg.setAttribute("viewBox", "0 0 46 18");
      this.svg.setAttribute("preserveAspectRatio", "none");
      this.svg.setAttribute("aria-hidden", "true");

      this.pathArea = document.createElementNS("http://www.w3.org/2000/svg", "path");
      this.pathArea.setAttribute("class", "ag-sparkline-area");

      this.pathLine = document.createElementNS("http://www.w3.org/2000/svg", "path");
      this.pathLine.setAttribute("class", "ag-sparkline-line");

      this.svg.appendChild(this.pathArea);
      this.svg.appendChild(this.pathLine);

      this.eGui.appendChild(this.textContainer);
      this.eGui.appendChild(this.svg);

      this.update(params);
    }
    getGui() {
      return this.eGui;
    }
    refresh(params) {
      this.params = params;
      this.update(params);
      return true;
    }
    update(params) {
      const d = params.data;
      if (!d) return;

      const st = (d.status || "").toLowerCase();
      const isProxy = !!d.use_proxy;
      recordSpeed(d);

      const history = speedHistories.get(d.id) || [];
      const spark = generateSparkline(history, 46, 18);

      this.pathArea.setAttribute("d", spark.area);
      this.pathLine.setAttribute("d", spark.line);

      if (isProxy) {
        this.svg.classList.add("is-proxy");
      } else {
        this.svg.classList.remove("is-proxy");
      }

      const spd = d.download_speed || 0;
      if (spd > 0 && (st === "downloading" || st === "proxying")) {
        this.speedLabel.className = `ag-speed-label ${isProxy ? "proxy-speed" : "local-speed"}`;
        this.speedLabel.textContent = formatSpeed(spd);
        this.svg.style.opacity = "1";
        this.svg.style.display = "block";
        this.eGui.style.justifyContent = "space-between";

        const remBytes = (d.total_size && d.downloaded_size)
          ? Math.max(0, d.total_size - d.downloaded_size)
          : 0;
        if (remBytes > 0) {
          const etaSec = remBytes / spd;
          const etaStr = formatEta(etaSec);
          this.etaLabel.textContent = etaStr;
          this.etaLabel.style.display = etaStr ? "inline" : "none";
          this.eGui.title = `${formatSpeed(spd)} · ETA: ${etaStr || "-"}`;
        } else {
          this.etaLabel.textContent = "";
          this.etaLabel.style.display = "none";
          this.eGui.title = formatSpeed(spd);
        }
      } else if (["parsing", "downloading", "proxying", "pending", "waiting"].includes(st)) {
        this.speedLabel.className = `ag-speed-label parsing-dots ${isProxy ? "proxy-loading" : "local-loading"}`;
        this.speedLabel.textContent = "•••";
        this.etaLabel.textContent = "";
        this.etaLabel.style.display = "none";
        this.svg.style.display = "none";
        this.eGui.style.justifyContent = "center";
        this.eGui.title = $t("download_" + st) || st;
      } else {
        this.speedLabel.className = "ag-speed-label is-empty";
        this.speedLabel.textContent = "-";
        this.etaLabel.textContent = "";
        this.etaLabel.style.display = "none";
        this.svg.style.display = "none";
        this.eGui.style.justifyContent = "center";
        this.eGui.title = "";
      }
    }
  }

  class DateCellRenderer {
    init(params) {
      this.eGui = document.createElement("span");
      this.eGui.className = "ag-date-text";
      this.update(params);
    }
    getGui() {
      return this.eGui;
    }
    refresh(params) {
      this.update(params);
      return true;
    }
    update(params) {
      const d = params.data;
      if (!d) return;
      this.eGui.textContent = formatDate(d.created_at);
      this.eGui.title = formatFullDateTime(d.created_at);
    }
  }

  class ProxyCellRenderer {
    init(params) {
      this.params = params;
      this.eGui = document.createElement("div");
      this.eGui.className = "ag-proxy-toggle-wrap";

      this.btn = document.createElement("button");
      this.btn.type = "button";
      this.btn.className = "grid-proxy-toggle ag-grid-proxy-toggle";

      const slider = document.createElement("div");
      slider.className = "grid-toggle-slider";
      const icons = document.createElement("div");
      icons.className = "grid-toggle-icons";

      this.btn.appendChild(slider);
      this.btn.appendChild(icons);

      this.btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (this.params.data) {
          dispatch("proxyToggle", { download: this.params.data });
        }
      });

      this.eGui.appendChild(this.btn);
      this.update(params);
    }
    getGui() {
      return this.eGui;
    }
    refresh(params) {
      this.params = params;
      this.update(params);
      return true;
    }
    update(params) {
      const d = params.data;
      if (!d) return;
      const isProxy = !!d.use_proxy;
      this.btn.className = `grid-proxy-toggle ag-grid-proxy-toggle ${
        isProxy ? "proxy" : "local"
      }`;
      const modeLabel = isProxy ? $t("proxy_mode") : $t("local_mode");
      this.btn.title = modeLabel;
      this.btn.setAttribute("aria-label", modeLabel);
      this.btn.setAttribute("role", "switch");
      this.btn.setAttribute("aria-checked", String(isProxy));
    }
  }

  class ActionsCellRenderer {
    init(params) {
      this.params = params;
      this.eGui = document.createElement("div");
      this.eGui.className = "ag-actions-cell";
      this.update(params);
    }
    getGui() {
      return this.eGui;
    }
    refresh(params) {
      this.params = params;
      this.update(params);
      return true;
    }
    makeBtn(iconSvg, title, onClick, extraClass = "", disabled = false) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `button-icon ag-btn-icon ${extraClass}`.trim();
      btn.title = title;
      btn.setAttribute("aria-label", title);
      btn.innerHTML = iconSvg;
      if (disabled) {
        // Genuine disabled (D-40): removes the control from the tab order
        // instead of leaving a focusable no-op behind.
        btn.disabled = true;
      } else {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          onClick();
        });
      }
      return btn;
    }
    update(params) {
      const d = params.data;
      if (!d) return;
      this.eGui.innerHTML = "";

      const playSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>`;
      const stopSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="1" ry="1"></rect></svg>`;
      const retrySvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>`;
      const copySvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>`;
      const infoSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`;
      const deleteSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>`;
      const skullSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 10.5a8 8 0 0 1 16 0v2.7a2 2 0 0 1-1.4 1.9l-1.6.5V19a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1v-3.4l-1.6-.5A2 2 0 0 1 4 13.2Z"></path><circle cx="9" cy="11" r="1.7" fill="currentColor" stroke="none"></circle><circle cx="15" cy="11" r="1.7" fill="currentColor" stroke="none"></circle><path d="M12 14.2v1.6"></path></svg>`;

      if (currentTab === "completed") {
        this.eGui.appendChild(
          this.makeBtn(retrySvg, $t("redownload"), () =>
            dispatch("redownload", { download: d })
          )
        );
      } else {
        const st = (d.status || "").toLowerCase();
        if (
          st === "failed" &&
          d.next_retry_at &&
          new Date(d.next_retry_at).getTime() > currentTime
        ) {
          this.eGui.appendChild(
            this.makeBtn(stopSvg, $t("action_cancel_retry"), () =>
              dispatch("stop", { id: d.id })
            )
          );
        } else if (
          ["downloading", "proxying", "pending", "parsing", "waiting"].includes(st)
        ) {
          this.eGui.appendChild(
            this.makeBtn(stopSvg, $t("action_pause"), () =>
              dispatch("stop", { id: d.id })
            )
          );
        } else if (["stopped"].includes(st)) {
          this.eGui.appendChild(
            this.makeBtn(
              playSvg,
              d.progress > 0 ? $t("action_resume") : $t("action_start"),
              () => dispatch("start", { id: d.id })
            )
          );
        }

        if (st === "failed") {
          if (d.failure_kind === "dead" || d.failure_kind === "unknown_terminal") {
            this.eGui.appendChild(
              this.makeBtn(
                d.failure_kind === "dead" ? skullSvg : retrySvg,
                $t("retry_blocked_dead"),
                () => {},
                "is-disabled",
                true
              )
            );
          } else if (d.failure_kind === "auth_required") {
            this.eGui.appendChild(
              this.makeBtn(
                retrySvg,
                $t("retry_blocked_auth_required"),
                () => dispatch("retry", { id: d.id }),
                "is-warn"
              )
            );
          } else {
            this.eGui.appendChild(
              this.makeBtn(
                retrySvg,
                d.failure_kind ? $t("kind_" + d.failure_kind) : $t("action_retry"),
                () => dispatch("retry", { id: d.id })
              )
            );
          }
        }
      }

      this.eGui.appendChild(
        this.makeBtn(copySvg, $t("copy_download_link"), () =>
          dispatch("copyLink", { download: d })
        )
      );
      this.eGui.appendChild(
        this.makeBtn(infoSvg, $t("action_details"), () =>
          openDetails(d)
        )
      );
      this.eGui.appendChild(
        this.makeBtn(
          deleteSvg,
          $t("action_delete"),
          () => dispatch("delete", { id: d.id }),
          "is-delete"
        )
      );
    }
  }

  function isMobileView() {
    return typeof window !== "undefined" && window.innerWidth < 640;
  }

  function createColumnDefs() {
    const mobile = isMobileView();
    return [
      {
        colId: "select",
        headerComponent: SelectHeaderRenderer,
        cellRenderer: SelectCellRenderer,
        width: 44,
        minWidth: 44,
        maxWidth: 50,
        sortable: false,
        resizable: false,
        suppressMovable: true,
        cellClass: "ag-cell-center"
      },
      {
        colId: "filename",
        headerName: $t("table_header_file_name"),
        field: "filename",
        cellRenderer: FilenameCellRenderer,
        minWidth: mobile ? 180 : 240,
        flex: 1,
        sortable: true,
        resizable: true,
        cellClass: "ag-cell-filename",
        comparator: (valA, valB, nodeA, nodeB) => {
          const a = nodeA.data?.filename || "";
          const b = nodeB.data?.filename || "";
          return a.localeCompare(b);
        }
      },
      {
        colId: "status",
        headerName: $t("table_header_status"),
        field: "status",
        cellRenderer: StatusCellRenderer,
        width: 140,
        minWidth: 125,
        sortable: true,
        resizable: true,
        cellClass: "ag-cell-center"
      },
      {
        colId: "size",
        headerName: $t("table_header_size"),
        field: "total_size",
        cellRenderer: SizeCellRenderer,
        width: 85,
        minWidth: 75,
        sortable: true,
        resizable: true,
        cellClass: "ag-cell-center",
        comparator: (a, b, nodeA, nodeB) => {
          const szA = nodeA.data?.total_size || 0;
          const szB = nodeB.data?.total_size || 0;
          return szA - szB;
        }
      },
      {
        colId: "progress",
        headerName: $t("table_header_progress"),
        field: "progress",
        cellRenderer: ProgressCellRenderer,
        width: 135,
        minWidth: 115,
        sortable: true,
        resizable: true,
        cellClass: "ag-cell-center",
        comparator: (a, b, nodeA, nodeB) => {
          const pA = getDownloadProgress(nodeA.data);
          const pB = getDownloadProgress(nodeB.data);
          return pA - pB;
        }
      },
      {
        colId: "speed_graph",
        headerName: $t("table_header_speed"),
        field: "download_speed",
        cellRenderer: SpeedGraphCellRenderer,
        width: 145,
        minWidth: 125,
        hide: currentTab === "completed",
        sortable: true,
        resizable: true,
        cellClass: "ag-cell-center",
        comparator: (a, b, nodeA, nodeB) => {
          const sA = nodeA.data?.download_speed || 0;
          const sB = nodeB.data?.download_speed || 0;
          return sA - sB;
        }
      },
      {
        colId: "created_at",
        headerName: $t("table_header_requested_date"),
        field: "created_at",
        cellRenderer: DateCellRenderer,
        width: 85,
        minWidth: 75,
        sortable: true,
        resizable: true,
        cellClass: "ag-cell-center",
        comparator: (a, b) => {
          const tA = a ? new Date(a).getTime() : 0;
          const tB = b ? new Date(b).getTime() : 0;
          return tA - tB;
        }
      },
      {
        colId: "use_proxy",
        headerName: $t("table_header_proxy"),
        field: "use_proxy",
        cellRenderer: ProxyCellRenderer,
        width: 70,
        minWidth: 60,
        sortable: true,
        resizable: false,
        cellClass: "ag-cell-center"
      },
      {
        colId: "actions",
        headerName: $t("table_header_actions"),
        cellRenderer: ActionsCellRenderer,
        width: mobile ? 128 : 140,
        minWidth: mobile ? 128 : 140,
        sortable: false,
        resizable: false,
        suppressMovable: true,
        cellClass: "ag-cell-center ag-actions-wrapper"
      }
    ];
  }

  function initGrid() {
    if (!gridContainer) return;

    const gridOptions = {
      theme: "legacy",
      columnDefs: createColumnDefs(),
      rowData: downloads,
      getRowId: (params) => String(params.data?.id),
      rowHeight: GRID_ROW_HEIGHT,
      headerHeight: GRID_HEADER_HEIGHT,
      enableCellTextSelection: true,
      animateRows: false,
      domLayout: "normal",
      suppressRowClickSelection: true,
      overlayNoRowsTemplate: `<div class="ag-empty-overlay-msg no-downloads-message">${
        currentTab === "working"
          ? $t("no_working_downloads")
          : $t("no_completed_downloads")
      }</div>`,
      overlayLoadingTemplate: `<span class="ag-loading-msg">${$t("loading")}</span>`
    };

    gridApi = createGrid(gridContainer, gridOptions);
  }

  let resizeObserver = null;
  let prevIsMobile = false;

  function cleanupSpeedHistories(items) {
    if (!items || !Array.isArray(items)) return;
    const ids = new Set(items.map((d) => d.id));
    for (const k of speedHistories.keys()) {
      if (!ids.has(k)) {
        speedHistories.delete(k);
      }
    }
  }

  onMount(() => {
    prevIsMobile = isMobileView();
    initGrid();
    if (gridContainer && typeof window !== "undefined" && window.ResizeObserver) {
      resizeObserver = new ResizeObserver(() => {
        if (gridApi) {
          const curMobile = isMobileView();
          if (curMobile !== prevIsMobile) {
            prevIsMobile = curMobile;
            gridApi.setGridOption("columnDefs", createColumnDefs());
          }
        }
      });
      resizeObserver.observe(gridContainer);
    }
  });

  onDestroy(() => {
    if (resizeObserver) {
      resizeObserver.disconnect();
      resizeObserver = null;
    }
    if (gridApi) {
      gridApi.destroy();
      gridApi = null;
    }
  });

  // Reactivity: update row data when downloads change
  $: if (gridApi && downloads) {
    cleanupSpeedHistories(downloads);
    gridApi.setGridOption("rowData", downloads);
    gridApi.refreshCells({ force: true });
    gridApi.refreshHeader();
  }

  // Reactivity: update column visibility or overlay message when tab or locale changes
  $: if (gridApi && (currentTab || $t)) {
    const isCompleted = currentTab === "completed";
    gridApi.setColumnsVisible(["speed_graph"], !isCompleted);
    const msg = isCompleted
      ? $t("no_completed_downloads")
      : $t("no_working_downloads");
    gridApi.setGridOption(
      "overlayNoRowsTemplate",
      `<div class="ag-empty-overlay-msg no-downloads-message">${msg}</div>`
    );
  }

  // Reactivity: loading vs empty vs data. Loading uses the supported `loading`
  // grid option (the imperative overlay calls are deprecated since v32); the
  // no-rows overlay appears automatically for empty rowData, and a fetch
  // failure renders the distinct error panel instead (D-02).
  $: if (gridApi) {
    gridApi.setGridOption("loading", !!isDownloadsLoading);
  }

  // Reactivity: update check/indeterminate on selection changes
  $: if (gridApi && selectedIds) {
    gridApi.refreshCells({ columns: ["select"], force: true });
    gridApi.refreshHeader();
  }

  // Reactivity: update wait timers and retry countdowns
  $: if (gridApi && (currentTime || downloadWaitInfo)) {
    gridApi.refreshCells({ columns: ["status", "speed_graph"], force: true });
  }

  // Dynamic height (DESIGN.md 4.2/4.3): one authority, using the same row and
  // header heights the grid renders. Grows with the page up to the cap so no
  // fetched row hides behind an unexpected internal scrollbar.
  $: computedGridHeight = (() => {
    const isMob = isMobileView();
    const minH = isMob ? 350 : 400;
    const maxH = isMob ? 500 : 800;
    const count = downloads ? downloads.length : 0;
    if (count === 0) return minH;
    const needed = GRID_HEADER_HEIGHT + count * GRID_ROW_HEIGHT;
    return Math.min(maxH, Math.max(minH, needed));
  })();
</script>

<div
  class="ag-grid-wrapper ag-theme-quartz {$theme === 'light'
    ? ''
    : 'ag-theme-quartz-dark'}"
  class:empty-downloads={downloads.length === 0}
>
  <div class="ag-grid-area">
    <div
      bind:this={gridContainer}
      class="ag-grid-inner"
      style="height: {computedGridHeight}px;"
    ></div>

    {#if gridError}
      <!-- Distinct fetch-failure state (D-02): never collapses into the
           "no downloads" empty overlay. Retry rides the existing fetch path. -->
      <div class="grid-error-overlay" role="alert">
        <div class="grid-error-panel">
          <span class="grid-error-title">{$t("settings_save_error_server")}</span>
          <button
            type="button"
            class="button button-secondary grid-error-retry"
            on:click={() => dispatch("retryFetch")}
          >
            {$t("action_retry")}
          </button>
        </div>
      </div>
    {/if}
  </div>

  <!-- Integrated pagination footer seamlessly merged into the grid -->
  <div class="pagination-footer">
    <div class="page-info">
      {#if totalPages > 1}
        <div>{$t("pagination_page_info", { currentPage, totalPages })}</div>
      {/if}
      <div class="items-info">
        {#if totalCount > 0}
          {$t("pagination_items_info", {
            total: totalCount,
            start: (currentPage - 1) * itemsPerPage + 1,
            end: Math.min(currentPage * itemsPerPage, totalCount)
          })}
        {/if}
      </div>
    </div>
    {#if totalPages > 1}
      <div class="pagination-buttons">
        <!-- Smart pagination for desktop -->
        <div class="pagination-desktop">
          <button
            type="button"
            class="page-number-btn prev-next-btn"
            aria-label={$t("pagination_prev")}
            title={$t("pagination_prev")}
            on:click={() => dispatch("pageChange", { page: currentPage - 1 })}
            disabled={currentPage <= 1}
          >
            <ChevronLeftIcon />
          </button>

          {#if totalPages <= 7}
            {#each Array(totalPages) as _, i}
              {@const pageNum = i + 1}
              <button
                type="button"
                class="page-number-btn"
                class:active={currentPage === pageNum}
                aria-current={currentPage === pageNum ? "page" : undefined}
                on:click={() => dispatch("pageChange", { page: pageNum })}
              >
                {pageNum}
              </button>
            {/each}
          {:else if currentPage <= 4}
            {#each [1, 2, 3, 4, 5] as pageNum}
              <button
                type="button"
                class="page-number-btn"
                class:active={currentPage === pageNum}
                aria-current={currentPage === pageNum ? "page" : undefined}
                on:click={() => dispatch("pageChange", { page: pageNum })}
              >
                {pageNum}
              </button>
            {/each}
            <span class="page-dots">...</span>
            <button
              type="button"
              class="page-number-btn"
              on:click={() => dispatch("pageChange", { page: totalPages })}
            >
              {totalPages}
            </button>
          {:else if currentPage >= totalPages - 3}
            <button
              type="button"
              class="page-number-btn"
              on:click={() => dispatch("pageChange", { page: 1 })}
            >
              1
            </button>
            <span class="page-dots">...</span>
            {#each [totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages] as pageNum}
              <button
                type="button"
                class="page-number-btn"
                class:active={currentPage === pageNum}
                aria-current={currentPage === pageNum ? "page" : undefined}
                on:click={() => dispatch("pageChange", { page: pageNum })}
              >
                {pageNum}
              </button>
            {/each}
          {:else}
            <button
              type="button"
              class="page-number-btn"
              on:click={() => dispatch("pageChange", { page: 1 })}
            >
              1
            </button>
            <span class="page-dots">...</span>
            {#each [currentPage - 2, currentPage - 1, currentPage, currentPage + 1, currentPage + 2] as pageNum}
              <button
                type="button"
                class="page-number-btn"
                class:active={currentPage === pageNum}
                aria-current={currentPage === pageNum ? "page" : undefined}
                on:click={() => dispatch("pageChange", { page: pageNum })}
              >
                {pageNum}
              </button>
            {/each}
            <span class="page-dots">...</span>
            <button
              type="button"
              class="page-number-btn"
              on:click={() => dispatch("pageChange", { page: totalPages })}
            >
              {totalPages}
            </button>
          {/if}

          <button
            type="button"
            class="page-number-btn prev-next-btn"
            aria-label={$t("pagination_next")}
            title={$t("pagination_next")}
            on:click={() => dispatch("pageChange", { page: currentPage + 1 })}
            disabled={currentPage >= totalPages}
          >
            <ChevronRightIcon />
          </button>
        </div>

        <!-- Smart pagination for mobile -->
        <div class="pagination-mobile">
          <div class="page-nav-container">
            <button
              type="button"
              class="page-nav-btn prev-btn"
              on:click={() => dispatch("pageChange", { page: currentPage - 1 })}
              disabled={currentPage <= 1}
            >
              <ChevronLeftIcon />
              {$t("pagination_prev")}
            </button>
            <button
              type="button"
              class="page-nav-btn next-btn"
              on:click={() => dispatch("pageChange", { page: currentPage + 1 })}
              disabled={currentPage >= totalPages}
            >
              {$t("pagination_next")}
              <ChevronRightIcon />
            </button>
          </div>

          <div class="page-numbers-mobile">
            {#if totalPages <= 7}
              {#each Array(totalPages) as _, i}
                {@const pageNum = i + 1}
                <button
                  type="button"
                  class="page-number-btn-mobile"
                  class:active={currentPage === pageNum}
                  aria-current={currentPage === pageNum ? "page" : undefined}
                  on:click={() => dispatch("pageChange", { page: pageNum })}
                >
                  {pageNum}
                </button>
              {/each}
            {:else if currentPage <= 4}
              {#each [1, 2, 3, 4, 5] as pageNum}
                <button
                  type="button"
                  class="page-number-btn-mobile"
                  class:active={currentPage === pageNum}
                  aria-current={currentPage === pageNum ? "page" : undefined}
                  on:click={() => dispatch("pageChange", { page: pageNum })}
                >
                  {pageNum}
                </button>
              {/each}
              <span class="page-dots-mobile">...</span>
              <button
                type="button"
                class="page-number-btn-mobile"
                on:click={() => dispatch("pageChange", { page: totalPages })}
              >
                {totalPages}
              </button>
            {:else if currentPage >= totalPages - 3}
              <button
                type="button"
                class="page-number-btn-mobile"
                on:click={() => dispatch("pageChange", { page: 1 })}
              >
                1
              </button>
              <span class="page-dots-mobile">...</span>
              {#each [totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1, totalPages] as pageNum}
                <button
                  type="button"
                  class="page-number-btn-mobile"
                  class:active={currentPage === pageNum}
                  aria-current={currentPage === pageNum ? "page" : undefined}
                  on:click={() => dispatch("pageChange", { page: pageNum })}
                >
                  {pageNum}
                </button>
              {/each}
            {:else}
              <button
                type="button"
                class="page-number-btn-mobile"
                on:click={() => dispatch("pageChange", { page: 1 })}
              >
                1
              </button>
              <span class="page-dots-mobile">...</span>
              {#each [currentPage - 2, currentPage - 1, currentPage, currentPage + 1, currentPage + 2] as pageNum}
                <button
                  type="button"
                  class="page-number-btn-mobile"
                  class:active={currentPage === pageNum}
                  aria-current={currentPage === pageNum ? "page" : undefined}
                  on:click={() => dispatch("pageChange", { page: pageNum })}
                >
                  {pageNum}
                </button>
              {/each}
              <span class="page-dots-mobile">...</span>
              <button
                type="button"
                class="page-number-btn-mobile"
                on:click={() => dispatch("pageChange", { page: totalPages })}
              >
                {totalPages}
              </button>
            {/if}
          </div>
        </div>
      </div>
    {/if}
  </div>
</div>

<style>
  .ag-grid-wrapper {
    position: relative;
    width: 100%;
    border: 1px solid var(--card-border);
    border-radius: 8px;
    background-color: var(--card-background);
    box-shadow: var(--shadow-light);
    overflow: hidden;
    margin-bottom: 0.5rem;
    transition: background-color 0.3s ease, border-color 0.3s ease;
    display: flex;
    flex-direction: column;
  }

  .ag-grid-area {
    position: relative;
    display: flex;
    flex-direction: column;
  }

  .ag-grid-inner {
    width: 100%;
    flex: 1 1 auto;
  }

  /* Distinct fetch-failure surface (D-02): danger-tinted, covers the grid
     viewport so the automatic no-rows overlay cannot read as "no downloads". */
  .grid-error-overlay {
    position: absolute;
    inset: 0;
    z-index: 2;
    display: flex;
    align-items: center;
    justify-content: center;
    background-color: var(--card-background);
  }

  .grid-error-panel {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
    padding: 1rem 1.25rem;
    border: 1px solid var(--status-failed-border);
    border-radius: 8px;
    background-color: var(--status-failed-bg);
  }

  .grid-error-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--status-failed-text);
  }

  .grid-error-retry:focus-visible {
    box-shadow: 0 0 0 3px
      color-mix(in srgb, var(--primary-color) 35%, transparent);
  }

  .pagination-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.3rem 0.8rem;
    min-height: 48px;
    background-color: var(--card-background);
    border-top: 1px solid var(--card-border);
    margin: 0;
    gap: 0.75rem;
    box-sizing: border-box;
    font-size: 14px;
  }

  /* ---- Custom AG-Grid Overrides to Match Theme Variables ---- */
  :global(.ag-theme-quartz),
  :global(.ag-theme-quartz-dark) {
    --ag-font-family: var(--font-sans);
    --ag-font-size: 14px;
    --ag-grid-size: 4px;
    --ag-row-height: 44px;
    --ag-header-height: 40px;
    --ag-background-color: var(--card-background);
    --ag-foreground-color: var(--text-primary);
    --ag-secondary-foreground-color: var(--text-secondary);
    --ag-header-background-color: var(--card-background);
    --ag-header-foreground-color: var(--text-secondary);
    --ag-border-color: var(--card-border);
    --ag-row-border-color: var(--card-border);
    --ag-odd-row-background-color: transparent;
    --ag-row-hover-color: rgba(var(--primary-color-rgb), 0.05);
    --ag-selected-row-background-color: rgba(var(--primary-color-rgb), 0.1);
    --ag-range-selection-border-color: var(--primary-color);
    /* AG Grid draws short vertical ticks for resizable headers by default.
       They look like broken column borders because they stop inside the
       header. Keep the resize hit target and cursor, but remove the tick. */
    --ag-header-column-resize-handle-display: none;
  }
  :global(.ag-header-cell[col-id="select"]),
  :global(.ag-cell[col-id="select"]) {
    padding-left: 0 !important;
    padding-right: 0 !important;
  }

  :global(.ag-header-cell[col-id="select"] .ag-header-cell-resize) {
    display: none !important;
  }

  :global(.ag-header-cell[col-id="select"] .ag-header-cell-comp-wrapper) {
    width: 100%;
    height: 100%;
    display: flex;
    justify-content: center;
    align-items: center;
  }
  :global(.ag-header-cell-label) {
    font-weight: 700;
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-secondary);
  }

  :global(.ag-cell) {
    display: flex;
    align-items: center;
    padding-left: 8px;
    padding-right: 8px;
    border-bottom: 1px solid var(--card-border);
  }

  /* Real column dividers: unlike AG Grid's short resize-handle ticks, these
     continue from the header through every row. The outer frame closes the
     final actions column, so it does not need a second overlapping border. */
  :global(.ag-header-cell:not([col-id="actions"])),
  :global(.ag-cell:not([col-id="actions"])) {
    border-right: 1px solid var(--card-border);
  }

  :global(.ag-cell-center) {
    justify-content: center;
  }

  :global(.ag-cell-filename) {
    justify-content: flex-start;
    overflow: hidden;
  }

  /* Filename Cell */
  :global(.ag-filename-cell) {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
    width: 100%;
  }

  /* Keyboard-reachable details trigger (D-35): styled as plain cell text so
     the grid's visual hierarchy is unchanged while focus becomes visible. */
  :global(.ag-filename-button) {
    display: flex;
    align-items: center;
    min-width: 0;
    width: 100%;
    padding: 0;
    border: none;
    background: transparent;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }

  :global(.ag-filename-button:focus-visible) {
    box-shadow: 0 0 0 3px
      color-mix(in srgb, var(--primary-color) 35%, transparent);
    border-radius: 4px;
  }

  :global(.ag-filename-text) {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
  }

  :global(.ag-filename-button:hover .ag-filename-text) {
    color: var(--primary-color);
  }

  /* Custom Checkbox */
  :global(.ag-custom-checkbox-wrap) {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    width: 100%;
  }
  :global(.ag-custom-checkbox) {
    -webkit-appearance: none;
    appearance: none;
    width: 16px;
    height: 16px;
    border: 1.5px solid var(--card-border);
    border-radius: 4px;
    background: transparent;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;
    position: relative;
    outline: none;
    margin: 0;
  }
  /* 24px hit area with the 16px visual unchanged (D-34 grid instance). */
  :global(.ag-custom-checkbox)::before {
    content: "";
    position: absolute;
    inset: -4px;
  }
  /* Keyboard focus ring (D-13): AG's base css strips outlines on ag- classes,
     so the ring must be restored explicitly (Checkbox.svelte recipe). */
  :global(.ag-custom-checkbox:focus-visible) {
    box-shadow: 0 0 0 3px
      color-mix(in srgb, var(--primary-color) 35%, transparent);
  }
  :global(.ag-custom-checkbox:hover) {
    border-color: var(--primary-color);
  }
  :global(.ag-custom-checkbox:checked) {
    background-color: var(--primary-color);
    border-color: var(--primary-color);
  }
  :global(.ag-custom-checkbox:checked::after) {
    content: "";
    position: absolute;
    width: 4px;
    height: 8px;
    border: solid #ffffff;
    border-width: 0 2px 2px 0;
    transform: rotate(45deg);
    top: 1px;
    left: 4px;
  }
  :global(.ag-custom-checkbox:indeterminate) {
    background-color: var(--primary-color);
    border-color: var(--primary-color);
  }
  :global(.ag-custom-checkbox:indeterminate::after) {
    content: "";
    position: absolute;
    width: 8px;
    height: 2px;
    background: #ffffff;
    border-radius: 1px;
    top: 5px;
    left: 3px;
  }

  /* Status Cell: Wrapper to center the restored span.status pill */
  :global(.ag-status-cell-wrap) {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
  }

  /* Empty state overlay */
  :global(.ag-empty-overlay-msg) {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-secondary);
    padding: 1.5rem 1rem;
    text-align: center;
  }

  :global(.ag-body-viewport) {
    -webkit-overflow-scrolling: touch;
  }
  :global(.ag-body-horizontal-scroll) {
    height: 10px !important;
    min-height: 10px !important;
  }
  :global(.ag-body-horizontal-scroll-viewport) {
    height: 10px !important;
    min-height: 10px !important;
  }

  /* Size & Date */
  :global(.ag-size-text),
  :global(.ag-date-text) {
    font-size: 14px;
    color: var(--text-secondary);
    font-variant-numeric: tabular-nums;
  }

  /* Modern Progress Bar */
  :global(.ag-progress-cell) {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 0 2px;
  }

  :global(.ag-progress-track) {
    position: relative;
    flex: 1 1 auto;
    height: 6px;
    background: rgba(var(--primary-color-rgb, 71, 75, 223), 0.15);
    border-radius: 3px;
    overflow: hidden;
  }

  :global(.ag-progress-bar) {
    height: 100%;
    background: var(--primary-color);
    border-radius: 3px;
    transition: width 0.15s ease-out;
  }

  :global(.ag-progress-bar.is-complete) {
    background: var(--success-color, #10b981);
  }

  :global(.ag-progress-val) {
    font-size: 14px;
    font-weight: 600;
    min-width: 28px;
    text-align: right;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
    flex-shrink: 0;
  }

  /* Text-safe green (D-18 migration-on-touch): the done-status ink token is
     the per-theme contrast workaround; the raw success hue fails in light. */
  :global(.ag-progress-val.is-complete) {
    color: var(--status-done-text);
    font-weight: 700;
  }

  /* Speed & Sparkline Graph Cell */
  :global(.ag-speed-graph-cell) {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    gap: 6px;
  }

  :global(.ag-speed-text-container) {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    line-height: 1.15;
    min-width: 0;
  }

  :global(.ag-speed-label) {
    font-size: 14px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  :global(.ag-speed-eta) {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-secondary);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    opacity: 0.85;
  }

  :global(.ag-speed-label.proxy-speed) {
    color: var(--warning-color);
  }
  :global(.ag-speed-label.local-speed) {
    color: var(--primary-color);
  }
  :global(.ag-speed-label.is-empty) {
    color: var(--text-secondary);
  }

  :global(.ag-sparkline-svg) {
    width: 44px;
    height: 18px;
    flex-shrink: 0;
  }

  :global(.ag-sparkline-area) {
    fill: rgba(var(--primary-color-rgb), 0.18);
  }
  :global(.ag-sparkline-line) {
    fill: none;
    stroke: var(--primary-color);
    stroke-width: 1.5;
    stroke-linejoin: round;
    stroke-linecap: round;
  }

  :global(.ag-sparkline-svg.is-proxy .ag-sparkline-area) {
    fill: rgba(245, 158, 11, 0.18);
  }
  :global(.ag-sparkline-svg.is-proxy .ag-sparkline-line) {
    stroke: var(--warning-color, #f59e0b);
  }

  /* Proxy Toggle Button */
  :global(.ag-proxy-toggle-wrap) {
    display: flex;
    align-items: center;
    justify-content: center;
  }

  :global(.ag-grid-proxy-toggle) {
    width: 44px;
    height: 22px;
  }

  /* Keyboard focus ring (D-13): same recipe as the header switch in app.css. */
  :global(.ag-grid-proxy-toggle:focus-visible) {
    box-shadow: 0 0 0 3px
      color-mix(in srgb, var(--primary-color) 35%, transparent);
  }

  /* Action Buttons Toolbar */
  :global(.ag-actions-wrapper) {
    justify-content: center;
  }

  :global(.ag-actions-cell) {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    min-width: 0;
    gap: 4px;
    flex-wrap: nowrap;
  }
  /* Remove default grid padding for actions to save space */
  :global(.ag-actions-wrapper) {
    padding-left: 4px !important;
    padding-right: 4px !important;
  }

  :global(.ag-btn-icon) {
    width: 28px;
    height: 28px;
    min-width: 28px;
    flex-shrink: 0;
    padding: 4px;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: transparent;
    border: none;
    color: var(--text-secondary);
    cursor: pointer;
    transition: background-color 0.2s ease, color 0.2s ease, transform 0.1s ease;
  }

  :global(.ag-btn-icon:focus-visible) {
    box-shadow: 0 0 0 3px
      color-mix(in srgb, var(--primary-color) 35%, transparent);
  }

  :global(.ag-btn-icon:hover:not(:disabled)) {
    background: rgba(var(--primary-color-rgb), 0.1);
    color: var(--primary-color);
    transform: scale(1.08);
  }

  :global(.ag-btn-icon.is-delete:hover:not(:disabled)) {
    background: rgba(220, 38, 38, 0.12);
    color: var(--danger-color, #dc2626);
  }

  :global(.ag-btn-icon:disabled) {
    opacity: 0.35;
    cursor: not-allowed;
    transform: none;
  }

  :global(.ag-btn-icon.is-warn) {
    color: var(--warning-color);
  }

  /* Mobile Responsiveness for Grid & Pagination */
  @media (max-width: 640px) {
    /* A row can have four actions. 48px targets made even three buttons wider
       than the action column and visibly spill into the next cell. Keep the
       compact icon toolbar inside its 128px grid column. */
    :global(.ag-actions-cell) {
      gap: 2px;
    }

    :global(.ag-btn-icon) {
      width: 28px;
      height: 28px;
      min-width: 28px;
      padding: 4px;
      border-radius: 6px;
    }
    .pagination-footer {
      flex-direction: column;
      gap: 0.6rem;
      padding: 0.75rem 0.6rem;
      align-items: center;
    }
    :global(.pagination-desktop) {
      display: none !important;
    }
    :global(.pagination-mobile) {
      display: flex !important;
      flex-direction: column;
      gap: 0.5rem;
      width: 100%;
      align-items: center;
    }
    :global(.page-nav-container) {
      display: flex;
      width: 100%;
      max-width: 280px;
      gap: 0.5rem;
      justify-content: center;
      order: 2;
    }
    :global(.page-numbers-mobile) {
      display: flex;
      align-items: center;
      gap: 0.25rem;
      justify-content: center;
      flex-wrap: wrap;
      order: 1;
    }
    :global(.page-nav-btn) {
      display: flex;
      align-items: center;
      justify-content: center;
      flex: 1;
      height: 40px;
      border: 1px solid var(--card-border);
      background: var(--card-background);
      color: var(--text-primary);
      border-radius: 6px;
      cursor: pointer;
      font-size: 14px;
      font-weight: 500;
      gap: 0.35rem;
      transition: background-color 0.2s ease, border-color 0.2s ease;
    }
    :global(.page-nav-btn:hover:not(:disabled)) {
      background: var(--bg-secondary);
      border-color: var(--primary-color);
    }
    :global(.page-nav-btn:disabled) {
      opacity: 0.4;
      cursor: not-allowed;
    }
    :global(.page-number-btn-mobile) {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border: 1px solid var(--card-border);
      background: var(--input-inner-bg, var(--card-background));
      color: var(--text-primary);
      border-radius: 6px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    :global(.page-number-btn-mobile.active) {
      background: var(--primary-color);
      color: #fff;
      border-color: var(--primary-color);
    }
    :global(.page-dots-mobile) {
      color: var(--text-secondary);
      padding: 0 0.15rem;
      font-weight: 600;
    }

    :global(.ag-custom-checkbox) {
      width: 18px;
      height: 18px;
    }
  }
</style>
