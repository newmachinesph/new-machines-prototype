import { describe, expect, it } from "vitest";
import { formatLimit, fromFieldValue, GUARDRAIL_MAX, toFieldValue } from "./limits";

describe("limits", () => {
  it("formats money limits from minor units", () => {
    expect(formatLimit({ unit: "usd_minor", value: 60000 })).toBe("$600.00");
  });
  it("formats plain limits with their unit", () => {
    expect(formatLimit({ unit: "runs", value: 20 })).toBe("20 runs");
    expect(formatLimit({ unit: "minutes", value: 45 })).toBe("45 minutes");
  });
  it("shows dollars in the field and sends minor units", () => {
    expect(toFieldValue({ unit: "usd_minor", value: 60000 })).toBe("600.00");
    expect(fromFieldValue("usd_minor", "600")).toBe(60000);
    expect(fromFieldValue("usd_minor", "12.34")).toBe(1234);
    expect(fromFieldValue("usd_minor", "250.10")).toBe(25010);
  });
  it("rejects bad dollar input", () => {
    expect(fromFieldValue("usd_minor", "1.234")).toBeNull();
    expect(fromFieldValue("usd_minor", "0x10")).toBeNull();
    expect(fromFieldValue("usd_minor", "1e3")).toBeNull();
    expect(fromFieldValue("usd_minor", "999999999")).toBeNull();
  });
  it("passes whole counts and minutes through", () => {
    expect(fromFieldValue("runs", "25")).toBe(25);
    expect(fromFieldValue("minutes", "45")).toBe(45);
  });
  it("caps counts and minutes at the API's ceiling", () => {
    expect(fromFieldValue("runs", String(GUARDRAIL_MAX))).toBe(GUARDRAIL_MAX);
    expect(fromFieldValue("runs", String(GUARDRAIL_MAX + 1))).toBeNull();
    expect(fromFieldValue("minutes", "50000000")).toBeNull();
  });
  it("rejects fractional, empty, negative and non-numeric counts", () => {
    expect(fromFieldValue("runs", "2.5")).toBeNull();
    expect(fromFieldValue("minutes", "0.5")).toBeNull();
    expect(fromFieldValue("runs", "")).toBeNull();
    expect(fromFieldValue("runs", "-3")).toBeNull();
    expect(fromFieldValue("runs", "abc")).toBeNull();
  });
});
