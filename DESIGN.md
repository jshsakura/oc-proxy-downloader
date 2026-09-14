# DESIGN.md - OC Proxy Downloader Frontend Design System

This document is the authoritative design contract for the Svelte dashboard in
`frontend/`. It codifies what already ships; it does not invent a new product
direction. Every color, font size, spacing value, and component behavior used
in new or modified frontend code must trace back to a token, scale, or rule in
this file.

- Baseline: HEAD `097edbb3b0e953027570189c4212945ca22995f5` plus the 12
  modified frontend sources verified by task 1
  (`.omo/evidence/ui-design-polish-and-finish/task-1/baseline.txt`).
- Measured inventory: `.omo/evidence/ui-design-polish-and-finish/task-2/design-system-audit.txt`
  maps every CSS custom property and every raw value in the current sources to
  a role defined here.
- Drift rule: newly introduced or modified styling may not introduce a raw
  color, font size, or spacing value that this contract does not name. Raw
  values already present in the baseline are documented below as legacy state;
  they migrate to tokens when their rule is next touched, not before.
- Style sheets of record: `frontend/src/app.css` (global) and the scoped
  `<style>` blocks of `frontend/src/lib/*.svelte`.

## 1. Atmosphere and Identity

**Product.** A self-hosted, single-page operational dashboard for queued
proxy downloads: watch live transfer gauges, system monitors, and a data-dense
download grid, intervene on individual items, and audit history. The user is
an operator scanning for anomalies, not a visitor being persuaded. Density and
legibility outrank decoration in every conflict.

**Identity markers.**

- Wordmark: the app title renders in `Zen Tokyo Zoo` (uppercase, tight
  letter-spacing) at `1.8rem` in the header (`2rem` fallback for a bare `h1`).
  It is the only display-face usage in the product.
- Body face: `Nanum Gothic` (weights 400/700/800) via `--font-sans`, loaded
  from Google Fonts in `frontend/index.html`; full fallback stack ends in the
  system emoji fonts. Korean is the primary UI language; all strings route
  through `i18n.js` (ko/en).
- Logo: 32px square `logo256.png` in the header, doubling as a refresh button.
- Numbers are `font-variant-numeric: tabular-nums` wherever they update live
  (speeds, counts, pagination, disk bars).
- Micro-labels (CPU, RAM, table headers, badges) are 0.6 to 0.72rem,
  `text-transform: uppercase`, `letter-spacing: 0.05em`, secondary color.

**Surface character.** Flat, calm, card-based surfaces with a light glass
tint: cards blur their backdrop at 12px, modals at 24px with 180% saturation.
Depth is communicated with hairline borders (`1px solid var(--card-border)`)
and restrained shadows, never heavy drop shadows. Color is carried by small
saturated elements (status pills, active segments, primary buttons) over
near-neutral surfaces. Status color is the loudest voice on the page because
it is the information.

**What this UI is not.** No marketing hero, no illustration, no decorative
gradient mesh. The two sanctioned gradients are the skeleton shimmer and the
login card's primary-to-dark fill.

## 2. Color

### 2.1 Token architecture

All theming flows through CSS custom properties defined per theme in
`app.css`: `:root` (light) plus `html.<theme>` blocks. Theme switching swaps
the property set; components reference only the properties. The full
per-theme value matrix is in the audit file; the role groups:

