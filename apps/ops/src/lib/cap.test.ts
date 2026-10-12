import { describe, expect, it } from "vitest";
import { capRatio, meterFill } from "./cap";

describe("capRatio", () => {
  it("keeps overspend, floors at 0 and treats a zero cap as full", () => {
    expect(capRatio(31840, 60000)).toBeCloseTo(0.5307, 3);
    expect(capRatio(90000, 60000)).toBe(1.5);
    expect(capRatio(-5, 60000)).toBe(0);
    expect(capRatio(10, 0)).toBe(1);
    expect(capRatio(0, 0)).toBe(1);
  });
  it("clamps the drawable fill at 1", () => {
    expect(meterFill(1.5)).toBe(1);
    expect(meterFill(0.4)).toBe(0.4);
  });
});
