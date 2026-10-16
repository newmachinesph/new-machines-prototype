import { describe, expect, it } from "vitest";
import { ago, agoParts, businessDay, date, dateTime, money, time, timeSec, until, untilParts } from "./format";

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
  it("labels a time in the business time zone with its short name", () => {
    expect(time("2026-10-12T16:40:00Z")).toBe("9:40 AM PT");
    expect(dateTime("2026-10-12T16:40:00Z")).toBe("Oct 12, 9:40 AM PT");
    expect(time("2026-10-12T16:40:00Z", undefined, "ja-JP")).toBe("9:40 太平洋時間");
    expect(dateTime("2026-10-12T16:40:00Z", undefined, "ja-JP")).toBe("10月12日 9:40 太平洋時間");
    // The reviewer portal's zone is named the same way; a timeline names its zone once, above its times.
    expect(dateTime("2026-10-12T16:40:00Z", "Asia/Manila")).toBe("Oct 13, 12:40 AM Manila time");
    expect(dateTime("2026-10-12T16:40:00Z", "Asia/Manila", "ja-JP")).toBe("10月13日 0:40 マニラ時間");
    expect(timeSec("2026-10-12T16:40:05Z")).toBe("9:40:05 AM");
    // The day a time falls on there: early UTC morning is still the evening before.
    expect(businessDay("2026-10-13T05:00:00Z")).toBe("2026-10-12");
  });

  it("hands relative time to a translator as a key and values", () => {
    const tr = (key: string, values?: Record<string, number>) => `${key}:${JSON.stringify(values ?? {})}`;
    expect(agoParts("2026-10-12T16:10:00Z", tr)).toBe('minAgo:{"n":30}');
    expect(agoParts("2026-10-11T16:40:00Z", tr)).toBe("yesterday:{}");
    expect(untilParts("2026-10-12T18:55:00Z", tr)).toBe('hMinLeft:{"h":2,"m":15}');
    expect(untilParts("2026-10-12T16:00:00Z", tr)).toBe("overdue:{}");
  });
});
