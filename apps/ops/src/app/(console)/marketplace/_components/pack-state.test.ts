import { describe, expect, it } from "vitest";
import { defaultTab, slugify, SLUG_PATTERN, tabCounts, tabFor, validActions, type PackStatus } from "./pack-state";

describe("validActions", () => {
  it.each<[PackStatus, boolean, string[]]>([
    ["draft", false, ["submit"]],
    ["rejected", false, ["submit"]],
    ["in_review", false, ["approve", "reject"]],
    ["published", false, ["certify", "deprecate"]],
    ["published", true, ["deprecate"]],
    ["deprecated", false, ["republish"]],
  ])("%s (certified %s) allows %j", (status, certified, expected) => {
    expect(validActions(status, certified)).toEqual(expected);
  });
});

describe("tabs", () => {
  it("maps statuses to tabs", () => {
    expect(tabFor("draft")).toBe("drafts");
    expect(tabFor("deprecated")).toBe("retired");
    expect(tabFor("rejected")).toBe("retired");
    expect(tabFor("in_review")).toBe("in_review");
  });

  it("counts per tab", () => {
    const counts = tabCounts([
      { status: "draft" },
      { status: "published" },
      { status: "published" },
      { status: "rejected" },
      { status: "deprecated" },
    ]);
    expect(counts).toEqual({ in_review: 0, published: 2, drafts: 1, retired: 2 });
  });

  it("defaults to in review only when something is waiting", () => {
    expect(defaultTab([{ status: "published" }, { status: "in_review" }])).toBe("in_review");
    expect(defaultTab([{ status: "published" }])).toBe("published");
    expect(defaultTab([])).toBe("published");
  });
});

describe("slugify", () => {
  it("makes kebab-case slugs the API accepts", () => {
    expect(slugify("Invoice Matching (EU)")).toBe("invoice-matching-eu");
    expect(slugify("  Café  orders ")).toBe("cafe-orders");
    expect(SLUG_PATTERN.test(slugify("Refund   Triage 2"))).toBe(true);
  });

  it("returns an empty string when nothing usable remains", () => {
    expect(slugify("***")).toBe("");
  });
});
