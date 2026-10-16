"use client";

import { useTranslations } from "next-intl";
import { useCallback } from "react";
import { useFormat } from "@/lib/use-format";
import type { Pack } from "@/lib/types";

/** What agents and tools cost one run of a pack, as the surfaces show it. */
export type PerRunCost = {
  /** The pack's own price note ("About $0.80 to $3.00 of AI work per run. …"), when it has one. */
  note: string | null;
  /** The catalog's estimate as one figure, a range or one amount, when it is a real estimate. */
  range: string | null;
  /** "Up to $30.00 per run (cap)" when the estimate is only the contract's cap. */
  cap: string | null;
  /** The cap's amount alone, for a caller that words it differently. */
  capAmount: string | null;
};

/**
 * A pack's agent and tool cost per run. The API's estimate for a pack definition runs from 0 to its contract's
 * budget cap, so an estimate starting at 0 is a cap, never shown as a "$0.00–$30.00" price. The typical cost
 * then comes from the pack's price note. With neither, callers say "Usage-based", never "Free".
 */
export function usePerRunCost() {
  const t = useTranslations("marketplace.price");
  const { money } = useFormat();
  return useCallback(
    (pack: Pick<Pack, "estimate" | "priceNote">): PerRunCost => {
      const { aiMin, aiMax } = pack.estimate;
      const isCap = aiMin.amountMinor === 0 && aiMax.amountMinor > 0;
      const capAmount = isCap ? money(aiMax) : null;
      const range =
        isCap || aiMax.amountMinor <= 0
          ? null
          : aiMin.amountMinor === aiMax.amountMinor
            ? money(aiMax)
            : t("range", { min: money(aiMin), max: money(aiMax) });
      return {
        note: pack.priceNote?.trim() || null,
        range,
        cap: capAmount === null ? null : t("cap", { amount: capAmount }),
        capAmount,
      };
    },
    [t, money],
  );
}

/**
 * The sentence of a price note that names an amount, for a card with no room for the whole note: "About $0.80
 * to $3.00 of AI work per run." from "About $0.80 to $3.00 of AI work per run. No reviewer time: …". The whole
 * note when no sentence names one.
 */
export function shortPriceNote(note: string): string {
  // A sentence ends at "." before a space ("$0.80" is not an end) or at "。".
  const sentences = note.split(/(?<=\.)\s+|(?<=。)/).filter((s) => s.trim());
  return sentences.find((s) => /\d/.test(s)) ?? note;
}
