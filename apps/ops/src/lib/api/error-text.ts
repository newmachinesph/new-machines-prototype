import { CONTRACT_DETAIL, toApiError } from "./errors";

const UNREACHABLE = "Can't reach New Machines. Check your connection and retry.";
const GENERIC = "Something went wrong.";

/** The plain words for an error the console raised itself, or the API's own problem detail as sent. */
export function errorText(error: unknown): string {
  const e = toApiError(error);
  if (e.code === "UNREACHABLE") return UNREACHABLE;
  if (e.code === "ERROR") return GENERIC;
  if (e.code === "CONTRACT" && e.detail === CONTRACT_DETAIL) return CONTRACT_DETAIL;
  return e.detail;
}
