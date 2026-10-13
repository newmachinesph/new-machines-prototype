import { describe, expect, it } from "vitest";
import type { AuditEntry } from "@/lib/api/gen/types.gen";
import { filterEntries, targetHref } from "./audit-logic";

const entry = (over: Partial<AuditEntry>): AuditEntry => ({
  id: "a1",
  at: "2026-10-12T10:00:00Z",
  actorEmail: "hana.okada@newmachin.es",
  actorRole: "admin",
  action: "tenant.suspend",
  targetType: "tenant",
  targetId: "org_hp01",
  reason: "Chargeback dispute",
  summary: "Suspended Harbor & Pine",
  ...over,
});

describe("targetHref", () => {
  it("links each target type to its page", () => {
    expect(targetHref("tenant", "org_hp01")).toBe("/tenants/org_hp01");
    expect(targetHref("pack", "invoice-chaser")).toBe("/marketplace/invoice-chaser");
    expect(targetHref("connector", "gmail")).toBe("/connectors?c=gmail");
    expect(targetHref("reviewer", "rev_1")).toBe("/workforce");
    expect(targetHref("guardrail", "pause_all_runs")).toBe("/guardrails");
    expect(targetHref("incident", "inc_0042")).toBe("/health");
    expect(targetHref("definition", "schema/order-payment-reconciliation/input")).toBe(
      "/definitions/schema/order-payment-reconciliation/input",
    );
    expect(targetHref("memory", "mem_12")).toBe("/memory");
  });
});

describe("filterEntries", () => {
  const rows = [
    entry({}),
    entry({ id: "a2", actorEmail: "marco@newmachin.es", reason: "Quarter-end", summary: "Raised cap" }),
  ];
  it("returns everything for an empty query", () => {
    expect(filterEntries(rows, "  ")).toHaveLength(2);
  });
  it("matches summary, reason and actor email, ignoring case", () => {
    expect(filterEntries(rows, "CHARGEBACK").map((r) => r.id)).toEqual(["a1"]);
    expect(filterEntries(rows, "raised").map((r) => r.id)).toEqual(["a2"]);
    expect(filterEntries(rows, "marco@").map((r) => r.id)).toEqual(["a2"]);
  });
  it("does not match the action or target id", () => {
    expect(filterEntries(rows, "org_hp01")).toHaveLength(0);
  });
});
