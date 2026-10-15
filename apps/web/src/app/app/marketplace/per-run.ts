"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";
import { useFormat } from "@/lib/use-format";
import type { Pack } from "@/lib/types";

/**
 * A pack's estimated agent and tool cost per run as one figure: a range, one amount when the ends meet, or
 * null when the estimate is zero. The API sends 0 when the contract sets no maximum, so callers say
 * "Price not set", never "Free".
 */
export function usePerRunPrice() {
  const t = useTranslations("marketplace.price");
  const { money } = useFormat();
  return useCallback(
    (estimate: Pack["estimate"]): string | null => {
      const { aiMin, aiMax } = estimate;
      if (aiMax.amountMinor <= 0) return null;
      if (aiMin.amountMinor === aiMax.amountMinor) return money(aiMax);
      return t("range", { min: money(aiMin), max: money(aiMax) });
    },
    [t, money],
  );
}
