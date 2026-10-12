import { describe, expect, it } from "vitest";
import type { Incident } from "@/lib/api/gen/types.gen";
import { nextStatuses, sortIncidents } from "./incidents";

const inc = (id: string, status: Incident["status"], startedAt: string): Incident => ({
  id,
  title: id,
  severity: "sev3",
  status,
  startedAt,
  services: [],
  updates: [],
});

describe("incidents", () => {
  it("offers only the statuses the API accepts next", () => {
    expect(nextStatuses("investigating")).toEqual(["investigating", "monitoring", "resolved"]);
    expect(nextStatuses("monitoring")).toEqual(["monitoring", "resolved"]);
    expect(nextStatuses("resolved")).toEqual([]);
  });
  it("puts open incidents first, newest first within each group", () => {
    const sorted = sortIncidents([
      inc("old-resolved", "resolved", "2026-10-01T00:00:00Z"),
      inc("old-open", "monitoring", "2026-10-02T00:00:00Z"),
      inc("new-resolved", "resolved", "2026-10-10T00:00:00Z"),
      inc("new-open", "investigating", "2026-10-12T00:00:00Z"),
    ]);
    expect(sorted.map((i) => i.id)).toEqual(["new-open", "old-open", "new-resolved", "old-resolved"]);
  });
});
