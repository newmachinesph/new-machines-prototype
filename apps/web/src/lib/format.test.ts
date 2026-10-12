import { describe, expect, it } from "vitest";
import { ago, agoParts, date, money, until, untilParts } from "./format";

describe("format", () => {
  it("formats minor units as dollars", () => {
    expect(money(25000)).toBe("$250.00");
    expect(money(-940)).toBe("−$9.40");
  });
  it("describes relative time against the demo clock", () => {
    expect(ago("2026-10-12T16:10:00Z")).toBe("30 min ago");
    expect(until("2026-10-12T18:40:00Z")).toBe("2 h left");
  });
  it("keeps money in dollars and dates short in Japanese", () => {
    expect(money(940, {}, "ja-JP")).toBe("$9.40");
    expect(date("2026-10-11T16:12:30Z", undefined, "ja-JP")).toBe("10月11日");
  });
  it("hands relative time to a translator as a key and values", () => {
    const tr = (key: string, values?: Record<string, number>) => `${key}:${JSON.stringify(values ?? {})}`;
    expect(agoParts("2026-10-12T16:10:00Z", tr)).toBe('minAgo:{"n":30}');
    expect(agoParts("2026-10-11T16:40:00Z", tr)).toBe("yesterday:{}");
    expect(untilParts("2026-10-12T18:55:00Z", tr)).toBe('hMinLeft:{"h":2,"m":15}');
    expect(untilParts("2026-10-12T16:00:00Z", tr)).toBe("overdue:{}");
  });
});
