"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";

/** The region codes the platform runs in; their place names are in messages (settings.workspace.places). */
export const REGION_CODES = ["asia-south1", "asia-northeast1", "us-central1"] as const;
export type RegionCode = (typeof REGION_CODES)[number];
export const isRegionCode = (code: string): code is RegionCode => (REGION_CODES as readonly string[]).includes(code);

/**
 * A region as a person reads it, "Mumbai (asia-south1)", the same words as Settings, wherever a pack or an agent
 * says where it processes data. A code the platform does not run in shows as it is.
 */
export function useRegionName() {
  const t = useTranslations("settings.workspace");
  return useCallback(
    (code: string): string => (isRegionCode(code) ? t("regionValue", { place: t(`places.${code}`), code }) : code),
    [t],
  );
}