| Group | Tokens | Role |
|---|---|---|
| Meta | `--font-sans`, `--date-icon-filter`, `color-scheme` | Font stack, date-input icon inversion on dark themes, native form control scheme |
| Page surface | `--background`, `--bg-secondary` | Page canvas; recessed hover surface (page-nav and bulk secondary hover) |
| Card surface | `--card-background`, `--card-border` | Cards, inputs' outer frame, table surfaces, modal fill (via glass mix) |
| Text | `--text-primary`, `--text-secondary` | Primary ink; meta ink |
| Brand | `--primary-color`, `--primary-hover`, `--primary-color-rgb` | Interactive accent, its hover, and its RGB triplet for `rgba()` tints |
| Feedback | `--danger-color`, `--danger-hover`, `--success-color`, `--warning-color` | Destructive, success, warning; warning doubles as the proxy-mode accent |
| Status labels | 18 tokens: `--status-downloading-bg`, `--status-downloading-border`, `--status-downloading-text`, `--status-pending-bg`, `--status-pending-border`, `--status-pending-text`, `--status-parsing-bg`, `--status-parsing-border`, `--status-parsing-text`, `--status-done-bg`, `--status-done-border`, `--status-done-text`, `--status-failed-bg`, `--status-failed-border`, `--status-failed-text`, `--status-stopped-bg`, `--status-stopped-border`, `--status-stopped-text` | Per-state triads consumed by the status pill (section 5). `pending` also serves `waiting` and `proxying` |
| Inputs | `--input-bg`, `--input-border`, `--input-inner-bg` | Select fill, input frame, tinted text-input fill |
| Buttons | `--button-background`, `--button-hover-background`, `--button-text`, `--button-secondary-background`, `--button-secondary-text`, `--button-secondary-background-hover`, `--button-secondary-border`, `--disabled-button-background`, `--disabled-button-text` | Neutral button chrome (see 2.4: base neutral button is only themed in dark/dracula; always use a variant class) |
| Charts | `--chart-color-1`, `--chart-color-2`, `--chart-color-3`, `--chart-grid`, `--chart-muted`, `--chart-bg` | Series 1 (down/good), series 2 (danger), series 3 (warning); grid lines; axis meta |
| Depth | `--shadow-light`, `--shadow-medium` | Resting and hover elevation (section 7) |
| Dashboard aliases | `--dashboard-card-bg`, `--dashboard-card-border`, `--dashboard-stat-value`, `--dashboard-stat-label` | Alias layer over card/text tokens for monitor cards |
| Scrollbar | `--scrollbar-thumb`, `--scrollbar-thumb-hover`, `--scrollbar-track` | Page and table scrollbar chrome in the theme accent |
| Skeleton | `--skeleton-base`, `--skeleton-shimmer` | Loading placeholder gradient stops |
| Toast (vestigial) | `--toast-bg`, `--toast-text` | Superseded by svelte-sonner inline style using card/text tokens |
| Tabs (vestigial) | `--tab-inactive-bg` | Light-only value from the pre-segmented design; the tab track now derives from `color-mix(... var(--text-secondary) 12%, transparent)` |
| Selection | `--theme-selected-bg` | Selected swatch/row tint in theme pickers |

Component-scoped tokens: `--status-hue` / `--status-ink` (status pill
locality, defined in `app.css` and duplicated in `DetailModal.svelte`, section
5). Bridge tokens: the 16 `--ag-*` variables in `AgDownloadGrid.svelte`
(`--ag-font-family`, `--ag-font-size`, `--ag-grid-size`, `--ag-row-height`,
`--ag-header-height`, `--ag-background-color`, `--ag-foreground-color`,
`--ag-secondary-foreground-color`, `--ag-header-background-color`,
`--ag-header-foreground-color`, `--ag-border-color`, `--ag-row-border-color`,
`--ag-odd-row-background-color`, `--ag-row-hover-color`,
`--ag-selected-row-background-color`, `--ag-range-selection-border-color`)
map AG Grid quartz/quartz-dark onto the theme tokens above; AG Grid reads
nothing else.

### 2.2 The 11 kept themes

Selector = class on `html` (and mirrored on `body` by `theme.js`).
`color-scheme: dark` everywhere except light.

| Theme | Class | Canvas | Card | Border | Text | Accent (`--primary-color`) |
|---|---|---|---|---|---|---|
| light | (none, `:root`) | `#f8fafc` | `#ffffff` | `#e2e8f0` | `#1e293b` | indigo `#6366f1` |
| dark | `dark` | `#1a1a2e` | `#252540` | `#333355` | `#e2e8f0` | indigo `#818cf8` |
| forest | `forest` | `#0d1a0f` | `#152118` | `#1e3322` | `#dcfce7` | green `#4ade80` |
| sunset | `sunset` | `#1a0f0a` | `#261a12` | `#3d2818` | `#fff7ed` | orange `#fb923c` |
| dracula | `dracula` | `#282a36` | `#3a3c4e` | `#50556a` | `#f8f8f2` | violet `#9580ff` (status pills use `#bd93f9`) |
| nord | `nord` | `#2e3440` | `#3b4252` | `#434c5e` | `#eceff4` | frost `#88c0d0` |
| solarized | `solarized` | `#002b36` | `#073642` | `#0a4050` | `#fdf6e3` | yellow `#b58900` |
| monokai | `monokai` | `#272822` | `#1e1f1c` | `#3e3d32` | `#f8f8f2` | magenta `#f92672` |
| ocean | `ocean` | `#0a192f` | `#112240` | `#1d3461` | `#ccd6f6` | teal `#3dd6b0` |
| rose | `rose` | `#191015` | `#261a22` | `#3d2434` | `#fce7f3` | rose `#f43f5e` |
| neon | `neon` | `#0a0a0f` | `#141425` | `#252540` | `#e0e0ff` | magenta `#e040fb` |

No theme may be removed. A new theme means a new `html.<name>` block
defining the full token set (use the dark blocks as the template) plus a
`<option>` in the settings theme select and a class entry in
`theme.js` `applyThemeClass`.

