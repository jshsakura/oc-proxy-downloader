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
  const headerCount = (APP.match(/<th[\s>]/g) || []).length;

  it("the header has the nine columns the width rules assume", () => {
    // select, filename, status, size, progress, speed, date, proxy, actions.
    expect(headerCount).toBe(9);
  });

  it("no width rule points past the last column", () => {
    const indexes = [...CSS.matchAll(/nth-child\((\d+)\)/g)].map((m) => Number(m[1]));

    expect(Math.max(...indexes)).toBeLessThanOrEqual(headerCount);
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
    expect(APP).toContain('class="filename-cell"');
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
