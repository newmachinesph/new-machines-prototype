import { describe, expect, it } from "vitest";
import { ago, count, duration, money, pct } from "./format";

describe("format", () => {
  it("formats minor units as dollars, with a true minus", () => {
    expect(money(619400)).toBe("$6,194.00");
    expect(money({ amountMinor: -250, currency: "USD" })).toBe("−$2.50");
    expect(money(100, { sign: true })).toBe("+$1.00");
  });

  it("formats counts and ratios", () => {
    expect(count(12480)).toBe("12,480");
    expect(pct(0.9734)).toBe("97.3%");
    expect(pct(1)).toBe("100%");
  });

  it("says how long ago, relative to the shared now", () => {
    expect(ago("2026-10-12T16:35:00Z")).toBe("5 min ago");
    expect(ago("2026-10-12T13:40:00Z")).toBe("3 h ago");
    expect(ago("2026-10-11T16:40:00Z")).toBe("yesterday");
    expect(ago("2026-10-08T16:40:00Z")).toBe("4 days ago");
  });

  it("formats durations", () => {
    expect(duration(42)).toBe("42s");
    expect(duration(125)).toBe("2m 5s");
    expect(duration(3720)).toBe("1h 2m");
  });
});
