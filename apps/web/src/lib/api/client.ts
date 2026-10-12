import { env } from "@/lib/env";
import { client } from "./gen/client.gen";
import { toApiError } from "./errors";

export const ORG_ID = "org_hp01";

type TokenSource = () => Promise<string | null>;
let tokenSource: TokenSource = async () => null;

/** Called by the session provider once Firebase knows the user. */
export function setTokenSource(source: TokenSource) {
  tokenSource = source;
}

type UnauthorizedHandler = () => Promise<void>;
let unauthorizedHandler: UnauthorizedHandler | null = null;
let handling: Promise<void> | null = null;

/** Called by the session provider: on a 401 it signs out, then goes to the landing page. */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  unauthorizedHandler = handler;
}

/** An expired or rejected session. A burst of concurrent 401s runs the handler once. */
export function handleUnauthorized(): Promise<void> {
  if (handling) return handling;
  const run = async () => {
    try {
      if (unauthorizedHandler) await unauthorizedHandler();
      else window.location.replace("/");
    } catch (e) {
      console.error("Sign-out after a 401 failed", e);
      window.location.replace("/");
    }
  };
  // Clear only after the stored promise settles, so a later 401 starts a fresh run.
  handling = run().finally(() => {
    handling = null;
  });
  return handling;
}

const apiOrigin = () => new URL(env.NEXT_PUBLIC_API_URL).origin;

client.setConfig({ baseUrl: env.NEXT_PUBLIC_API_URL, throwOnError: true });

client.interceptors.request.use(async (request) => {
  // Never send the ID token to any origin but our own API.
  if (new URL(request.url).origin !== apiOrigin()) return request;
  const token = await tokenSource();
  if (token) request.headers.set("Authorization", `Bearer ${token}`);
  return request;
});

client.interceptors.error.use((error) => toApiError(error));
