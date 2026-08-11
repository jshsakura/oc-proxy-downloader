import { describe, expect, it } from "vitest";

import {
  ACTIVE_STATUSES,
  countActiveByStatus,
  countLive,
  isLiveStatus,
  truncateMiddle,
} from "../src/lib/grid.js";

/**
 * Both helpers here shipped wrong, and both times a person found it by looking
 * at a screenshot rather than a test failing.
 */

describe("what counts as running", () => {
  it("counts a transferring row", () => {
    expect(isLiveStatus("downloading")).toBe(true);
  });

  it("counts a row waiting its turn — queued is still progress", () => {
    expect(isLiveStatus("pending")).toBe(true);
    expect(isLiveStatus("waiting")).toBe(true);
  });

  it.each(["stopped", "failed", "done"])(
    "does not count %s — nothing is happening to it",
    (status) => {
      expect(isLiveStatus(status)).toBe(false);
    },
  );

  it("is case-insensitive, since SSE and the API disagree on case", () => {
    expect(isLiveStatus("DOWNLOADING")).toBe(true);
    expect(isLiveStatus("Parsing")).toBe(true);
  });

  it.each([null, undefined, "", 0])("treats %s as not running", (status) => {
    expect(isLiveStatus(status)).toBe(false);
  });

  it("reports zero for a queue of 262 rows where none are moving", () => {
    // The exact shape that read as "진행중 262" with no speed anywhere.
    const rows = [
      ...Array(250).fill({ status: "stopped" }),
      ...Array(12).fill({ status: "failed" }),
    ];

    expect(countLive(rows)).toBe(0);
    expect(rows.length).toBe(262);
  });

  it("sums the live statuses out of the stats map", () => {
    const byStatus = {
      done: 1902, stopped: 247, failed: 12, downloading: 2, parsing: 1,
    };

    expect(countActiveByStatus(byStatus)).toBe(3);
  });

  it("survives a stats map that is missing keys entirely", () => {
    expect(countActiveByStatus({})).toBe(0);
    expect(countActiveByStatus(undefined)).toBe(0);
  });

  it("does not treat failure as progress", () => {
    // App.svelte has its own isActiveStatus that includes `failed` on purpose,
    // mirroring the backend's active-list filter. Confusing the two is what put
    // stopped rows in the "in progress" count.
    expect(ACTIVE_STATUSES).not.toContain("failed");
    expect(ACTIVE_STATUSES).not.toContain("stopped");
  });
});

describe("shortening a release name", () => {
  const LONG =
    "G-MODE Archives+ Detective Ryosuke Kiseigawa Case Files Vol. 13 Twilight is a Lapis Lazuli Recollection [010000901D8E8000][v0][Base].rar";

  it("leaves a short name alone", () => {
    expect(truncateMiddle("Hollow Knight.nsp", 42)).toBe("Hollow Knight.nsp");
  });

  it("keeps the end, which is where Base and UPD are told apart", () => {
    const out = truncateMiddle(LONG, 42);

    expect(out).toContain("[Base].rar");
    expect(out.length).toBeLessThanOrEqual(42);
  });

  it("keeps the beginning too, so the title is still recognisable", () => {
    expect(truncateMiddle(LONG, 42).startsWith("G-MODE")).toBe(true);
  });

  it("distinguishes two builds that differ only at the tail", () => {
    // The failure that started this: both rendered as an identical prefix.
    const base = "Some Very Long Game Title Goes Here [0100ABC][v0][Base].rar";
    const upd = "Some Very Long Game Title Goes Here [0100ABC][v196608][UPD].rar";

    expect(truncateMiddle(base, 42)).not.toBe(truncateMiddle(upd, 42));
  });

  it("marks the cut so a shortened name is not mistaken for the real one", () => {
    expect(truncateMiddle(LONG, 42)).toContain("…");
  });

  it.each([null, undefined, ""])("passes %s through untouched", (name) => {
    expect(truncateMiddle(name, 42)).toBe(name);
  });

  it("still keeps both ends at the tighter phone cap", () => {
    const out = truncateMiddle(LONG, 42);
    const wide = truncateMiddle(LONG, 88);

    expect(out.length).toBeLessThan(wide.length);
    expect(wide).toContain("[Base].rar");
  });
});
