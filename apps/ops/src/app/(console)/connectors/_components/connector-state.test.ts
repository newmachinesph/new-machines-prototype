import { describe, expect, it } from "vitest";
import { describeChanges, diffDefaults, isHighErrorRate } from "./connector-state";

const base = { read: "permit", write: "require_approval", delete: "deny", money: "deny" } as const;

describe("diffDefaults", () => {
  it("returns nothing when the defaults match", () => {
    expect(diffDefaults(base, { ...base })).toEqual([]);
  });

  it("lists only changed action classes, in display order", () => {
    const changes = diffDefaults(base, { ...base, money: "require_approval", write: "permit" });
    expect(changes.map((c) => c.key)).toEqual(["write", "money"]);
    expect(changes[1]).toMatchObject({ from: "deny", to: "require_approval" });
  });
});

describe("describeChanges", () => {
  it("names each change in plain words", () => {
    const text = describeChanges(diffDefaults(base, { ...base, delete: "require_approval" }));
    expect(text).toBe("Delete: deny to require approval.");
  });
});

describe("isHighErrorRate", () => {
  it("flags 5% and above only", () => {
    expect(isHighErrorRate(0.049)).toBe(false);
    expect(isHighErrorRate(0.05)).toBe(true);
    expect(isHighErrorRate(0.2)).toBe(true);
  });
});
