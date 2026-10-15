/** Where sign-in lands when there is no safe `next`: the business workspace, or the portal for a reviewer. */
export const DEFAULT_AFTER_SIGN_IN = "/app";
export const REVIEWER_AFTER_SIGN_IN = "/work";

export type SignedInArea = "app" | "work" | "studio";
const SIGNED_IN_AREAS: SignedInArea[] = ["app", "work", "studio"];

/** The signed-in area (`/app`, `/work` or `/studio`) a path belongs to, or null outside them. */
export function signedInArea(path: string): SignedInArea | null {
  return (
    SIGNED_IN_AREAS.find((a) => path === `/${a}` || path.startsWith(`/${a}/`) || path.startsWith(`/${a}?`)) ?? null
  );
}

/**
 * The `next` path after sign-in, or null when it is unsafe. Safe means a same-origin path (one leading `/`,
 * not `//` or `/\`, no scheme, no backslash or control character) inside a signed-in area (`/app`, `/work` or
 * `/studio`), so a crafted link can't send anyone to another site.
 */
export function safeNext(raw: string | null | undefined): string | null {
  if (!raw || !raw.startsWith("/") || raw.startsWith("//") || raw.startsWith("/\\")) return null;
  if (raw.includes("://") || [...raw].some((c) => c < " " || c === "\\")) return null;
  return signedInArea(raw) ? raw : null;
}

/** The landing page, with a `next` that brings the visitor back to `path` (path and search) after sign-in. */
export function signInHref(path: string): string {
  return safeNext(path) ? `/?next=${encodeURIComponent(path)}` : "/";
}
