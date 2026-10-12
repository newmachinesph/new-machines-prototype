/** The ways a sign-in can fail, each with its own message in SIGN_IN_ERROR_TEXT. */
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

export const SIGN_IN_ERROR_TEXT: Record<SignInError, string> = {
  mismatch: "That email and password did not match. Check them and try again.",
  tooManyAttempts: "Too many attempts. Wait a minute and try again.",
  offline: "Can't reach the sign-in service. Check your connection and try again.",
  googleIncomplete: "Google sign-in did not finish. Try again.",
};
