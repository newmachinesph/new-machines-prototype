/** Keys under `errors.signIn` in the message files. */
export const SIGN_IN_ERRORS = ["mismatch", "tooManyAttempts", "offline", "googleIncomplete"] as const;
export type SignInError = (typeof SIGN_IN_ERRORS)[number];

/** Keys under `errors.createAccount` in the message files. */
export const CREATE_ACCOUNT_ERRORS = [
  "emailInUse",
  "invalidEmail",
  "weakPassword",
  "tooManyAttempts",
  "offline",
  "failed",
] as const;
export type CreateAccountError = (typeof CREATE_ACCOUNT_ERRORS)[number];

/** A sign-in or create-account message, relative to `errors`. */
export type AuthErrorKey = `signIn.${SignInError}` | `createAccount.${CreateAccountError}`;

const codeOf = (e: unknown) => (typeof e === "object" && e !== null && "code" in e ? String(e.code) : "");

/** The message key for a failed sign-in, or null when the user simply closed the popup. */
export function signInMessage(how: "google" | "email", e: unknown): SignInError | null {
  switch (codeOf(e)) {
    case "auth/popup-closed-by-user":
    case "auth/cancelled-popup-request":
      return null;
    case "auth/invalid-credential":
    case "auth/wrong-password":
    case "auth/user-not-found":
      return "mismatch";
    case "auth/too-many-requests":
      return "tooManyAttempts";
    case "auth/network-request-failed":
      return "offline";
    default:
      return how === "google" ? "googleIncomplete" : "mismatch";
  }
}

/** The message key for a failed account creation. Nothing beyond these is ever shown. */
export function createAccountMessage(e: unknown): CreateAccountError {
  switch (codeOf(e)) {
    case "auth/email-already-in-use":
      return "emailInUse";
    case "auth/invalid-email":
      return "invalidEmail";
    case "auth/weak-password":
      return "weakPassword";
    case "auth/too-many-requests":
      return "tooManyAttempts";
    case "auth/network-request-failed":
      return "offline";
    default:
      return "failed";
  }
}
