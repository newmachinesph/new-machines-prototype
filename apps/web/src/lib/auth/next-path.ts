/** Where sign-in lands when there is no safe `next`. */
export const DEFAULT_AFTER_SIGN_IN = "/app";

const SIGNED_IN_AREAS = ["/app", "/work"];

/**
 * The `next` path after sign-in, or null when it is unsafe. Safe means a same-origin path (one leading `/`,
 * not `//` or `/\`, no scheme, no backslash or control character) inside a signed-in area (`/app` or `/work`),
 * so a crafted link can't send anyone to another site.
 */
export function safeNext(raw: string | null | undefined): string | null {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return null;
  if (raw.includes("://") || [...raw].some((c) => c < " " || c === "\\")) return null;
  const inArea = SIGNED_IN_AREAS.some((a) => raw === a || raw.startsWith(`${a}/`) || raw.startsWith(`${a}?`));
  return inArea ? raw : null;
}

/** The landing page, with a `next` that brings the visitor back to `path` (path and search) after sign-in. */
export function signInHref(path: string): string {
  return safeNext(path) ? `/?next=${encodeURIComponent(path)}` : "/";
}
