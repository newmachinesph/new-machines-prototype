import { afterEach, describe, expect, it, vi } from "vitest";
import { isSecureUrl, leaveFor } from "./navigate";

describe("leaveFor", () => {
  const assign = vi.fn();
  const location = window.location;
  afterEach(() => {
    assign.mockReset();
    Object.defineProperty(window, "location", { value: location, configurable: true });
  });
  const stubLocation = () => Object.defineProperty(window, "location", { value: { assign }, configurable: true });

  it("sends the browser to a secure web address", () => {
    stubLocation();
    expect(leaveFor("https://connect.example/x?y=1")).toBe(true);
    expect(assign).toHaveBeenCalledWith("https://connect.example/x?y=1");
  });

  it.each(["javascript:alert(1)", "http://connect.example/x", "connect.example", "", "data:text/html,hi"])(
    "stays put for %j",
    (url) => {
      stubLocation();
      expect(leaveFor(url)).toBe(false);
      expect(assign).not.toHaveBeenCalled();
    },
  );
});

describe("isSecureUrl", () => {
  it("accepts only https", () => {
    expect(isSecureUrl("https://a.example")).toBe(true);
    expect(isSecureUrl("HTTPS://a.example")).toBe(true);
    expect(isSecureUrl("ftp://a.example")).toBe(false);
    expect(isSecureUrl("not a url")).toBe(false);
  });
});