**`system` selection.** `system` is a stored preference, not a theme: when
selected, `theme.js` consults `matchMedia('(prefers-color-scheme: dark)')`
once at apply time and applies the `dark` class or none (light). It does not
listen for later OS changes until the next apply. The stored value lives in
`localStorage['theme']` and (when saved) the server settings `theme` field.

### 2.3 Alpha and tint system

Tints of the accent are always built from the triplet:
`rgba(var(--primary-color-rgb), 0.04 to 0.45)`. The observed ladder is
0.04/0.05 (inner fills), 0.08 (icon hover), 0.1 (strong hover), 0.12 to 0.18
(selected), 0.3 to 0.45 (borders, glow shadows). New accent tints must come
from this ladder. Black scrims and white glass overlays follow the fixed
steps in the audit (raw-value families F2 scrim-black, F3 glass-white); those
two families plus `#fff` on saturated fills (F1 on-fill ink) are the only
raw colors this contract blesses for unrestricted reuse.

### 2.4 Contradictions resolved (documented; code changes deferred)

1. **Phantom tokens.** `--bg-primary`, `--border-color`,
   `--text-color-secondary`, `--input-background`, `--primary-color-dark`,
   `--danger-color-rgb`, `--warning-color-rgb` are referenced but never
   defined; each declaration is silently invalid at computed-value time.
   Canonical mapping when the rule is next touched:
   `--bg-primary` -> `--background`; `--border-color` -> `--card-border`;
   `--text-color-secondary` -> `--text-secondary`; `--input-background` ->
   `--input-bg`; `--primary-color-dark` -> `--primary-hover` (gradient stop);
   `--danger-color-rgb` / `--warning-color-rgb` -> define the triplets in
   every theme block (mirroring `--primary-color-rgb`) or use the solid
   token. New code must not use phantom names.
2. **Dead `html[data-theme=...]` selectors.** `theme.js` sets classes, never
   a `data-theme` attribute, so the light/dracula blocks at app.css lines
   1605 to 1640 never apply. Consequence: the neutral `--button-background`
   family is only defined in `dark` and `dracula`; a bare `.button` in the
   other nine themes paints a transparent background. Contract: never render
   a `.button` without a variant (`button-primary`, `button-secondary`,
   `button-danger`, or `button-icon`); base `.button` is chrome only.
3. **Duplicated status pill.** `span.status` exists globally (app.css) and as
   a scoped copy in `DetailModal.svelte`. They differ in one state: stopped
   ink. Canonical behavior is the global one (`--text-primary`); the
   DetailModal copy migrates to match when next touched.
4. **`--toast-bg` / `--toast-text` / `--tab-inactive-bg`** are vestigial (see
   2.1); do not add new usages.
5. **Legacy raw-value families.** Raw colors outside the token system are
   inventoried in the audit under families F4 to F12 (danger reds, warning
   oranges, success greens, neutral greys, blue link accents, theme-swatch
   previews, dracula code palette, indigo/slate/purple tints). They are
   legal as-is where they stand; when one of their rules is modified it must
   move onto the corresponding token (mapping table in the audit). The
   families themselves stay raw where representation demands it: theme
   swatches and code blocks must show their fixed palettes regardless of the
   active theme.

### 2.5 Theme selection surfaces and migration to one authority

Two selection surfaces exist today:

- **ThemeSelect (authoritative):** the `<select id="theme">` in
  `SettingsModal.svelte`. It binds `selectedTheme`, live-previews via
  `theme.set()` on change, persists to server settings on save, and restores
  `originalTheme` on cancel.
- **ThemeToggle (legacy, currently unmounted):** `ThemeToggle.svelte` writes
  `localStorage['theme']` directly and toggles only the `dark` class,
  bypassing the store. If remounted it would desync the store (store still
  holds the old value; server settings untouched). It is imported nowhere;
  `.theme-toggle-btn` CSS remains as a stub.

Target state (documented now, source changes belong to the repair tasks):
`theme.js` writable store is the single theme authority. ThemeSelect becomes
a thin view over it (already is); ThemeToggle either is deleted or becomes a
store-calling quick toggle cycling light -> dark -> light that persists
through the store, never through direct `localStorage` writes. No component
other than `theme.js` may touch `localStorage['theme']` or the `html`
theme classes. The `.theme-options` / `.theme-card` radio-grid CSS in
app.css and SettingsModal is the leftover of a removed picker UI; it is
legacy state (documented, not used, safe to remove in a repair task).

## 3. Typography

