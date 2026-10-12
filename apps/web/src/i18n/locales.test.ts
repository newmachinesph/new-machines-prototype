import { describe, expect, it } from "vitest";
import { mergeMessages, resolveLocale } from "./locales";

describe("resolveLocale", () => {
  it("accepts supported locales", () => {
    expect(resolveLocale("ja")).toBe("ja");
    expect(resolveLocale("en")).toBe("en");
  });
  it.each([undefined, null, "", "fr", "JA", "ja-JP"])("falls back to English for %s", (v) => {
    expect(resolveLocale(v)).toBe("en");
  });
});

describe("mergeMessages", () => {
  const en = { a: { b: "B", c: "C" }, d: "D", e: { f: "F" } };

  it("falls back to English for a nested key the other language lacks", () => {
    const merged = mergeMessages(en, { a: { b: "ビー" }, d: "ディー" });
    expect(merged).toEqual({ a: { b: "ビー", c: "C" }, d: "ディー", e: { f: "F" } });
  });
  it("falls back for a whole missing namespace", () => {
    expect(mergeMessages(en, {}).e).toEqual({ f: "F" });
  });
  it("ignores keys English does not have, and a string where a namespace is expected", () => {
    expect(mergeMessages(en, { extra: "x", a: "oops" })).toEqual(en);
  });
  it("does not mutate its inputs", () => {
    const own = { a: { b: "ビー" } };
    mergeMessages(en, own);
    expect(en.a.c).toBe("C");
    expect(own).toEqual({ a: { b: "ビー" } });
  });
});
