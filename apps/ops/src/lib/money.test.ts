import { describe, expect, it } from "vitest";
import { MAX_MINOR, minorToDollarsInput, parseDollarsToMinor } from "./money";

describe("parseDollarsToMinor", () => {
  it.each([
    ["250", 25000],
    ["250.1", 25010],
    ["250.10", 25010],
    ["0.29", 29],
    ["1.15", 115],
    ["8.2", 820],
    ["0", 0],
    [" 12.50 ", 1250],
    ["100000", MAX_MINOR],
  ])("reads %s as %i minor units", (input, minor) => {
    expect(parseDollarsToMinor(input)).toBe(minor);
  });

  it.each(["", "abc", "0x10", "1e3", "1.005", "-5", "1,000", ".5", "5.", "100000.01"])("rejects %j", (input) => {
    expect(parseDollarsToMinor(input)).toBeNull();
  });

  it("honours a custom ceiling", () => {
    expect(parseDollarsToMinor("10.01", 1000)).toBeNull();
    expect(parseDollarsToMinor("10", 1000)).toBe(1000);
  });
});

describe("minorToDollarsInput", () => {
  it("round-trips through the parser", () => {
    for (const minor of [0, 5, 29, 25010, MAX_MINOR]) {
      expect(parseDollarsToMinor(minorToDollarsInput(minor))).toBe(minor);
    }
  });
});