**Families.** `--font-sans` is the only text family (Nanum Gothic stack).
`Zen Tokyo Zoo` is display-only (app wordmark). Monospace appears solely
inside the DetailModal code block (`monospace` family, fixed dracula-ish
palette, audit family F10). AG Grid inherits `--ag-font-family:
var(--font-sans)`.

**Scale (measured; rem unless noted).** The canonical roles and their
permitted values:

| Role | Size | Weight | Notes |
|---|---|---|---|
| Wordmark | `1.8rem` (`2rem` bare `h1`) | 400 | Zen Tokyo Zoo, uppercase |
| Modal title | `1.05` to `1.25rem` | 600 to 700 | `.modal-header h2` |
| Section title | `0.9` to `1.1rem` | 600 | Settings sections, stats titles |
| Body / table cell / control label | `0.8` to `0.9rem` | 400 to 600 | Workhorse is `0.85rem` |
| Forced control text | `1rem` | inherit | The 38px control-height override (below) forces `font-size: 1rem` on `.input`, `.search-input`, `.button`, `.tab`; this is the sanctioned exception, do not fight it locally |
| Secondary / meta | `0.7` to `0.78rem` | 400 to 600 | Counts, meta rows |
| Micro-label | `0.6` to `0.72rem` | 600 to 800 | Uppercase, `letter-spacing: 0.05em` |
| Stat value | `0.82` to `1.5rem` | 700 | KPI numbers, tabular-nums |
| SVG gauge text | `8` / `10` / `18px` | 700 for values | Inline SVG `font-size` attributes; exempt from the rem scale |
| AG Grid | `14px` root, `14px` header | 700 header | Set via `--ag-font-size` / `--ag-header-*` |

The measured long tail (0.6 to 2.7rem, px values 8 to 18 in SVG and gauge
components) is fully enumerated in the audit; new styles must reuse a role
from this table rather than minting another step.

**Rules.**

- Body `line-height: 1.6`; pills, labels, and headings `1.2`.
- Uppercase only for micro-labels, table headers, and badges, always with
  `letter-spacing: 0.03em` to `0.08em`.
- Never below `0.6rem`. Anything at `0.6` to `0.65rem` must be secondary
  color or a badge, never primary reading text.
- Weights: 400 body, 500 to 600 emphasis/controls, 700 headings and active
  states, 800 labels (form `label` is the only 800).

## 4. Spacing, Layout, and the 4px Grid

### 4.1 Units

Base unit is 4px. The canonical spacing scale (rem and px equivalents):
`2px` (hairline offsets only), `4px` (`0.25rem`), `8px` (`0.5rem`),
`12px` (`0.75rem`), `16px` (`1rem`), `20px` (`1.25rem`), `24px` (`1.5rem`),
`32px` (`2rem`). Legacy in-between steps present in the baseline
(`0.3rem` 4.8, `0.35rem` 5.6, `0.4rem` 6.4, `0.6rem` 9.6, `0.65rem` 10.4,
`0.7rem` 11.2, `0.85rem` 13.6) are documented in the audit; when a rule
using one is modified, snap it to the canonical scale. Gaps inside dense
monitor/dashboard clusters (`0.4rem` to `0.75rem`) are the exception band
where the legacy values are closest to intentional; prefer `4/8/12` there
too.

**Control heights (fixed).** Standard controls are exactly `38px` tall:
`.input`, `.search-input`, `.button`, `.add-download-button`, `.tab`
(enforced by the `!important` block at the end of app.css). `34px` remains
in earlier `.button` declarations but the 38px override wins; new rules
write `38px`. Small controls: icon buttons 26 to 32px hit area (mobile
raises action icons to `48px`), `30px` page-number buttons, `32px` mobile
page buttons. Row heights: AG Grid `44px` rows, `40px` header
(`--ag-row-height`, `--ag-header-height`).

**Radii.** Controls `8px` (buttons, inputs, tabs, page buttons); cards and
surfaces `10` to `12px` (`.card` 9px is legacy-accepted); selects `10px`;
modals and their footers `16px`; modals in Confirm/Password `12px` (legacy);
pills and progress tracks `999px` or `50%` circles; micro badges `4px`.
`13px` exists only on the proxy toggle (track height/2).

### 4.2 Layout regions and scroll ownership

Shell (top to bottom inside `#app`, max-width `1200px`, centered):

1. `.header`: logo button, centered wordmark, `.header-actions` (settings
   icon button). No scroll.
2. `.card` download form: URL input with inline actions (host badge, clear,
   clipboard, password), proxy toggle, submit button.
3. `Dashboard`: slot `gauges` rendering `.live-card` (ProxyGauge + LocalGauge
   as two equal panes) and `.monitor-grid` (CPU / RAM / Disk / Network cards).
