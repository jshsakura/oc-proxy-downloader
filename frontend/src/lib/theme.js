import { writable } from "svelte/store";

export const THEMES = [
  "light",
  "dark",
  "dracula",
  "nord",
  "solarized",
  "monokai",
  "ocean",
  "rose",
  "neon",
  "forest",
  "sunset",
  "system",
];

const CLASS_THEMES = THEMES.filter((name) => !["light", "system"].includes(name));

export function normalizeTheme(value) {
  return THEMES.includes(value) ? value : "system";
}

function createThemeStore() {
  const stored = typeof window === "undefined" ? "system" : localStorage.getItem("theme");
  const initialTheme = normalizeTheme(stored);
  const store = writable(initialTheme);
  let currentTheme = initialTheme;
  let mediaQuery;

  function applyTheme(value) {
    if (typeof document === "undefined") return;
    const normalized = normalizeTheme(value);
    const effective = normalized === "system" && mediaQuery?.matches ? "dark" : normalized;

    for (const root of [document.documentElement, document.body]) {
      root.classList.remove(...CLASS_THEMES);
      if (CLASS_THEMES.includes(effective)) root.classList.add(effective);
    }
  }

  function set(value) {
    const normalized = normalizeTheme(value);
    currentTheme = normalized;
    if (typeof window !== "undefined") localStorage.setItem("theme", normalized);
    applyTheme(normalized);
    store.set(normalized);
  }

  if (typeof window !== "undefined") {
    mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
    mediaQuery.addEventListener?.("change", () => {
      if (currentTheme === "system") applyTheme(currentTheme);
    });
    set(initialTheme);
  }

  return { subscribe: store.subscribe, set };
}

export const theme = createThemeStore();
