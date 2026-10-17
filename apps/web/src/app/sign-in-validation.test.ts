import { describe, expect, it } from "vitest";
import { fieldOfError, MIN_PASSWORD_LENGTH, validate } from "./sign-in-validation";

describe("validate", () => {
  it("only asks a sign-in to be filled in", () => {
    expect(validate("signIn", { name: "", email: "", password: "" })).toEqual({
      email: "signIn.emailRequired",
      password: "signIn.passwordRequired",
    });
    expect(validate("signIn", { name: "", email: "nora", password: "x" })).toEqual({});
  });

  it("asks a new account for a name, a real email and a long enough password", () => {
    expect(validate("create", { name: "", email: "nora", password: "x".repeat(MIN_PASSWORD_LENGTH - 1) })).toEqual({
      name: "createAccount.nameRequired",
      email: "createAccount.emailInvalid",
      password: "createAccount.passwordShort",
    });
    expect(validate("create", { name: "Nora", email: "", password: "" })).toEqual({
      email: "signIn.emailRequired",
      password: "signIn.passwordRequired",
    });
    expect(
      validate("create", { name: "Nora", email: "nora@example.com", password: "x".repeat(MIN_PASSWORD_LENGTH) }),
    ).toEqual({});
  });
});

describe("fieldOfError", () => {
  it("knows which sign-in service errors are about a field", () => {
    expect(fieldOfError("createAccount.emailInUse")).toBe("email");
    expect(fieldOfError("createAccount.invalidEmail")).toBe("email");
    expect(fieldOfError("createAccount.weakPassword")).toBe("password");
    expect(fieldOfError("createAccount.tooManyAttempts")).toBeNull();
    expect(fieldOfError("createAccount.offline")).toBeNull();
    expect(fieldOfError("signIn.mismatch")).toBeNull();
  });
});
