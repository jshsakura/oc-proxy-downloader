import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * Structural guards for the app shell, dashboard gauges, period controls,
 * and the login identity surface (task-5 scope).
 *
 * Split in two halves:
 *
 *  1. "baseline characterization" pins observable behavior the current
 *     shell/dashboard/period controls already have, so the task-5
 *     consolidation cannot silently drop an existing control or label.
 *  2. "task-5 contracts" pins the repaired contracts (login identity
 *     gradient, phantom-token removal, tab semantics, period-control
 *     responsiveness). These were written red first: each one failed on
 *     the pre-repair tree, which is the failing-first proof.
 *
 * Like layout.test.js, these read source text: the defects here (phantom
 * tokens, dead :global() selectors shipped to the browser, missing ARIA
 * roles) are visible in the source and invisible to a DOM-less test run.
 */

const read = (rel) =>
  readFileSync(fileURLToPath(new URL(rel, import.meta.url)), "utf8");

const CSS = read("../src/app.css");
const APP = read("../src/App.svelte");
const LOGIN = read("../src/lib/LoginScreen.svelte");
const PERIOD = read("../src/lib/HistoryPeriodControls.svelte");
const LOCAL_GAUGE = read("../src/lib/LocalGauge.svelte");
const PROXY_GAUGE = read("../src/lib/ProxyGauge.svelte");
const DASHBOARD = read("../src/lib/Dashboard.svelte");

const PERIOD_STYLE = PERIOD.match(/<style>([\s\S]*)<\/style>/)[1];

/** Comments can name a token or syntax without using it; assertions about
 *  usage must read code, not prose (same treatment as layout.test.js). */
