"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useToast } from "@/components/base";
import { Button, Callout, Id, KeyValues, Pill, Section } from "@/components/ui";
import { useErrorText } from "@/lib/api/use-error-text";
import { useDecideApproval } from "@/lib/queries/workspace";
import { useFormat } from "@/lib/use-format";
import type { Approval } from "@/lib/types";

export function ApprovalCard({ approval: a, onDecide }: { approval: Approval; onDecide: () => void }) {
  const t = useTranslations("approvals.card");
  const { dateTime, until } = useFormat();
  const errorText = useErrorText();
  const toast = useToast();
  const approveMutation = useDecideApproval("approve");
  const declineMutation = useDecideApproval("decline");
  // The cache is updated at once and rolled back on error, so the status is the single source of truth.
  const state = a.status === "GRANTED" ? "approved" : a.status === "DECLINED" ? "declined" : "pending";
  const approve = () => {
    onDecide();
    approveMutation.mutate(
      { path: { approval_id: a.id } },
      {
        onSuccess: () => toast(t("approvedToast"), t("approvedToastBody", { to: a.preview.to }), "sim"),
        onError: (e) => toast(t("approveFailed"), errorText(e), "blocked"),
      },
    );
  };
  const decline = () => {
    onDecide();
    declineMutation.mutate(
      { path: { approval_id: a.id } },
      {
        onSuccess: () => toast(t("declinedToast"), t("declinedToastBody")),
        onError: (e) => toast(t("declineFailed"), errorText(e), "blocked"),
      },
    );
  };

  return (
    <Section
      title={a.title}
      aside={
        state === "pending" ? (
          <Pill tone="human" className="whitespace-normal">
            {t("expires", { when: dateTime(a.expiresAt), left: until(a.expiresAt) })}
          </Pill>
        ) : state === "approved" ? (
          <Pill tone="ink">{t("approved")}</Pill>
        ) : (
          <Pill tone="quiet">{t("declined")}</Pill>
        )
      }
    >
      <div className="grid gap-px bg-rule lg:grid-cols-2">
        <div className="bg-paper px-5 py-4">
          <h3 className="label mb-2">{t("emailHeading")}</h3>
          <div className="rounded-[10px] border border-rule">
            <div className="space-y-1 border-b border-rule px-4 py-3 text-sm">
              <div>
                <span className="text-muted">{t("to")} </span>
                {a.preview.to}
              </div>
              <div>
                <span className="text-muted">{t("subject")} </span>
                <span className="font-medium">{a.preview.subject}</span>
              </div>
            </div>
            <p className="px-4 py-3 text-sm leading-relaxed whitespace-pre-line">{a.preview.body}</p>
          </div>
        </div>
        <div className="bg-paper px-5 py-4">
          <h3 className="label mb-1">{t("digestHeading")}</h3>
          <KeyValues rows={a.digest.map((d) => ({ label: d.label, value: d.mono ? <Id>{d.value}</Id> : d.value }))} />
        </div>
      </div>
      <div className="border-t border-rule px-5 py-4">
        {state === "pending" ? (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="max-w-[60ch] text-sm text-muted">{t("pendingNote")}</p>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={decline}>
                {t("decline")}
              </Button>
              <Button onClick={approve}>{t("approve")}</Button>
            </div>
          </div>
        ) : state === "approved" ? (
          <Callout tone="info" title={t("approvedTitle")}>
            {t.rich("recorded", {
              id: a.id,
              hash: "sha256:9f2c…41ad",
              mono: (chunks) => <Id>{chunks}</Id>,
            })}{" "}
            <Link className="link" href={`/app/runs/${a.runId}`}>
              {t("backToRun")}
            </Link>
          </Callout>
        ) : (
          <Callout tone="warn" title={t("declinedTitle")}>
            {t("declinedBody")}{" "}
            <Link className="link" href={`/app/runs/${a.runId}`}>
              {t("backToRun")}
            </Link>
          </Callout>
        )}
      </div>
    </Section>
  );
}
