import { describe, expect, it } from "vitest";
import type { OpsAttentionItem } from "@/lib/api/gen/types.gen";
import { CAP_FULL, CAP_WARN, isSimulated, maxHourTotal, sortAttention } from "./logic";

const item = (title: string, severity: OpsAttentionItem["severity"], at: string): OpsAttentionItem => ({
  kind: "incident",
  title,
  detail: "",
  href: "/health",
  severity,
  at,
});

describe("sortAttention", () => {
  it("orders critical, warn, info, then newest first, without mutating the input", () => {
    const input = [
      item("old info", "info", "2026-10-12T10:00:00Z"),
      item("warn", "warn", "2026-10-12T09:00:00Z"),
      item("new info", "info", "2026-10-12T12:00:00Z"),
      item("crit", "critical", "2026-10-11T00:00:00Z"),
    ];
    expect(sortAttention(input).map((i) => i.title)).toEqual(["crit", "warn", "new info", "old info"]);
    expect(input[0].title).toBe("old info");
  });
});

describe("cap thresholds", () => {
  it("warns before the cap is reached", () => {
    expect(CAP_WARN).toBe(0.8);
    expect(CAP_FULL).toBe(1);
    expect(CAP_WARN).toBeLessThan(CAP_FULL);
  });
});

describe("chart helpers", () => {
  it("finds the tallest hour and never returns 0", () => {
    expect(maxHourTotal([])).toBe(1);
    expect(
      maxHourTotal([
        { hour: 0, completed: 3, failed: 1, waiting: 1 },
        { hour: 1, completed: 2, failed: 0, waiting: 0 },
      ]),
    ).toBe(5);
  });
  it("checks simulated fields by name", () => {
    expect(isSimulated(["kpis.runsToday"], "kpis.runsToday")).toBe(true);
    expect(isSimulated(["kpis.runsToday"], "kpis.aiSpendToday")).toBe(false);
  });
});