const bare = (src) => src.replace(/\/\*[\s\S]*?\*\//g, "");

describe("baseline characterization: the shell keeps every control it renders today", () => {
  it("renders the working/completed switcher with count badges", () => {
    expect(APP).toContain('onTabChange("working")');
    expect(APP).toContain('onTabChange("completed")');
    expect(APP).toMatch(/\{workingCount\}/);
    expect(APP).toMatch(/\{completedCount\}/);
    expect(APP).toContain('class="tab-label"');
  });

  it("renders the period bar above the grid, bound to the dashboard period", () => {
    expect(APP).toContain("HistoryPeriodControls");
    expect(APP).toContain('bind:period={dashboardPeriod}');
    expect(APP).toContain("grid-period-bar");
  });

  it("keeps the search row with its toggle, clear, and collapse affordances", () => {
    expect(APP).toContain("search-toggle-btn");
    expect(APP).toContain("search-clear-btn");
    expect(APP).toContain("clearSearch");
    expect(APP).toContain("closeSearch");
  });

  it("keeps the download form actions: host badge, clear, clipboard, password, submit", () => {
    expect(APP).toContain("detected-host-badge");
    expect(APP).toContain("clear-btn");
    expect(APP).toContain("clipboard-button");
    expect(APP).toContain("password-toggle-button");
    expect(APP).toContain('class="button button-primary add-download-button"');
  });

  it("mounts both live gauges and the monitor dashboard", () => {
    expect(APP).toContain("<ProxyGauge");
    expect(APP).toContain("<LocalGauge");
    expect(APP).toContain("<Dashboard {systemStats}>");
    expect(DASHBOARD).toContain('monitor-grid');
  });

  it("period controls offer the five segments and custom date inputs", () => {
    expect(PERIOD).toContain('"today"');
    expect(PERIOD).toContain('"7d"');
    expect(PERIOD).toContain('"30d"');
    expect(PERIOD).toContain('"all"');
    expect(PERIOD).toContain('"custom"');
    expect(PERIOD).toContain('type="date"');
    expect(PERIOD).toContain('lang="en-CA"');
  });

  it("gauges keep their stop/restart/refresh bulk actions with labels", () => {
    for (const src of [LOCAL_GAUGE, PROXY_GAUGE]) {
      expect(src).toContain("aria-label");
      expect(src).toContain("control-button");
    }
    expect(PROXY_GAUGE).toContain("refresh-button");
  });

  it("the 38px control-height contract still governs shell controls", () => {
    expect(CSS).toMatch(/\.input, \.search-input, \.button[^{]*\{[^}]*height: 38px/i);
  });

  it("the login screen keeps its language selector and lockout panel", () => {
    expect(LOGIN).toContain("language-selector");
    expect(LOGIN).toContain("lockout-timer");
    expect(LOGIN).toContain("login-button");
  });
});

describe("task-5 contracts: login identity (D-05, D-19, D-20)", () => {
  it("the login gradient is opaque in every theme: primary to primary-hover", () => {
    // --primary-color-dark is a phantom token; at computed-value time the
    // whole background is invalid and renders transparent (D-05), which
    // also causes the non-light login flash (D-19).
    expect(LOGIN).toMatch(
      /linear-gradient\([\s\S]*?var\(--primary-color\)[\s\S]*?var\(--primary-hover\)/,
    );
    expect(bare(LOGIN)).not.toContain("--primary-color-dark");
  });

  it("no phantom token is referenced anywhere in the login screen (D-20)", () => {
    const phantoms = [
      "--primary-color-dark",
      "--danger-color-rgb",
      "--warning-color-rgb",
      "--input-background",
      "--bg-primary",
      "--border-color",
      "--text-color-secondary",
    ];
    for (const token of phantoms) {
      expect(bare(LOGIN), `phantom ${token} still referenced`).not.toContain(
        `var(${token})`,
      );
    }
  });

  it("the failed-login error panel carries a danger tint from a real token", () => {
    const errorRule = LOGIN.match(/\.error-message \{([\s\S]*?)\n  \}/)?.[1] ?? "";
    expect(errorRule).toMatch(/color-mix\([^)]*var\(--danger-color\)/);
  });

  it("login text inputs fill from the documented input token", () => {
    const inputRule =
      LOGIN.match(/\.input-group input \{([\s\S]*?)\n  \}/)?.[1] ?? "";
    expect(inputRule).toMatch(/var\(--input-bg\)/);
  });
});

describe("task-5 contracts: primary tab semantics (D-32)", () => {
  const tabsBlock =
    APP.match(/<div class="tabs" role="tablist">([\s\S]*?)<\/div>/)?.[1] ?? "";

  it("the working/completed track is a real tablist", () => {
    expect(APP).toMatch(/<div class="tabs"[^>]*role="tablist"/);
  });

  it("each tab button carries role=tab and aria-selected", () => {
    // Attribute order inside the button tag is not the contract; both tabs
    // carrying the tab role and a bound selected state is.
    expect((tabsBlock.match(/role="tab"/g) ?? []).length).toBe(2);
    expect(tabsBlock).toMatch(/aria-selected=\{currentTab === "working"\}/);
    expect(tabsBlock).toMatch(/aria-selected=\{currentTab === "completed"\}/);
  });
});

describe("task-5 contracts: header switch and control labels (D-13, D-15, D-39)", () => {
  it("the header proxy toggle announces switch state (D-39)", () => {
    const toggle = APP.match(
      /class="proxy-toggle-button[\s\S]*?<\/button>/,
    )?.[0] ?? "";
    expect(toggle).toMatch(/role="switch"/);
    expect(toggle).toMatch(/aria-checked=\{useProxy\}/);
  });

  it("the header proxy toggle keeps a visible keyboard focus ring (D-13)", () => {
    expect(CSS).toMatch(
      /\.proxy-toggle-button:focus-visible[^{]*\{[^}]*box-shadow/,
    );
  });

  it("the login password toggle is labeled and keyboard-reachable (D-15)", () => {
    const toggle = LOGIN.match(
      /class="password-toggle"[\s\S]*?<\/button>/,
    )?.[0] ?? "";
    expect(toggle).not.toContain('tabindex="-1"');
    expect(toggle).toMatch(/aria-label=/);
    expect(toggle).toMatch(/aria-pressed=\{showPassword\}/);
  });

  it("the search and URL inputs are labeled, not placeholder-only (D-15)", () => {
    const search = APP.match(/class="search-input"[\s\S]*?\/>/)?.[0] ?? "";
    const url = APP.match(/class="input url-input"[\s\S]*?\/>/)?.[0] ?? "";
    expect(search).toMatch(/aria-label=/);
    expect(url).toMatch(/aria-label=/);
  });
});

describe("task-5 contracts: period controls own one responsive rule set", () => {
  it("every import sits at the top of the script (project rule)", () => {
    const lines = PERIOD.match(/<script>([\s\S]*?)<\/script>/)[1].split("\n");
    let sawStatement = false;
    for (const line of lines) {
      const code = line.trim();
      if (!code || code.startsWith("//") || code.startsWith("/*")) continue;
      if (/^import[\s{]/.test(code)) {
        expect(
          sawStatement,
          `an import appears below the top of the script: ${code}`,
        ).toBe(false);
      } else {
        sawStatement = true;
      }
    }
  });

  it("the 38px control-height lock is declared once per control, un-patched", () => {
    // The patch-era block re-declared the height rules with !important both
    // at desktop scope and again inside the media query. One declaration per
    // control (segment, custom group, apply) is the consolidated contract.
    const heights = PERIOD_STYLE.match(/height: 38px/g) ?? [];
    expect(heights.length).toBe(3);
    expect(bare(PERIOD_STYLE)).not.toContain("!important");
  });

  it("mobile reflow wraps: the segment and the custom row stack (DESIGN.md 4.3)", () => {
    const mobile = PERIOD_STYLE.match(
      /@media \(max-width: 768px\) \{([\s\S]*)\}/,
    )?.[1] ?? "";
    expect(mobile).toMatch(/\.period-controls[^{]*\{[^}]*flex-wrap: wrap/);
    expect(mobile).toMatch(/\.period-right-group[^{]*\{[^}]*width: 100%/);
  });

  it("the segment group label is localized, not hardcoded English (D-33)", () => {
    expect(PERIOD).not.toMatch(/aria-label="period"/);
    expect(PERIOD).toMatch(/aria-label=\{\$t\(/);
  });

  it("app.css no longer ships Svelte :global() selectors, which are dead in plain CSS", () => {
    // :global() is scoped-CSS syntax; in app.css the browser drops the whole
    // rule, so these blocks were silently inactive overrides.
    expect(bare(CSS)).not.toContain(":global(");
  });

  it("the period bar cancels the component's own bottom margin with a live selector", () => {
    expect(CSS).toMatch(
      /\.grid-period-bar \.period-controls \{[^}]*margin-bottom: 0/,
    );
  });
});
