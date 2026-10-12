import { describe, expect, it } from "vitest";
import { MAX_CONNECTORS, newPackSchema } from "./new-pack-dialog";

const valid = {
  name: "Dock booking",
  slug: "dock-booking",
  publisher: "Portwise",
  category: "Fulfillment",
  riskClass: "low" as const,
  outcome: "Every pallet has a slot",
  description: "Books slots",
  humanReview: "A planner confirms",
  connectors: [{ app: "Gmail", access: "read" as const }],
  reason: "Pilot",
};

const fails = (over: object) => !newPackSchema.safeParse({ ...valid, ...over }).success;

describe("newPackSchema", () => {
  it("accepts a valid pack", () => {
    expect(newPackSchema.safeParse(valid).success).toBe(true);
  });

  it("matches the API bounds at the limit and one past it", () => {
    expect(fails({ name: "a".repeat(120) })).toBe(false);
    expect(fails({ name: "a".repeat(121) })).toBe(true);
    expect(fails({ slug: "a".repeat(60) })).toBe(false);
    expect(fails({ slug: "a".repeat(61) })).toBe(true);
    expect(fails({ publisher: "a".repeat(121) })).toBe(true);
    expect(fails({ category: "a".repeat(40) })).toBe(false);
    expect(fails({ category: "a".repeat(41) })).toBe(true);
    for (const key of ["outcome", "description", "humanReview"]) {
      expect(fails({ [key]: "a".repeat(1000) })).toBe(false);
      expect(fails({ [key]: "a".repeat(1001) })).toBe(true);
    }
  });

  it("allows at most 20 connectors", () => {
    const rows = (n: number) => Array.from({ length: n }, () => ({ app: "Gmail", access: "read" as const }));
    expect(fails({ connectors: rows(MAX_CONNECTORS) })).toBe(false);
    expect(fails({ connectors: rows(MAX_CONNECTORS + 1) })).toBe(true);
    expect(fails({ connectors: [] })).toBe(true);
  });
});