4. `.downloads-section`: `.grid-period-bar` (HistoryPeriodControls row),
   `.tabs-container` (working/completed segmented tabs + search), then
   `AgDownloadGrid` with its `.pagination-footer`.
5. Overlays: modals, `.bulk-action-bar` (fixed bottom-center when rows are
   selected), sonner toaster (bottom-center), login screen when
   unauthenticated.

**Scroll ownership (binding).**

| Region | Owner of vertical scroll | Owner of horizontal scroll |
|---|---|---|
| Page | `html`/`body` (`overflow-x: hidden` globally) | none |
| AG Grid | `.ag-grid-inner` / AG viewport, capped `800px` desktop / `500px` below 640px | AG viewport; sticky first columns handled by AG |
| Legacy table container / settings proxy table | `.table-container` (`max-height` 500px desktop / 60vh mobile; sticky `thead`) | same container |
| Modals | `.modal-body` / modal content (`overflow-y: auto`) inside `max-height: 90vh`; header and actions stay pinned | content wraps; only code blocks may scroll horizontally |
| Mobile summary strip | none (fixed pill heights) | `.dashboard-summary-strip` (touch, scrollbar hidden) |

Body scroll may be locked only by an open modal that needs it
(DetailModal sets `body { overflow: hidden }` while open). No scroll
container may nest another scroll container on the same axis.

### 4.3 Responsive behavior: 375 / 768 / 1280

Breakpoints in the codebase: 480, 600, 640, 759/760, 768/769, 900, 1199/1200.
The three contract widths and their guaranteed behavior:

**375px (mobile).**
- `#app` padding `1rem`; download form stacks vertically, submit button full
  width; proxy toggle row keeps its own line at 52px.
- `.monitor-grid` compresses to 4 narrow columns: sparklines, disk bars,
  meta rows, and net units hidden; gauge shrinks to 50px; numbers only.
- `.live-card` and `.gauge-container` are single column (below 759/640).
- Tabs stretch full width with ellipsized labels; search collapses into a
  40px toggle button that expands to a full-width row.
- Period controls go full-width segmented; custom dates and apply button
  take the next full-width row.
- AG Grid: min 350px, max 500px tall; grid density set by `--ag-*`.
- Modals: `95vw`, `margin: 1rem`, action buttons share one row (`flex: 1`);
  modal `table` rows become stacked label/value blocks; theme select stays a
  native select. Toasts clamp to 320px/90vw (below 480).
- Legacy table (settings proxy list): horizontal scroll with sticky header;
  filename column capped at `46vw` with ellipsis.
- Mobile pagination layout (below 640): compact numbered window with
  first/last anchors, prev/next at 40px height.

**768px (tablet boundary; `max-width: 768px` blocks are inclusive, desktop
table rules start at 769).**
- Both gauges side by side (live-card is 2-column above 759); monitor grid
  is 2-column below 900.
- Modals take the medium tier (768 to 1199): `max-width: 700px`.
- Desktop pagination (numbered window) is active; mobile pagination is not
  (below 640 only).
- Download form is single row (above 641) with the 200px submit button
  (above 760).

**1280px (desktop).**
- `#app` centered at `max-width: 1200px`; monitor grid 4-column with full
  sparklines; table floors (`min-width: 800px`) active, wide columns scroll
  inside the container, never crush.
- Modals take the large tier (1200+): `max-width: 800px`.
- Full action column density; `40px` select column; filename column takes
  remaining width (`40%`, min 220px, max 460px).

**Content-stress rules.**
- Long filenames: ellipsis everywhere (`min-width: 0` on the flex child,
  `overflow: hidden; text-overflow: ellipsis; white-space: nowrap`); caps
  460px desktop / 46vw mobile.
- Long URLs and host strings: `word-break: break-all` inside DetailModal
  values; never inside grid cells.
- Long localized status labels (e.g. "재시도 대기 (0:38)"): pills stay
  `nowrap`; the table scrolls sideways instead of wrapping or shrinking
  below content size. Fixed pseudo-widths on content cells are forbidden.
- CJK text: wraps at any character by default in body copy; `nowrap` +
  ellipsis only in the cells and labels listed here. No `letter-spacing`
  on CJK body text (micro-labels only, where they are short).
- Live numbers use `tabular-nums` so refreshes do not jitter layout.
- Pagination windows collapse to `...` dots under pressure; mobile keeps
  first/last reachable.
- Empty states: `.no-downloads-message` and `.empty-table` (200px) instead
  of collapsed regions.

## 5. Components and States

Shared primitives used two or more times (file of record in parentheses;
`.foo` = app.css global class):

