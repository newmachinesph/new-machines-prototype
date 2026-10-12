import { describe, expect, it } from "vitest";
import { safeNext, signInHref } from "./next-path";

describe("safeNext", () => {
  it.each([
    "/command",
    "/tenants/org_hp01?tab=audit",
    "/audit",
    "/marketplace/shipping-exceptions",
    "/runs?status=FAILED",
  ])("accepts %s", (path) => {
    expect(safeNext(path)).toBe(path);
  });

  it.each([
    "//evil.com",
    "/\evil.com",
    "https://x",
    "javascript:alert(1)",
    "/command/redirect?to=https://evil.com",
    "/tenants\..\evil",
    "/command/\tx",
    "/commander",
    "/",
    "/app",
    "command",
    "",
    null,
    undefined,
  ])("rejects %s", (path) => {
    expect(safeNext(path)).toBeNull();
  });
});

describe("signInHref", () => {
  it("carries a safe deep link as an encoded next", () => {
    expect(signInHref("/tenants/org_hp01?x=1")).toBe("/?next=%2Ftenants%2Forg_hp01%3Fx%3D1");
  });

  it("drops an unsafe path", () => {
    expect(signInHref("//evil.com")).toBe("/");
  });
});
