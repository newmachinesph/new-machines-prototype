import { describe, expect, it } from "vitest";
import { safeNext, signInHref } from "./next-path";

describe("safeNext", () => {
  it.each([
    "/app",
    "/app/runs/run_1042?x=1",
    "/work",
    "/work/tasks/ht_011",
    "/app?tab=all",
    "/studio",
    "/studio/packs/acme--invoices",
  ])("accepts %s", (path) => {
    expect(safeNext(path)).toBe(path);
  });

  it.each([
    "//evil.com",
    "/\\evil.com",
    "https://x",
    "javascript:alert(1)",
    "/app/redirect?to=https://evil.com",
    "/app\\..\\evil",
    "/app/\tx",
    "/application",
    "/studios",
    "/",
    "/settings",
    "app",
    "",
    null,
    undefined,
  ])("rejects %s", (path) => {
    expect(safeNext(path)).toBeNull();
  });
});

describe("signInHref", () => {
  it("carries a safe deep link as an encoded next", () => {
    expect(signInHref("/app/runs/run_1042?x=1")).toBe("/?next=%2Fapp%2Fruns%2Frun_1042%3Fx%3D1");
  });

  it("drops an unsafe path", () => {
    expect(signInHref("//evil.com")).toBe("/");
  });
});
