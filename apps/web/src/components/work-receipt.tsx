"use client";

import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import type { FeeItem } from "@/lib/api/gen";
import { isFinishedRun, type RunStatus } from "@/lib/types";
import { useReceipt } from "@/lib/queries/runs";
import { useFormat } from "@/lib/use-format";
import { PublisherFeeRows } from "./publisher-fee-rows";
import { CollapsibleSection, TechnicalDetails } from "./run-disclosures";
import { Id, KeyValues, Pill, SimTag } from "./ui";

const HASH_PREFIX = 12;

/** The definition kinds a receipt pins, each with a label in the messages (`run.view.receipt.kinds`). */
const KNOWN_KINDS = [
  "pack",
  "workflow",
  "contract",
  "agent",
  "connector",
  "decision_rules",
  "memory_space",
  "schema",
  "models",
  "taxonomy",
] as const;
const isKnownKind = (kind: string): kind is (typeof KNOWN_KINDS)[number] =>
  (KNOWN_KINDS as readonly string[]).includes(kind);

function PublisherFees({ fees }: { fees: FeeItem[] }) {
  const t = useTranslations("publisherFees");
  const { money } = useFormat();
  // The total assumes one currency (USD only today).
  const total = {
    amountMinor: fees.reduce((sum, f) => sum + f.amount.amountMinor, 0),
    currency: fees[0]!.amount.currency,
  };
  return (
    <section className="mb-3 border-t border-rule pt-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="label">{t("title")}</h3>
        <SimTag>{t("simulated")}</SimTag>
      </div>
      <PublisherFeeRows fees={fees} />
      <div className="flex justify-between border-t border-rule pt-1.5 text-xs font-medium">
        <span>{t("total")}</span>
        <span className="tnum">{money(total)}</span>
      </div>
    </section>
  );
}

/** The hash-chained record of a real run. Fixture runs have no receipt, so nothing renders for them. */
export function WorkReceipt({ runId, status, id }: { runId: string; status: RunStatus; id?: string }) {
  const t = useTranslations("run.view.receipt");
  const query = useReceipt(runId, status);
  const r = query.data;
  if (!r) return null;
  // A kind the interface has no words for yet (added to the API later) shows as sent.
  const kindLabel = (kind: string) => (isKnownKind(kind) ? t(`kinds.${kind}`) : kind);
  // `verified` is the chain recomputed now: while the run still writes to it, that is the chain so far.
  const verified = isFinishedRun(status) ? t("verified") : t("verifiedSoFar");

  return (
    <CollapsibleSection
      id={id}
      data-tour="run-receipt"
      title={t("title")}
      aside={
        <Pill tone={r.verified ? "machine" : "blocked"}>
          {r.verified ? <ShieldCheck className="size-3" aria-hidden /> : <ShieldAlert className="size-3" aria-hidden />}
          {r.verified ? verified : t("notVerified")}
        </Pill>
      }
    >
      <div className="px-5 py-2">
        <KeyValues rows={[{ label: t("entries"), value: <span className="tnum">{r.entries}</span> }]} />
        {r.fees && r.fees.length > 0 ? <PublisherFees fees={r.fees} /> : null}
        <p className="py-2 text-xs leading-relaxed text-muted">{t("help")}</p>
        <TechnicalDetails
          className="mb-3"
          rows={[
            { label: t("headHash"), value: r.headHash.slice(0, HASH_PREFIX) },
            ...(r.pinned.length > 0
              ? [
                  {
                    label: t("pinned"),
                    value: (
                      <ul className="space-y-1">
                        {r.pinned.map((p) => (
                          <li key={`${p.kind}:${p.key}`} className="flex flex-wrap items-baseline gap-x-2">
                            <span className="text-muted">{kindLabel(p.kind)}</span>
                            <Id className="text-[11px] break-all">{p.key}</Id>
                            <span className="tnum text-grey-700">{t("version", { version: p.version })}</span>
                          </li>
                        ))}
                      </ul>
                    ),
                  },
                ]
              : []),
          ]}
        />
      </div>
    </CollapsibleSection>
  );
}
