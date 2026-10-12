"use client";

import { useTranslations } from "next-intl";
import { CONTRACT_DETAIL, toApiError } from "./errors";

/**
 * The words to show for a failed request. Errors the web app raises itself (offline, unexpected data,
 * anything unknown) are translated; the API's own problem detail is data and is shown as sent.
 */
export function useErrorText() {
  const t = useTranslations("errors");
  return (error: unknown): string => {
    const e = toApiError(error);
    if (e.code === "UNREACHABLE") return t("unreachable");
    if (e.code === "ERROR") return t("generic");
    if (e.code === "CONTRACT" && e.detail === CONTRACT_DETAIL) return t("contract");
    return e.detail;
  };
}
