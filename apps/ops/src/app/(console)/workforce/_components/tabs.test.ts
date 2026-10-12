import { describe, expect, it } from "vitest";
import type { Reviewer } from "@/lib/api/gen/types.gen";
import { canSetLevel, countByTab, resolveTab } from "./tabs";

const r = (status: Reviewer["status"]) => ({ status }) as Reviewer;

describe("workforce tabs", () => {
  it("counts reviewers by status", () => {
    expect(countByTab([r("applicant"), r("active"), r("active"), r("suspended")])).toEqual({
      applicants: 1,
      active: 2,
      suspended: 1,
    });
  });
  it("defaults to applicants when there are any", () => {
    expect(resolveTab(null, { applicants: 2, active: 5, suspended: 0 })).toBe("applicants");
  });
  it("defaults to active when nobody is waiting", () => {
    expect(resolveTab(null, { applicants: 0, active: 5, suspended: 1 })).toBe("active");
  });
  it("keeps the tab from the URL", () => {
    expect(resolveTab("suspended", { applicants: 3, active: 5, suspended: 0 })).toBe("suspended");
  });
  it("only allows a level change when the level differs", () => {
    expect(canSetLevel("trainee", "trainee")).toBe(false);
    expect(canSetLevel("trainee", "senior")).toBe(true);
  });
});
