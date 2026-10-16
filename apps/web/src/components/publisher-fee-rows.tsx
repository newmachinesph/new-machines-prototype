"use client";

import { useTranslations } from "next-intl";
import type { FeeItem } from "@/lib/api/gen";
import { useFormat } from "@/lib/use-format";

/** One row per listing: "{name} by {publisher}", how it was charged, and the amount. Simulated money. */
export function PublisherFeeRows({ fees }: { fees: FeeItem[] }) {
  const t = useTranslations("publisherFees");
  const { money } = useFormat();
  return (
    <ul className="divide-y divide-rule text-xs">
      {fees.map((f) => (
        <li
          key={`${f.listingId}:${f.kind}:${f.unit.amountMinor}`}
          className="flex items-baseline justify-between gap-x-4 py-1.5"
        >
          <span className="min-w-0">
            <span className="block">{t("by", { name: f.name, publisher: f.publisher })}</span>
            <span className="tnum text-muted">
              {f.kind === "pack_run" ? t("perRun") : t("calls", { quantity: f.quantity, unit: money(f.unit) })}
            </span>
          </span>
          <span className="tnum">{money(f.amount)}</span>
        </li>
      ))}
    </ul>
  );
}
