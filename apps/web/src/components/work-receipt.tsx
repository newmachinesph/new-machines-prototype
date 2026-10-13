"use client";

import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import type { RunStatus } from "@/lib/types";
import { useReceipt } from "@/lib/queries/runs";
import { Id, KeyValues, Pill, Section } from "./ui";

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

/** The hash-chained record of a real run. Fixture runs have no receipt, so nothing renders for them. */
export function WorkReceipt({ runId, status }: { runId: string; status: RunStatus }) {
  const t = useTranslations("run.view.receipt");
  const query = useReceipt(runId, status);
  const r = query.data;
  if (!r) return null;
  // A kind the interface has no words for yet (added to the API later) shows as sent.
  const kindLabel = (kind: string) => (isKnownKind(kind) ? t(`kinds.${kind}`) : kind);

  return (
    <Section
      title={t("title")}
      aside={
        <Pill tone={r.verified ? "machine" : "blocked"}>
          {r.verified ? <ShieldCheck className="size-3" aria-hidden /> : <ShieldAlert className="size-3" aria-hidden />}
          {r.verified ? t("verified") : t("notVerified")}
        </Pill>
      }
    >
      <div className="px-5 py-2">
        <KeyValues
          rows={[
            { label: t("entries"), value: <span className="tnum">{r.entries}</span> },
            { label: t("headHash"), value: <Id>{r.headHash.slice(0, HASH_PREFIX)}</Id> },
          ]}
        />
        {r.pinned.length > 0 ? (
          <div className="border-t border-rule py-3">
            <h3 className="mb-2 text-xs font-medium text-muted">{t("pinned")}</h3>
            <ul className="space-y-1.5 text-sm">
              {r.pinned.map((p) => (
                <li key={`${p.kind}:${p.key}`} className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0">
                    <span className="text-xs text-muted">{kindLabel(p.kind)}</span>{" "}
                    <Id className="break-all">{p.key}</Id>
                  </span>
                  <span className="tnum shrink-0 text-xs text-grey-700">{t("version", { version: p.version })}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="pb-2 text-xs leading-relaxed text-muted">{t("help")}</p>
      </div>
    </Section>
  );
}
