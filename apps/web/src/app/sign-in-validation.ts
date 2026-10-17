import type { AuthErrorKey } from "@/lib/auth/messages";

/** The shortest password a new account may have. The sign-in service's own floor is lower. */
export const MIN_PASSWORD_LENGTH = 8;
// Catches a name typed into the email box; the sign-in service does the real check.
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export type Mode = "signIn" | "create";
export type Field = "name" | "email" | "password";
export type Values = Record<Field, string>;
/** Keys under `landing` that say what is wrong with a field. */
export type FieldError =
  | "signIn.emailRequired"
  | "signIn.passwordRequired"
  | "createAccount.nameRequired"
  | "createAccount.emailInvalid"
  | "createAccount.passwordShort";
export type FieldErrors = Partial<Record<Field, FieldError>>;

/** The fields in reading order, which is the order the first wrong one is focused in. */
export const FIELDS: readonly Field[] = ["name", "email", "password"];

/** What is wrong with the submitted fields. Sign-in only asks that they are filled in. */
export function validate(mode: Mode, v: Values): FieldErrors {
  const errors: FieldErrors = {};
  if (mode === "create" && v.name === "") errors.name = "createAccount.nameRequired";
  if (v.email === "") errors.email = "signIn.emailRequired";
  else if (mode === "create" && !EMAIL_SHAPE.test(v.email)) errors.email = "createAccount.emailInvalid";
  if (v.password === "") errors.password = "signIn.passwordRequired";
  else if (mode === "create" && v.password.length < MIN_PASSWORD_LENGTH)
    errors.password = "createAccount.passwordShort";
  return errors;
}

/** The field a sign-in service's error is about, when it is about one; the others are about the attempt. */
export function fieldOfError(key: AuthErrorKey): Field | null {
  switch (key) {
    case "createAccount.emailInUse":
    case "createAccount.invalidEmail":
      return "email";
    case "createAccount.weakPassword":
      return "password";
    default:
      return null;
  }
}
