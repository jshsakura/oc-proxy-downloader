import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * Structural guards on the stylesheet.
 *
 * The grid broke three times in one session and every break was found by a
 * person looking at a screenshot: a filename column that had been inheriting
 * the status column's width since the checkbox column was added, a `<td>` I
 * turned into a flex container (which drops it out of the table layout, so its
 * width stops applying), and a phone layout that forced a "재시도 대기 (0:38)"
 * pill into 54px and let it spill onto its neighbour.
 *
 * None of these need a browser to catch — they are visible in the CSS text.
 */

const read = (rel) =>
  readFileSync(fileURLToPath(new URL(rel, import.meta.url)), "utf8");

const CSS = read("../src/app.css");
const APP = read("../src/App.svelte");
const GRID = read("../src/lib/AgDownloadGrid.svelte");
const DASHBOARD = read("../src/lib/Dashboard.svelte");
const DETAIL = read("../src/lib/DetailModal.svelte");
const SETTINGS = read("../src/lib/SettingsModal.svelte");
const PASSWORD = read("../src/lib/PasswordModal.svelte");
const CONFIRM = read("../src/lib/ConfirmModal.svelte");
const AUDIT = read("../src/lib/AuditModal.svelte");
const AUDIT_PANEL = read("../src/lib/AuditPanel.svelte");
const TREND = read("../src/lib/TrendChart.svelte");
const MODAL_ACTION = read("../src/lib/modal.js");
const THEME = read("../src/lib/theme.js");

describe("stable grid row count", () => {
  it("does not derive page size from viewport height", () => {
    const calculator = APP.slice(
      APP.indexOf("function calculateItemsPerPage"),
      APP.indexOf("function handleResize"),
    );
    expect(calculator).toContain("itemsPerPageForWidth(window.innerWidth)");
    expect(calculator).not.toContain("innerHeight");
  });
});

describe("settings link-audit tab", () => {
  it("removes the duplicate header shortcut and uses the shared audit API", () => {
    expect(APP).not.toContain("audit-button");
    expect(APP).not.toContain("<LinkCopyIcon");
    expect(APP).toContain("bind:activeTab={settingsTab}");
    expect(APP).toContain('on:auditStart={(e) => startAudit(e.detail)}');
    expect(APP).not.toContain("<AuditModal");
  });

  it("renders audit controls as the third settings tab", () => {
    expect(SETTINGS).toContain('activeTab === "audit"');
    expect(SETTINGS).toContain("<AuditPanel");
    expect(AUDIT_PANEL).toContain('dispatch("start", payload)');
  });

  it("keeps the settings shell at a stable height across tabs", () => {
    expect(SETTINGS).toMatch(/\.modern-modal\s*\{[^}]*height:\s*min\(92vh, 700px\)/s);
  });
});

/** The `@media (max-width: 768px)` body — where the phone rules live. */
function mobileBlock(css) {
  const start = css.indexOf("@media (max-width: 768px)");
  expect(start, "the phone breakpoint is gone").toBeGreaterThan(-1);
  let depth = 0;
  for (let i = css.indexOf("{", start); i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}" && --depth === 0) return css.slice(start, i);
  }
  throw new Error("unbalanced braces in the phone block");
}

/** Rule bodies for a selector, with comments stripped so prose cannot match. */
function rulesFor(css, selectorPart) {
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const out = [];
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(bare))) {
    if (m[1].includes(selectorPart)) out.push(m[2]);
  }
  return out;
}

