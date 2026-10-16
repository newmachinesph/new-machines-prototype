import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";
import type { MarketplaceListing } from "@/lib/api/gen/types.gen";
import en from "../../messages/en.json";
import ja from "../../messages/ja.json";
import { money } from "./format";
import { feeLabel } from "./listing-fee";

const t = createTranslator({ locale: "en", messages: en, namespace: "listedMarket" });
const tJa = createTranslator({ locale: "ja", messages: ja, namespace: "listedMarket" });
const usd = (m: MarketplaceListing["fee"]) => money(m, {}, "en-US");
const listing = (over: Partial<MarketplaceListing>): MarketplaceListing => ({
  listingId: "lst_1",
  publisher: "Harbor Cafe",
  fee: { amountMinor: 0, currency: "USD" },
  feeUnit: "run",
  version: 1,
  ...over,
});

describe("feeLabel", () => {
  it("says No fee for a zero fee", () => {
    expect(feeLabel(t, listing({}), usd)).toBe("No fee");
  });
  it("prices a run in dollars", () => {
    expect(feeLabel(t, listing({ fee: { amountMinor: 250, currency: "USD" } }), usd)).toBe("$2.50 per run");
  });
  it("prices a call in dollars", () => {
    expect(feeLabel(t, listing({ fee: { amountMinor: 30, currency: "USD" }, feeUnit: "call" }), usd)).toBe(
      "$0.30 per call",
    );
  });
  it("uses the caller's formatter and translator, so Japanese reads in Japanese", () => {
    const label = feeLabel(tJa, listing({ fee: { amountMinor: 250, currency: "USD" } }), (m) => money(m, {}, "ja-JP"));
    expect(label).toBe("1回の実行あたり$2.50");
  });
});
