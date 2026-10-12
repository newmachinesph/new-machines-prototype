import { describe, expect, it } from "vitest";
import { signInMessage } from "./messages";

const err = (code: string) => ({ code });

describe("signInMessage", () => {
  it.each(["auth/popup-closed-by-user", "auth/cancelled-popup-request"])("shows nothing for %s", (code) => {
    expect(signInMessage("google", err(code))).toBeNull();
  });

  it.each(["auth/invalid-credential", "auth/wrong-password", "auth/user-not-found"])(
    "says it did not match for %s",
    (code) => {
      expect(signInMessage("email", err(code))).toBe("mismatch");
    },
  );

  it("explains a network failure", () => {
    expect(signInMessage("email", err("auth/network-request-failed"))).toBe("offline");
  });

  it("explains rate limiting", () => {
    expect(signInMessage("email", err("auth/too-many-requests"))).toBe("tooManyAttempts");
  });

  it("falls back per method for unknown errors", () => {
    expect(signInMessage("google", err("auth/whatever"))).toBe("googleIncomplete");
    expect(signInMessage("email", new Error("boom"))).toBe("mismatch");
  });
});
