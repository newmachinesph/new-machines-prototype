/** Keys under `errors.signIn` in the message files. */
export const SIGN_IN_ERRORS = ["mismatch", "tooManyAttempts", "offline", "googleIncomplete"] as const;
export type SignInError = (typeof SIGN_IN_ERRORS)[number];

/** The message key for a failed sign-in, or null when the user simply closed the popup. */
export function signInMessage(how: "google" | "email", e: unknown): SignInError | null {
  const code = typeof e === "object" && e !== null && "code" in e ? String(e.code) : "";
  switch (code) {
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