1. **Button** `.button` (app.css; AgDownloadGrid, modals, App): variants
   `button-primary` (accent fill, `#fff` ink, glow shadow on hover),
   `button-secondary` (tinted glass fill, card border), `button-danger`
   (danger fill; the bulk bar uses raw `#e53935`/`#b71c1c`, audit F4),
   `button-icon` (transparent, secondary ink, 8px radius; modifiers
   `danger`, `is-warn`, `is-disabled`, `is-cooldown`, `is-running`).
   States: hover (variant fill/hover token + shadow-medium), focus-visible
   (ring, section 8), disabled (`--disabled-button-*`, `opacity: 0.7`,
   `cursor: not-allowed`, no shadow), loading (inline `.spinner` + label).
2. **Input** `.input` (app.css; SettingsModal, PasswordModal, AuditModal,
   App): tinted inner fill, 1px `--input-border`, 8px radius, 38px height;
   `select.input` variant uses `input-bg` fill and the `SelectArrow.svg`
   chevron; `.search-input` variant uses card fill with absolute icon and
   clear button. States: focus (accent border + 2 to 3px accent ring +
   deeper tint), disabled via `disabled` attribute, invalid via native
   `required` (native outline suppressed only on focus-rewritten rules).
3. **Card** `.card`, `.monitor-card`, `.live-pane`, `.skeleton-card`
   (app.css, Dashboard): card token fill, hairline border, radius 9 to 12px,
   shadow-light, optional 12px glass blur. States: hover only where the card
   is interactive (summary pill, theme card legacy).
4. **Modal** (SettingsModal `.modern-*`, DetailModal, ConfirmModal,
   PasswordModal, AuditModal): fixed backdrop `rgba(0,0,0,0.5-0.6)`
   (Confirm/Password add 4px blur), glass panel (24px blur, 180% saturate,
   70% card mix), header (icon + title + close), scrollable body, action
   footer. Widths: 400 (confirm), 600 default, 700 medium, 800 large, 90-95vw
   mobile; `max-height: 90vh` (95vh below 700px viewport height). z-index
   ladder in section 7. Confirm/Password/Audit sit above Settings (20000 vs
   10000) so confirms stack on top of settings.
5. **Segmented control**: tabs `.tabs` / `.tab` (track:
   `color-mix(text-secondary 12%, transparent)`; inactive transparent;
   active = accent pill, white ink, count badge inverted) and
   `.period-segment` / `.period-seg-btn` (same shape, card-filled track),
   plus `.settings-tabs` in SettingsModal. States: hover (8% primary mix),
   active (accent fill), count badge (22% secondary mix; on active: white
   fill, accent ink).
6. **Status pill** `span.status` (app.css; duplicated scoped in
   DetailModal): `--status-hue` drives a 15% mix background, 38% mix border,
   and a solid dot; `--status-ink` colors the text. State classes:
   downloading, pending (+waiting, proxying), parsing, done, failed,
   stopped. Working states animate only the dot (pulse 1.5s). Exhausted
   retry: `.status-exhausted` (secondary, dimmed).
7. **Kind chip** `.kind-chip` (+ dead / auth-family / blocked-family /
   alive variants): failure-classification chip inside the status cell;
   fixed raw severity palette (audit F4/F5/F12) intentionally theme-stable.
8. **Checkbox** `Checkbox.svelte` (+ AG header select-all): custom box,
   `:focus-visible` ring on the box via sibling selector; the only
   focus-visible rule in the baseline (section 8 makes the pattern general).
9. **Skeleton** `Skeleton.svelte` + `.skeleton*` layout classes: shimmer
   gradient over `--skeleton-base/shimmer`, `flex-shrink: 0`, capped
   `max-width: 100%`; page, form, live, monitor, and table scaffolds mirror
   the real layouts 1:1.
10. **Spinner** `.spinner` (16px, currentColor ring), `.row-audit-spinner`
    (12px, accent top), `.modal-spinner` (24px), `.loading-spinner`:
    `spin 1s linear infinite`; proxy/wait micro-spinners 8 to 10px.
11. **Donut gauge** (Dashboard SVG, StatusDonutChart): 100x100 viewBox,
    36px radius ring, `--chart-grid` track, threshold fill (accent below
    65%, warning to 88%, danger above), center value + micro sublabel,
    `stroke-dasharray` transition 0.6s.
12. **Sparkline** (Dashboard spark, TrendChart, AG cell sparkline): area
    gradient 40% to 0% under a 1.4px stroke; net-up uses warning color
    dashed.
13. **Progress bar** `.progress-container` / `.progress-bar` /
    `.progress-text`: 25px track (card-border fill), success fill at 90%
    opacity, white centered percent text with 1px text-shadow, width
    transition 0.15s ease-out.
