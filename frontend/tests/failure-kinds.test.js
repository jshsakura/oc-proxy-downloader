import { describe, expect, it } from "vitest";
import ko from "../../backend/locales/ko.json";
import en from "../../backend/locales/en.json";

describe("download failure labels", () => {
  it("has readable Korean and English labels for every new refusal", () => {
    for (const key of ["kind_daily_quota", "kind_slot_busy", "kind_browser_parse"]) {
      expect(ko[key]).toBeTruthy();
      expect(en[key]).toBeTruthy();
      expect(ko[key]).not.toBe(key);
      expect(en[key]).not.toBe(key);
    }
  });
});
