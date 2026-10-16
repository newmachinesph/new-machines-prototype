import { useTranslations } from "next-intl";
import type { MarketplaceListing } from "@/lib/api/gen/types.gen";
import { useFormat } from "@/lib/use-format";

/** The `listedMarket` translator, or any with the same keys. */
type FeeT = (key: "noFee" | "perRun" | "perCall", values?: { amount: string }) => string;

/** A listing's fee in words: "No fee", "$2.50 per run" or "$0.30 per call". `format` renders the amount in the interface language. */
export function feeLabel(
  t: FeeT,
  listing: Pick<MarketplaceListing, "fee" | "feeUnit">,
  format: (m: MarketplaceListing["fee"]) => string,
): string {
  if (listing.fee.amountMinor <= 0) return t("noFee");
  return t(listing.feeUnit === "call" ? "perCall" : "perRun", { amount: format(listing.fee) });
}

/** The entry point for components: `feeLabel` bound to the interface language's translator and number format. */
export function useFeeLabel() {
  const t = useTranslations("listedMarket");
  const { money: fmt } = useFormat();
  return (listing: Pick<MarketplaceListing, "fee" | "feeUnit">) => feeLabel(t, listing, fmt);
}
