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
const DETAIL = read("../src/lib/DetailModal.svelte");
const SETTINGS = read("../src/lib/SettingsModal.svelte");
const PASSWORD = read("../src/lib/PasswordModal.svelte");
const CONFIRM = read("../src/lib/ConfirmModal.svelte");
const AUDIT = read("../src/lib/AuditModal.svelte");
const MODAL_ACTION = read("../src/lib/modal.js");
const THEME = read("../src/lib/theme.js");

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
  // At 375px the one-row bar was wider than the viewport, so the flex-squeezed
  // buttons fragmented their Korean labels one glyph per line (and the EN bar
  // escaped the viewport entirely). The bar must wrap as rows inside the
  // viewport and each label must stay on one line.
  it("mobile rules let the bar wrap and clamp it to the viewport", () => {
    const barRules = rulesFor(CSS, ".bulk-action-bar").join(" ");

    expect(barRules).toMatch(/flex-wrap:\s*wrap/);
    expect(barRules).toMatch(/max-width:\s*calc\(100vw - 2rem\)/);
  });

  it("bulk bar buttons never fragment their labels", () => {
    expect(rulesFor(CSS, ".bulk-action-bar .button").join(" ")).toMatch(/white-space:\s*nowrap/);
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
