import { describe, expect, it } from "vitest";

import { normalizeTheme, THEMES } from "../src/lib/theme.js";

describe("theme normalization", () => {
  it("keeps every supported theme", () => {
    for (const name of THEMES) expect(normalizeTheme(name)).toBe(name);
  });

  it.each([undefined, null, "", "removed-theme", "DARK"])(
    "falls back safely for %s",
    (value) => expect(normalizeTheme(value)).toBe("system"),
  );
});