14. **Toggle switch** `.proxy-toggle-button` (52x26, header form) and
    `.grid-proxy-toggle` (40x20, grid cell): local = accent fill, proxy =
    warning orange (raw `#ffb74d`/`#ffa726`, audit F5), disabled = grey
    ladder (F7); white 18px slider translating 20 to 26px.
15. **Pagination** `.page-number-btn` (30px), `.prev-next-btn`, mobile
    `.page-nav-btn` / `.page-number-btn-mobile` (32px), `.page-dots`:
    active = accent fill white ink; hover = 12% accent tint; disabled 45%
    opacity. Footer `.pagination-footer` is part of the grid card (min-height
    48px desktop).
16. **Theme picker**: current UI is the settings `<select>` (ThemeSelect,
    section 2.5); legacy `.theme-options` / `.theme-card` radio grid CSS is
    retained but unrendered.
17. **Toast** (svelte-sonner `Toaster`, bottom-center, richColors, 3
    visible, 3s): panel styled inline with card/text/border tokens; width
    clamp 400 to 600px (320 to 90vw below 480px).
18. **Badge** `.detected-host-badge` (host slug or multi-link count),
    `.tab-count`, `.version-label`: uppercase micro text, 4 to 8px radius,
    tinted fills (multi = indigo 15%, audit F11).
19. **Close button** `.close-button` / header icon buttons: transparent,
    secondary ink, 5 to 8px radius; hover = card-border fill or 10% accent
    tint; settings gear rotates 45 degrees on hover, theme stub rotates 15.
20. **Field group** `.form-group` + `label` (app.css; every modal form):
    block label (800 weight, secondary ink), 1.5rem vertical rhythm,
    fieldset variant with 10px radius border.
21. **Bulk action bar** `.bulk-action-bar`: fixed bottom-center glass bar
    (16px blur), count + secondary/danger/secondary buttons, slide-up
    entrance, z-index 9000.
22. **Period controls** `HistoryPeriodControls`: segment + custom date
    inputs (`lang="en-CA"`, en-dash separator) + apply button; all locked to
    38px.
23. **Code block** (DetailModal): monospace, fixed dark palette (F10),
    horizontal scroll only.
24. **Stat KPI card** (SettingsModal stats tab): icon + big value + label
    triple; warning-variant for totals.

## 6. Motion

**Durations.** Micro-feedback `0.15` to `0.2s` (tabs 0.15, page buttons
0.18, icon hovers 0.2); standard state changes `0.2` to `0.3s` (buttons,
cards, inputs, theme cross-fade 0.3); entrances `0.2` to `0.28s`
(badge pop 0.2, bulk bar slide 0.28 with `cubic-bezier(0.16, 1, 0.3, 1)`);
data visualization `0.6s` (gauge dasharray) and progress `0.15s`; loops:
spin 0.7 to 1s, dot pulse 1.5s, shimmer 1.8s. Nothing new exceeds 0.3s
except data-viz transitions.

**Properties.** Animate `transform`, `opacity`, `filter`, and color tokens
only. Sanctioned exceptions (data-driven, not decorative): progress bar
`width`, gauge `stroke-dasharray`/`stroke`, skeleton `background-position`.
Layout properties (`top/left/height/padding`) animate nowhere and must not
start.

**Keyframes inventory** (reuse, do not redeclare): `spin`, `pulse`,
`pendingPulse`, `pulse-dot`, `parsing-loading`, `fadeInBadge`, `fadein`,
`fadeout`, `slideUpFloat`, `skeleton-shimmer`, `ripple`, `bounce`,
`pulse-glow`. Only working states carry looping animation (downloading /
parsing / proxying dots, spinners, shimmer); settled states never pulse.
Hover motion maps to real affordances only (chevron rotation signals
expandability; gear rotation signals the settings affordance).

**Reduced motion.** Every new or modified animation must be wrapped in
`@media (prefers-reduced-motion: no-preference)` (or gated with an
equivalent query) so reduced-motion users get static states. The baseline
ships without such guards; adding them where a rule is touched is mandatory,
retrofitting untouched rules belongs to the repair tasks. Loops that convey
"work in progress" (spinners, shimmer) may slow to a static state; they must
not disappear entirely, because the loading signal is information.

## 7. Depth and Surface

**Shadows.** Tokens `--shadow-light` (resting cards, controls) and
`--shadow-medium` (hover lift). Legacy raw ladder (rgba components in audit family F2): `0 2px 6/8px`
(resting buttons), `0 4px 12/16px` (hover, accent glow uses
`rgba(var(--primary-color-rgb), 0.3-0.45)`), `0 16px 40px` (bulk bar),
`0 25px 50px -12px` (modals). Shadow steps above 12px blur are reserved for
overlays; cards never exceed shadow-medium.

