import { describe, expect, it } from "vitest";
import { safeNext, signInHref, signedInArea } from "./next-path";

describe("signedInArea", () => {
  it.each([
    ["/app", "app"],
    ["/app/runs/run_1042?x=1", "app"],
    ["/work?tab=all", "work"],
    ["/studio/packs/acme--invoices", "studio"],
  ])("names the area of %s", (path, area) => {
    expect(signedInArea(path)).toBe(area);
  });

  it.each(["/", "/application", "/workers", "/settings", "app"])("is null for %s", (path) => {
    expect(signedInArea(path)).toBeNull();
  });
});

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