describe("column widths address the columns that exist", () => {
  const gridColCount = (GRID.match(/colId:\s*["'][^"']+["']/g) || []).length;

  it("the header has the nine columns the width rules assume", () => {
    // select, filename, status, size, progress, speed, date, proxy, actions.
    expect(gridColCount).toBe(9);
  });

  it("no width rule points past the last column", () => {
    const indexes = [...CSS.matchAll(/nth-child\((\d+)\)/g)].map((m) => Number(m[1]));

    expect(Math.max(...indexes)).toBeLessThanOrEqual(gridColCount);
  });

  it("column 1 is sized like the checkbox it holds", () => {
    // The whole family of bugs in one assertion. These indexes were written
    // before the select checkbox became the first column and were never
    // shifted, so every column took the width meant for its neighbour and a
    // filename rendered as "Dyn···" on a 1244px screen. Shift them again and
    // column 1 inherits a content-sized width, which a checkbox never needs.
    const widths = rulesFor(CSS, "nth-child(1)")
      .flatMap((body) => [...body.matchAll(/(?:^|[^-])(?:min-|max-)?width:\s*(\d+)px/g)])
      .map((m) => Number(m[1]));

    expect(widths.length, "column 1 has no width rule at all").toBeGreaterThan(0);
    expect(Math.max(...widths)).toBeLessThanOrEqual(60);
  });

  it("the filename column is the one given room to breathe", () => {
    const filenameRules = rulesFor(CSS, "nth-child(2)").join(" ");

    expect(filenameRules).toMatch(/min-width:\s*\d{3}px|max-width:\s*\d+vw|width:\s*auto/);
  });

  it("width rules cover the header cell as well as the body cell", () => {
    // Under the table layout the header row decides the column box; a rule that
    // reaches only the td leaves the two disagreeing and the columns stop
    // lining up. Selectors span lines here, so the whole selector list is read
    // rather than a single line of it.
    const bare = CSS.replace(/\/\*[\s\S]*?\*\//g, "");
    const tdOnly = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m;
    while ((m = re.exec(bare))) {
      const selector = m[1];
      const columns = [...selector.matchAll(/td:nth-child\((\d+)\)/g)].map((x) => x[1]);
      for (const col of columns) {
        if (!selector.includes(`th:nth-child(${col})`)) {
          tdOnly.push(selector.trim().slice(0, 60));
        }
      }
    }

    expect(tdOnly).toEqual([]);
  });
});

describe("cells stay table cells", () => {
  it("no rule makes a td a flex container", () => {
    // `display: flex` on a <td> removes it from the table layout algorithm and
    // its width silently stops applying.
    const offenders = rulesFor(CSS, "td").filter((body) =>
      /display:\s*(flex|grid)\b/.test(body),
    );

    expect(offenders).toEqual([]);
  });

  it("the filename cell holds a wrapper for its flex row", () => {
    expect(GRID).toContain('filename-cell');
    expect(rulesFor(CSS, ".filename-cell").join(" ")).toMatch(/display:\s*flex/);
  });
});

describe("the phone layout scrolls sideways", () => {
  const MOBILE = mobileBlock(CSS);

  it("does not hide the horizontal overflow", () => {
    // Hiding it put the right-hand columns out of reach entirely.
    expect(MOBILE).not.toMatch(/overflow-x:\s*hidden/);
  });

  it("does not force the table into a fixed layout", () => {
    // Fixed layout does not shrink content to fit; it lets it spill into the
    // next column, which is how the status pill landed on the progress cell.
    expect(MOBILE).not.toMatch(/table-layout:\s*fixed/);
  });

  it("does not pin the status, progress or actions columns to a fixed width", () => {
    const forced = [...MOBILE.matchAll(/nth-child\((3|5)\)[^{]*\{([^}]*)\}/g)]
      .map((m) => m[2])
      .filter((body) => /(^|[^-])width:\s*\d+px/.test(body));

    expect(forced).toEqual([]);
  });
});

describe("the header stays put while the body scrolls", () => {
  it("thead cells are sticky inside the scrolling container", () => {
    const sticky = rulesFor(CSS, "thead th").join(" ");

    expect(sticky).toMatch(/position:\s*sticky/);
    expect(sticky).toMatch(/top:\s*0/);
  });

  it("the sticky header is drawn above the rows", () => {
    expect(rulesFor(CSS, "thead th").join(" ")).toMatch(/z-index:\s*[1-9]/);
  });

  it("the container it sticks to is the one that scrolls", () => {
    expect(rulesFor(CSS, ".table-container").join(" ")).toMatch(/overflow-y:\s*auto/);
  });
});

describe("the AG Grid density and state contracts", () => {
  // D-12: three authorities once fought over row height (options 52, css 44,
  // formula 34). The render constants, the css bridge, and the height formula
  // must all say 44/40, with the DESIGN.md height clamps in one place only.
  it("grid options render 44px rows under a 40px header", () => {
    expect(GRID).toContain("rowHeight: GRID_ROW_HEIGHT");
    expect(GRID).toContain("GRID_ROW_HEIGHT = 44");
    expect(GRID).toContain("GRID_HEADER_HEIGHT = 40");
    expect(GRID).not.toMatch(/rowHeight:\s*(34|52)/);
  });

  it("the height formula uses the rendered row heights and the documented clamps", () => {
    expect(GRID).toMatch(/isMob \? 350 : 400/);
    expect(GRID).toMatch(/isMob \? 500 : 800/);
    expect(GRID).not.toMatch(/isMob \? 240 : 280/);
    expect(GRID).not.toMatch(/isMob \? 300 : 380/);
  });

  it("no second height authority survives in the stylesheet", () => {
    expect(rulesFor(GRID, ".ag-grid-inner").join(" ")).not.toMatch(/min-height|max-height/);
    expect(rulesFor(GRID, ".ag-grid-inner").join(" ")).not.toMatch(/transition:\s*height/);
  });

  it("cell focus is not suppressed", () => {
    // suppressCellFocus left keyboard users no way into the grid at all.
    expect(GRID).not.toContain("suppressCellFocus: true");
  });

  it("does not draw header-only column divider fragments", () => {
    // AG Grid's default resize-handle tick looks like a vertical border that
    // stops halfway through the table. The invisible hit target still works.
    expect(GRID).toMatch(/--ag-header-column-resize-handle-display:\s*none/);
  });

  it("draws column dividers continuously through header and body cells", () => {
    const dividers = rulesFor(GRID, 'ag-cell:not([col-id="actions"])').join(" ");
    expect(dividers).toMatch(/border-right:\s*1px solid var\(--card-border\)/);
    expect(GRID).toContain('.ag-header-cell:not([col-id="actions"])');
  });

  it("keeps the grid as one horizontally scrollable surface", () => {
    expect(GRID).not.toMatch(/pinned:\s*(?:mobile\s*\?[^:]+:\s*)?["'](?:left|right)["']/);
    expect(GRID).not.toContain("gridApi.sizeColumnsToFit()");
    expect(GRID).toMatch(/colId:\s*["']filename["'][\s\S]*?minWidth:\s*mobile\s*\?\s*180\s*:\s*240[\s\S]*?flex:\s*1/);
  });

  it("keeps every mobile row action inside its own column", () => {
    expect(GRID).toMatch(/colId:\s*["']actions["'][\s\S]*?width:\s*mobile \? 128 : 140/);
    expect(GRID).toMatch(/minWidth:\s*mobile \? 128 : 140/);
    expect(GRID).toMatch(
      /@media \(max-width: 640px\)[\s\S]*?\.ag-actions-cell[\s\S]*?gap:\s*2px[\s\S]*?\.ag-btn-icon[\s\S]*?width:\s*28px[\s\S]*?min-width:\s*28px/,
    );
    expect(GRID).not.toMatch(
      /@media \(max-width: 640px\)[\s\S]*?\.ag-btn-icon[\s\S]*?width:\s*48px/,
    );
  });

  it("opens details through a direct renderer callback", () => {
    expect(GRID).toContain("export let onDetails");
    expect(GRID).toContain("onDetails(download)");
    expect(APP).toContain("onDetails={openDetailModal}");
  });

  it("loading uses the supported grid option, not the deprecated overlay API", () => {
    expect(GRID).toContain('setGridOption("loading"');
    expect(GRID).not.toMatch(/showLoadingOverlay|showNoRowsOverlay|hideOverlay/);
  });

  it("a fetch failure stays distinct from a genuinely empty grid (D-02)", () => {
    expect(GRID).toContain("export let gridError");
    expect(GRID).toContain('dispatch("retryFetch"');
    expect(APP).toMatch(/gridFetchError = `http_/);
    expect(APP).toContain("gridError={gridFetchError}");
    expect(APP).toContain("on:retryFetch");
  });

  it("the terminal-failure action is genuinely disabled, not a focusable no-op", () => {
    expect(GRID).not.toContain("aria-disabled");
  });

  it("checkbox and pagination controls carry localized names and current-page state", () => {
    expect(GRID).not.toContain("Select all visible");
    expect(GRID).toContain('aria-current=');
    expect(GRID).toMatch(/aria-label=\{\$t\("pagination_(prev|next)"/);
  });
});

describe("the bulk action bar stays readable on a phone", () => {
  // The generic mobile `.button { width:100% }` rule turned this into a tall
  // three-row popup over the grid. It must stay a compact single toolbar.
  it("mobile rules keep the bar on one row and clamp it to the viewport", () => {
    const barRules = rulesFor(CSS, ".bulk-action-bar").join(" ");

    expect(barRules).toMatch(/flex-wrap:\s*nowrap/);
    expect(barRules).toMatch(/max-width:\s*calc\(100vw - 1rem\)/);
  });

  it("bulk bar buttons override the generic full-width mobile button", () => {
    const rules = rulesFor(CSS, ".bulk-action-bar .bulk-actions .button").join(" ");
    expect(rules).toMatch(/width:\s*auto !important/);
    expect(rules).toMatch(/white-space:\s*nowrap/);
  });
});

describe("button typography and theme ink", () => {
  it("does not force desktop button labels to body-sized 1rem text", () => {
    expect(CSS).toMatch(/\.button, \.add-download-button, \.logout-btn, \.tab\s*\{[\s\S]*?font-size:\s*0\.85rem !important/);
  });

  it("uses light primary-button text on dark themes", () => {
    expect(CSS).toMatch(/--button-primary-ink:\s*#fff/);
    expect(CSS).toMatch(/color:\s*var\(--button-primary-ink, #fff\) !important/);
  });
});

describe("modal and theme contracts", () => {
  const modals = [DETAIL, SETTINGS, PASSWORD, CONFIRM, AUDIT];

  it("every modal uses the shared focus trap and dialog semantics", () => {
    for (const source of modals) {
      expect(source).toContain("use:modalFocus");
      expect(source).toContain('role="dialog"');
      expect(source).toContain('aria-modal="true"');
      expect(source).toContain("aria-labelledby");
    }
    expect(MODAL_ACTION).toContain('event.key !== "Tab"');
    expect(MODAL_ACTION).toContain('event.key === "Escape"');
    expect(MODAL_ACTION).toContain("trigger.focus");
  });

  it("detail rendering uses real API fields and the canonical formatter", () => {
    expect(DETAIL).toContain("download.save_path");
    expect(DETAIL).toContain("download.error_message");
    expect(DETAIL).toContain("download.finished_at");
    expect(DETAIL).toContain("formatTimestamp(download.created_at)");
    expect(DETAIL).not.toMatch(/formatDate|getStatusClass|getStatusDot/);
    expect(DETAIL).not.toContain("download.download_path");
  });

  it("lets the detail header title shrink before clipping the mobile close button", () => {
    expect(rulesFor(DETAIL, ".header-content").join(" ")).toMatch(/min-width:\s*0/);
    expect(rulesFor(DETAIL, ".title-section").join(" ")).toMatch(/min-width:\s*0/);
    expect(rulesFor(DETAIL, ".title-text").join(" ")).toMatch(/min-width:\s*0/);
    expect(mobileBlock(DETAIL)).toMatch(/\.modern-modal\s*\{[^}]*box-sizing:\s*border-box/s);
    expect(mobileBlock(DETAIL)).toMatch(/\.close-button\s*\{[^}]*flex-shrink:\s*0/s);
  });

  it("settings previews a theme only after user input", () => {
    expect(SETTINGS).toContain("on:change={previewTheme}");
    expect(SETTINGS).toContain("selectedTheme = $theme");
    expect(SETTINGS).not.toMatch(/\$:\s*if \(isInitialized && selectedTheme\)/);
  });

  it("one theme authority validates values and clears stale classes", () => {
    expect(THEME).toContain('return THEMES.includes(value) ? value : "system"');
    expect(THEME).toContain("root.classList.remove(...CLASS_THEMES)");
    expect(THEME).toContain('mediaQuery.addEventListener?.("change"');
  });

  it("password input is masked and delete confirms retain danger intent", () => {
    expect(PASSWORD).toContain('type={showPassword ? "text" : "password"}');
    expect(PASSWORD).toContain("aria-pressed={showPassword}");
    expect(APP).toContain("isDeleteAction={confirmIsDeleteAction}");
  });
});

describe("settings density", () => {
  it("gives the settings title room while keeping tabs and body compact", () => {
    const header = rulesFor(SETTINGS, ".modal-header").join(" ");
    expect(header).toMatch(/min-height:\s*64px/);
    expect(header).toMatch(/margin:\s*0/);
    expect(rulesFor(SETTINGS, ".settings-tabs").join(" ")).toMatch(/padding:\s*0\.25rem 0\.75rem 0/);
    expect(rulesFor(SETTINGS, ".modal-body").join(" ")).toMatch(/padding:\s*1rem 1\.25rem/);
    expect(rulesFor(SETTINGS, ".modern-modal:focus").join(" ")).toMatch(/outline:\s*none/);
  });

  it("keeps proxy rows and their footer compact", () => {
    expect(rulesFor(SETTINGS, ".proxy-table th").join(" ")).toMatch(/height:\s*36px/);
    expect(rulesFor(SETTINGS, ".proxy-table td").join(" ")).toMatch(/height:\s*44px/);
    expect(rulesFor(SETTINGS, ".proxy-action-btn").join(" ")).toMatch(/height:\s*32px/);
    expect(rulesFor(SETTINGS, ".proxy-table-footer").join(" ")).toMatch(/min-height:\s*44px/);
  });

  it("does not repeat the FlareSolverr heading above its input label", () => {
    expect(SETTINGS).not.toContain("<legend>FlareSolverr</legend>");
  });

  it("uses compact accordion padding for Telegram settings", () => {
    expect(rulesFor(SETTINGS, ".telegram-header").join(" ")).toMatch(/padding:\s*0\.75rem 1rem/);
    expect(rulesFor(SETTINGS, ".accordion-content").join(" ")).toMatch(/padding:\s*1rem/);
  });
});

describe("download grid alignment", () => {
  it("centers every grid column except the filename", () => {
    expect(GRID).toContain('.ag-header-cell:not([col-id="filename"]) .ag-header-cell-label');
    expect(GRID).toContain('.ag-header-cell[col-id="filename"] .ag-header-cell-label');
    expect(rulesFor(GRID, ".ag-cell-center").join(" ")).toMatch(/text-align:\s*center/);
  });

  it("renders a dead-source skull as a status icon, not a fake button", () => {
    expect(GRID).toContain("skullSvg");
    expect(GRID).toContain("makeIndicator(skullSvg");
    expect(GRID).toContain('setAttribute("role", "img")');
    expect(GRID).not.toContain('makeBtn(\n                skullSvg');
  });

  it("keeps enough footer height for the pagination controls", () => {
    const footerRules = rulesFor(GRID, ".pagination-footer").join(" ");
    expect(footerRules).toMatch(/min-height:\s*64px/);
    expect(footerRules).toMatch(/overflow:\s*visible/);
  });

  it("keeps failed status text on its status color token", () => {
    expect(CSS).toMatch(/\.status\s*\{[^}]*color:\s*var\(--status-ink,/s);
    expect(CSS).not.toMatch(/\.status,\s*\n\.ag-status-pill\s*\{[^}]*--text-primary/s);
  });

  it("centers the custom checkbox glyph instead of pixel-offsetting it", () => {
    expect(GRID).toMatch(/ag-custom-checkbox:checked::after[\s\S]*top:\s*50%;[\s\S]*left:\s*50%;[\s\S]*translate\(-50%, -60%\)/);
    expect(GRID).toMatch(/ag-custom-checkbox[\s\S]*box-sizing:\s*border-box/);
  });

  it("keeps mobile bulk actions in one compact row", () => {
    expect(CSS).toMatch(/\.bulk-action-bar \.bulk-actions \.button\s*\{[^}]*width:\s*auto !important;[^}]*height:\s*32px/s);
  });
});

describe("dashboard skeleton geometry", () => {
  it("uses a dedicated skeleton card and a square mobile gauge", () => {
    expect(DASHBOARD).toContain("monitor-card monitor-card-skeleton");
    expect(DASHBOARD).toMatch(/monitor-card-skeleton \.monitor-body \.skeleton:first-child[^}]*width:\s*50px !important;[^}]*height:\s*50px !important;/s);
  });
});

describe("settings trend chart bounds", () => {
  it("keeps headroom above the highest data point", () => {
    expect(TREND).toContain("HEADROOM_RATIO = 1.12");
    expect(TREND).toContain("domainMax(d)");
  });

  it("clamps smoothed control points and gives the glow room", () => {
    expect(TREND).toContain("clampPlotY(p1.y");
    expect(TREND).toContain("clampPlotY(p2.y");
    expect(TREND).toMatch(/<filter id="glow" x="-20%" y="-30%"/);
  });
});
