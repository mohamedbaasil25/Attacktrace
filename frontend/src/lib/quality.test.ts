import { describe, expect, it } from "vitest";
import { QUALITY_ICON, QUALITY_LABEL, ageLabel } from "./quality";

describe("quality", () => {
  it("has no icon for good, and one for every problem", () => {
    expect(QUALITY_ICON.good).toBeUndefined();
    for (const q of ["stale", "missing", "out_of_range", "frozen"] as const) {
      expect(QUALITY_ICON[q]).toBeDefined();
    }
  });

  it("uses a distinct icon per problem", () => {
    const icons = (["stale", "missing", "out_of_range", "frozen"] as const).map((q) => QUALITY_ICON[q]);
    expect(new Set(icons).size).toBe(4);
  });

  it("labels every quality", () => {
    expect(QUALITY_LABEL.good).toBe("Good");
    expect(QUALITY_LABEL.stale).toBe("Stale");
    expect(QUALITY_LABEL.out_of_range).toBe("Out of range");
  });

  it("formats age in ms below one second, seconds above", () => {
    expect(ageLabel(250)).toBe("250 ms old");
    expect(ageLabel(1500)).toBe("1.5 s old");
    expect(ageLabel(null)).toBe("age unknown");
    expect(ageLabel(undefined)).toBe("age unknown");
  });
});