**Glass tiers.** Input / secondary button `blur(8px)`; card `blur(12px)`;
bulk bar `blur(16px)`; modal `blur(24px) saturate(180%)` over
`color-mix(card 70%, transparent)`. Backdrops: `rgba(0,0,0,0.5)` base,
0.6 for the legacy global modal, plus optional 4px backdrop blur on small
confirm modals.

**Elevation ladder (z-index).** Content stacking 1 to 50 (spinners over
bars, sticky table header 100) < bulk action bar 9000 < DetailModal 1000
(legacy position; visually below settings in practice because settings is
10000) < SettingsModal 10000 < Confirm/Password/Audit 20000 to 20001 <
sonner toaster (library default, top). New overlays pick the next free tier;
never exceed 20000 for a confirm stacked on settings.

**Borders and hairlines.** `1px solid var(--card-border)` is the only
resting border. Sticky table headers draw their divider as
`box-shadow: inset 0 -1px 0 var(--card-border)` (border-collapse cannot
carry it). Focus rings are 2 to 3px accent tints (section 8), never borders.

## 8. Accessibility Constraints and Accepted Debt

### 8.1 Binding constraints (WCAG 2.2 AA)

- **Contrast.** 4.5:1 for text, 3:1 for large text (18.66px bold / 24px),
  icons, and control boundaries (SC 1.4.3, 1.4.11). Ink-on-token pairs must
  be checked per theme when a pairing changes. Known tight spots to respect
  in any modification: light-theme `--success-color` (#81c784) as text on
  white fails 4.5:1 (use a darker green when a text rule is touched);
  `#ffb74d` proxy toggle needs its dark slider/knob contrast preserved;
  white text on `--primary-color` passes in all 11 themes today and must be
  re-verified if any theme's accent changes; status-pill text tokens are the
  per-theme contrast workaround and must never be replaced by hue tokens.
- **Focus visible (SC 2.4.7, 2.4.11).** Every interactive element shows a
  visible focus indicator: inputs/search use the accent border plus 2 to 3px
  `rgba(var(--primary-color-rgb), 0.1-0.2)` ring; buttons and tabs inherit
  or must add an equivalent ring. `outline: none` without a replacement ring
  is a defect. `:focus-visible` (the Checkbox.svelte pattern) is the
  preferred form for pointer+keyboard shared controls. Modals must not hide
  the focused element behind the fixed bulk bar.
- **Target size (SC 2.5.8).** Interactive targets at least 24x24px AA
  minimum; the house standard is 38px controls and 48px mobile action icons
  (`.actions .button-icon { min-width/height: 48px }`), which exceeds AA.
  New compact controls (dots, clears, chevrons) must keep a 24px hit area
  via padding.
- **CJK and text wrap.** Korean strings may wrap at any glyph in body copy;
  `white-space: nowrap` is allowed only in the cells and labels enumerated
  in 4.3, always paired with `text-overflow: ellipsis` and `min-width: 0`.
  No `text-transform: uppercase` on user-entered or localized sentence text
  (uppercase is for short fixed micro-labels, which are ASCII-safe).
  Date inputs pin `lang="en-CA"` for a stable ISO placeholder.
- **Reduced motion.** Section 6: `prefers-reduced-motion` guards on all new
  or modified animation.
- **Semantics already in place that must survive edits:** `role="dialog"` +
  `aria-modal` on modal backdrops, `aria-label` on every icon-only button
  (paired with `title`), `role="tablist"`/`tab`/`aria-selected` on segment
  controls, table headers as real `th`, SVG gauges `aria-hidden` with the
  value present as text, `.status` pill text readable without color (the
  dot repeats the hue, never the sole signal... the label text itself is the
  signal; color is reinforcement).
- **Keyboard.** Enter submits the download form; every grid action is a
  real `<button>`; modal close buttons are reachable; focus must land on
  modals when opened (backdrop `tabindex="0"` pattern).

### 8.2 Accepted debt

| ID | Item | Reason accepted | Removal plan |
|---|---|---|---|
| (none) | | | |

The table is genuinely empty: no deviation from this contract is accepted.
Pre-baseline legacy states documented above (phantom tokens, dead selectors,
raw-value families, missing reduced-motion guards, contrast tight spots) are
recorded as facts with mandatory migration-on-touch rules; their repair is
scheduled by the plan's structural repair tasks, not waived here. Add a row
only when a maintainer explicitly decides to keep a deviation; an empty table
is the goal state, not a placeholder.
