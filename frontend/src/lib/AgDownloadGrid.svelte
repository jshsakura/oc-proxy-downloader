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

  ModuleRegistry.registerModules([AllCommunityModule]);

  export let downloads = [];
  export let currentTab = "working"; // "working" | "completed"
  export let selectedIds = new Set();
  export let auditingIds = new Set();
  export let downloadWaitInfo = {};
  export let downloadProxyInfo = {};
  export let currentTime = Date.now();
  export let isDownloadsLoading = false;

  const dispatch = createEventDispatcher();

  let gridContainer;
  let gridApi = null;

  // Speed history buffer per download ID: maps id -> number[] (up to 16 points)
  const speedHistories = new Map();

  function getHosterSlug(url) {
    if (!url) return "";
    try {
      const parsed = new URL(url);
      const host = parsed.hostname.toLowerCase().replace(/^www\./, "");
      if (host.includes("1fichier")) return "1fichier";
      if (host.includes("mega.nz") || host.includes("mega.co.nz")) return "mega";
      if (host.includes("datanodes")) return "datanodes";
      if (host.includes("megaup")) return "megaup";
      if (host.includes("send.now")) return "sendnow";
      if (host.includes("gofile")) return "gofile";
      if (host.includes("mediafire")) return "mediafire";
      if (host.includes("pixeldrain")) return "pixeldrain";
      if (host.includes("bunkr")) return "bunkr";
      return "";
    } catch {
      return "";
    }
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
      this.checkbox.setAttribute("aria-label", "Select all visible");

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
    }
    getGui() {
      return this.eGui;
    }
    refresh(params) {
      this.params = params;
      this.checkbox.checked = selectedIds.has(params.data?.id);
      return true;
    }
  }

  class FilenameCellRenderer {
    init(params) {
      this.params = params;
      this.eGui = document.createElement("div");
      this.eGui.className = "filename-cell ag-filename-cell";
      this.badgeSpan = document.createElement("span");
      this.nameSpan = document.createElement("span");
      this.nameSpan.className = "filename-text ag-filename-text";

      this.eGui.appendChild(this.badgeSpan);
      this.eGui.appendChild(this.nameSpan);

      this.eGui.addEventListener("click", () => {
        if (this.params.data) {
          dispatch("details", { download: this.params.data });
        }
      });

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

      const hosterSlug = d.hoster_key || getHosterSlug(d.url);
      const hosterLabel = d.hoster || hosterSlug;

      if (hosterLabel) {
        this.badgeSpan.className = `ag-host-badge host-${hosterSlug || "default"}`;
        this.badgeSpan.textContent = hosterLabel;
        this.badgeSpan.style.display = "inline-flex";
      } else {
        this.badgeSpan.style.display = "none";
      }

      this.nameSpan.textContent = getDisplayFileName(d);
      this.eGui.title = d.filename || d.url || "";
    }
  }

  class StatusCellRenderer {
    init(params) {
      this.params = params;
      this.eGui = document.createElement("div");
      this.eGui.className = "ag-status-cell-wrap";
      this.pill = document.createElement("span");
      this.pill.className = "interactive-status ag-status-pill";
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

      this.pill.className = `interactive-status ag-status-pill status-${st} ${
        isProxy ? "proxy-status" : "local-status"
      }`;
      this.pill.title = getStatusTooltip(d);

      if (isAuditing) {
        this.pill.innerHTML = `<span class="row-audit-spinner"></span> <span>${$t("action_audit_running")}</span>`;
      } else if (
        wait &&
        wait.remaining_time > 0 &&
        ["waiting", "parsing", "proxying", "pending"].includes(st)
      ) {
        this.pill.innerHTML = `<span>${$t("download_waiting_time")} (${formatWaitTime(
          wait.remaining_time
        )})</span><span class="wait-indicator wait-indicator-waiting"></span>`;
      } else if (st === "downloading" && !d.progress) {
        this.pill.innerHTML = `<span>${$t("download_downloading")}</span><span class="wait-indicator wait-indicator-downloading"></span>`;
      } else if (st === "failed" && d.failure_kind) {
        if (d.next_retry_at && new Date(d.next_retry_at).getTime() > currentTime) {
          const remSec = (new Date(d.next_retry_at).getTime() - currentTime) / 1000;
          this.pill.innerHTML = `<span>${$t("download_retry_pending")} (${formatWaitTime(
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
        this.pill.innerHTML = `<span>${label}</span>${liveDot}`;
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
        this.svg.style.opacity = "0.3";
        this.eGui.title = $t("download_" + st) || st;
      } else {
        this.speedLabel.className = "ag-speed-label is-empty";
        this.speedLabel.textContent = "-";
        this.etaLabel.textContent = "";
        this.etaLabel.style.display = "none";
        this.svg.style.opacity = "0.15";
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
      this.btn.title = isProxy ? $t("proxy_mode") : $t("local_mode");
      this.btn.setAttribute("aria-label", isProxy ? $t("proxy_mode") : $t("local_mode"));
    }
  }

  class ActionsCellRenderer {
    init(params) {
      this.params = params;
      this.eGui = document.createElement("div");
      this.eGui.className = "actions ag-actions-cell";
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
    makeBtn(iconSvg, title, onClick, extraClass = "") {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `button-icon ag-btn-icon ${extraClass}`.trim();
      btn.title = title;
      btn.setAttribute("aria-label", title);
      btn.innerHTML = iconSvg;
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        onClick();
      });
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
            const btn = this.makeBtn(
              d.failure_kind === "dead" ? skullSvg : retrySvg,
              $t("retry_blocked_dead"),
              () => {},
              "is-disabled"
            );
            btn.setAttribute("aria-disabled", "true");
            this.eGui.appendChild(btn);
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
          dispatch("details", { download: d })
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

  function createColumnDefs() {
    return [
      {
        colId: "select",
        headerComponent: SelectHeaderRenderer,
        cellRenderer: SelectCellRenderer,
        width: 44,
        minWidth: 44,
        maxWidth: 50,
        pinned: "left",
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
        minWidth: 180,
        flex: 2,
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
        width: 125,
        minWidth: 110,
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
        width: 125,
        minWidth: 110,
        pinned: "right",
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
      rowHeight: 38,
      headerHeight: 36,
      suppressCellFocus: true,
      enableCellTextSelection: true,
      animateRows: false,
      domLayout: "autoHeight",
      suppressRowClickSelection: true,
      overlayNoRowsTemplate: `<span class="ag-empty-msg">${
        currentTab === "working"
          ? $t("no_working_downloads")
          : $t("no_completed_downloads")
      }</span>`,
      overlayLoadingTemplate: `<span class="ag-loading-msg">${$t("loading")}</span>`
    };

    gridApi = createGrid(gridContainer, gridOptions);
  }

  let resizeObserver = null;

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
    initGrid();
    if (gridContainer && typeof window !== "undefined" && window.ResizeObserver) {
      resizeObserver = new ResizeObserver(() => {
        if (gridApi) {
          gridApi.sizeColumnsToFit();
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

  // Reactivity: handle loading vs empty vs data overlays
  $: if (gridApi) {
    if (isDownloadsLoading) {
      gridApi.showLoadingOverlay();
    } else if (!downloads || downloads.length === 0) {
      gridApi.showNoRowsOverlay();
    } else {
      gridApi.hideOverlay();
    }
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
</script>

<div
  class="ag-grid-wrapper ag-theme-quartz {$theme === 'light'
    ? ''
    : 'ag-theme-quartz-dark'}"
  class:empty-downloads={downloads.length === 0}
>
  <div bind:this={gridContainer} class="ag-grid-inner"></div>
</div>

<style>
  .ag-grid-wrapper {
    position: relative;
    width: 100%;
    min-height: 120px;
    border: 1px solid var(--card-border);
    border-radius: 10px;
    background-color: var(--card-background);
    box-shadow: var(--shadow-light);
    overflow: hidden;
    margin-bottom: 0.5rem;
    transition: background-color 0.3s ease, border-color 0.3s ease;
  }

  .ag-grid-inner {
    width: 100%;
  }

  /* ---- Custom AG-Grid Overrides to Match Theme Variables ---- */
  :global(.ag-theme-quartz),
  :global(.ag-theme-quartz-dark) {
    --ag-font-family: var(--font-sans);
    --ag-font-size: 0.8125rem;
    --ag-grid-size: 4px;
    --ag-row-height: 38px;
    --ag-header-height: 36px;
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
  }

  :global(.ag-header-cell-label) {
    font-weight: 700;
    font-size: 0.76rem;
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

  :global(.ag-cell-center) {
    justify-content: center;
  }

  :global(.ag-cell-filename) {
    justify-content: flex-start;
    overflow: hidden;
  }

  /* Filename and Host Badges */
  :global(.ag-filename-cell) {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
    width: 100%;
    cursor: pointer;
  }

  :global(.ag-filename-text) {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.825rem;
    font-weight: 500;
    color: var(--text-primary);
  }

  :global(.ag-filename-cell:hover .ag-filename-text) {
    color: var(--primary-color);
  }

  :global(.ag-host-badge) {
    flex-shrink: 0;
    font-size: 0.65rem;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 4px;
    letter-spacing: 0.02em;
    line-height: 1.3;
    border: 1px solid rgba(var(--primary-color-rgb), 0.3);
    background: rgba(var(--primary-color-rgb), 0.1);
    color: var(--primary-color);
  }

  :global(.ag-host-badge.host-1fichier) {
    background: rgba(156, 39, 176, 0.16);
    border-color: #9c27b0;
    color: #ba68c8;
  }
  :global(.ag-host-badge.host-mega) {
    background: rgba(229, 57, 53, 0.16);
    border-color: #e53935;
    color: #ef5350;
  }
  :global(.ag-host-badge.host-datanodes) {
    background: rgba(30, 136, 229, 0.16);
    border-color: #1e88e5;
    color: #42a5f5;
  }
  :global(.ag-host-badge.host-megaup) {
    background: rgba(0, 137, 123, 0.16);
    border-color: #00897b;
    color: #26a69a;
  }
  :global(.ag-host-badge.host-sendnow) {
    background: rgba(245, 124, 0, 0.16);
    border-color: #f57c00;
    color: #ff9800;
  }
  :global(.ag-host-badge.host-gofile) {
    background: rgba(67, 160, 71, 0.16);
    border-color: #43a047;
    color: #66bb6a;
  }
  :global(.ag-host-badge.host-mediafire) {
    background: rgba(3, 155, 229, 0.16);
    border-color: #039be5;
    color: #29b6f6;
  }
  :global(.ag-host-badge.host-pixeldrain) {
    background: rgba(124, 179, 66, 0.16);
    border-color: #7cb342;
    color: #9ccc65;
  }
  :global(.ag-host-badge.host-bunkr) {
    background: rgba(142, 36, 170, 0.16);
    border-color: #8e24aa;
    color: #ab47bc;
  }

  /* Custom Checkbox */
  :global(.ag-custom-checkbox-wrap) {
    display: flex;
    align-items: center;
    justify-content: center;
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

  /* Status Pill */
  :global(.ag-status-cell-wrap) {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
  }

  :global(.ag-status-pill) {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 4px;
    padding: 2px 8px;
    font-size: 0.72rem;
    font-weight: 600;
    border-radius: 12px;
    max-width: 100%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.3;
  }

  /* Size & Date */
  :global(.ag-size-text),
  :global(.ag-date-text) {
    font-size: 0.78rem;
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
    background: linear-gradient(90deg, var(--primary-color), var(--primary-hover));
    border-radius: 3px;
    transition: width 0.3s ease;
  }

  :global(.ag-progress-bar.is-complete) {
    background: var(--success-color, #10b981);
  }

  :global(.ag-progress-val) {
    font-size: 0.74rem;
    font-weight: 600;
    min-width: 32px;
    text-align: right;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
    flex-shrink: 0;
  }

  :global(.ag-progress-val.is-complete) {
    color: var(--success-color, #10b981);
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
    font-size: 0.78rem;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  :global(.ag-speed-eta) {
    font-size: 0.64rem;
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

  /* Action Buttons Toolbar */
  :global(.ag-actions-wrapper) {
    justify-content: center;
  }

  :global(.ag-actions-cell) {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 2px;
  }

  :global(.ag-btn-icon) {
    width: 24px;
    height: 24px;
    padding: 3px;
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

  :global(.ag-btn-icon:hover) {
    background: rgba(var(--primary-color-rgb), 0.1);
    color: var(--primary-color);
    transform: scale(1.08);
  }

  :global(.ag-btn-icon.is-delete:hover) {
    background: rgba(220, 38, 38, 0.12);
    color: var(--danger-color, #dc2626);
  }

  :global(.ag-btn-icon.is-disabled) {
    opacity: 0.35;
    cursor: not-allowed;
  }

  :global(.ag-btn-icon.is-warn) {
    color: var(--warning-color);
  }
</style>
