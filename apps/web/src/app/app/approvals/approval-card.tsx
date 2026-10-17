"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import type { ReactNode } from "react";
import { useToast } from "@/components/base";
import { Button, Callout, Id, KeyValues, Pill, Section, SimTag } from "@/components/ui";
import { useErrorText } from "@/lib/api/use-error-text";
import type { ApprovalAction, DigestRow, EmailPreview } from "@/lib/api/gen/types.gen";
import { useIsDemo } from "@/lib/queries/me";
import { useDecideApproval } from "@/lib/queries/workspace";
import { useFormat } from "@/lib/use-format";
import type { Approval } from "@/lib/types";

/**
 * One approval. A real run's approval names the step it lets the run take (`action`); a demo approval shows
 * the email it would send (`preview`). "Simulated" appears only when the step's call would use sandbox data.
 */
export function ApprovalCard({ approval: a, onDecide }: { approval: Approval; onDecide: () => void }) {
  const t = useTranslations("approvals.card");
  const { dateTime, until } = useFormat();
  const errorText = useErrorText();
  const toast = useToast();
  const approveMutation = useDecideApproval("approve");
  const declineMutation = useDecideApproval("decline");
  const action = a.action;
  const demo = useIsDemo();
  // The cache is updated at once and rolled back on error, so the status is the single source of truth.
  const state = a.status === "GRANTED" ? "approved" : a.status === "DECLINED" ? "declined" : "pending";
  const approvedToast = () => {
    if (!action) {
      // An email approval belongs to the demo's fixtures; should one reach a live workspace, it is not the demo.
      const to = a.preview?.to ?? "";
      return demo
        ? toast(t("approvedToast"), t("approvedToastBody", { to }), "sim")
        : toast(t("approvedToast"), t("approvedToastBodyLive", { to }));
    }
    if (action.mocked)
      return toast(t("actionApprovedToast"), t("actionApprovedToastSimulated", { app: action.app }), "sim");
    return toast(t("actionApprovedToast"), t("actionApprovedToastBody", { app: action.app }));
  };
  const approve = () => {
    onDecide();
    approveMutation.mutate(
      { path: { approval_id: a.id } },
      {
        onSuccess: approvedToast,
        onError: (e) => toast(t("approveFailed"), errorText(e), "blocked"),
      },
    );
  };
  const decline = () => {
    onDecide();
    declineMutation.mutate(
      { path: { approval_id: a.id } },
      {
        onSuccess: () =>
          toast(
            t("declinedToast"),
            action ? t("actionDeclinedToastBody", { app: action.app }) : t("declinedToastBody"),
          ),
        onError: (e) => toast(t("declineFailed"), errorText(e), "blocked"),
      },
    );
  };
  const backToRun = (
    <Link className="link" href={`/app/runs/${a.runId}`}>
      {t("backToRun")}
    </Link>
  );

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
          {action ? <ActionPreview action={action} /> : a.preview ? <EmailPreviewBox preview={a.preview} /> : null}
        </div>
        <div className="bg-paper px-5 py-4">
          <h3 className="label mb-1">{t("digestHeading")}</h3>
          <KeyValues rows={a.digest.map((d) => digestRow(d, Boolean(action), t))} />
        </div>
      </div>
      <div className="border-t border-rule px-5 py-4">
        {state === "pending" ? (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="max-w-[60ch] text-sm text-muted">
              {action
                ? action.unlocked?.length
                  ? t("actionPendingNoteMore", { count: action.unlocked.length })
                  : t("actionPendingNote")
                : t("pendingNote")}
            </p>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={decline}>
                {t("decline")}
              </Button>
              <Button onClick={approve}>{action ? t("approveAction") : t("approve")}</Button>
            </div>
          </div>
        ) : state === "approved" ? (
          <Callout tone="info" title={action ? t("actionApprovedTitle") : t("approvedTitle")}>
            {action
              ? t("actionRecorded")
              : t.rich("recorded", { id: a.id, hash: "sha256:9f2c…41ad", mono: (chunks) => <Id>{chunks}</Id> })}{" "}
            {backToRun}
          </Callout>
        ) : (
          <Callout tone="warn" title={action ? t("actionDeclinedTitle") : t("declinedTitle")}>
            {action ? t("actionDeclinedBody", { app: action.app }) : t("declinedBody")} {backToRun}
          </Callout>
        )}
      </div>
    </Section>
  );
}

type CardT = ReturnType<typeof useTranslations<"approvals.card">>;
// The API's digest labels (English) that have a translation; a real approval's policy line is rendered from a key.
const DIGEST_KEYS = { Run: "digest.Run", Policy: "digest.Policy", "Decided by": "digest.Decided by" } as const;

/** A digest row in the interface language where the API's label is a known one, else as the API wrote it. */
function digestRow(d: DigestRow, real: boolean, t: CardT): { label: ReactNode; value: ReactNode } {
  const key = DIGEST_KEYS[d.label as keyof typeof DIGEST_KEYS];
  const label = key ? t(key) : d.label;
  if (real && d.label === "Policy") return { label, value: t("policyLine") };
  return { label, value: d.mono ? <Id>{d.value}</Id> : d.value };
}

/** The action in words: "Google Sheets: Append rows" (the app, then the tool's name as a sentence). */
function actionText(app: string, operation: string | null | undefined): string {
  const words = (operation ?? "").trim();
  return words ? `${app}: ${words.charAt(0).toUpperCase()}${words.slice(1)}` : app;
}

/** Whether the step is the app's own step: the run page labels such a step "App: …", so the action names it. */
function namesAction(step: string, app: string): boolean {
  return step.trim().toLowerCase().startsWith(`${app.toLowerCase()}:`);
}

function ActionPreview({ action }: { action: ApprovalAction }) {
  const t = useTranslations("approvals.card");
  const text = actionText(action.app, action.operation);
  // The step's label from the run page, then the action; one row when the step is the app's own step.
  const rows = [
    ...(namesAction(action.step, action.app) ? [] : [{ label: t("step"), value: action.step }]),
    { label: t("tool"), value: text },
    ...(action.count != null ? [{ label: t("calls"), value: t("times", { count: action.count }) }] : []),
    ...(action.summary ? [{ label: t("does"), value: action.summary }] : []),
  ];
  return (
    <>
      <h3 className="label mb-1 flex items-center gap-2">
        {t("actionHeading")}
        {action.mocked ? <SimTag /> : null}
      </h3>
      <KeyValues rows={rows} />
      {action.mocked ? <p className="mt-2 text-xs text-muted">{t("simulatedNote", { app: action.app })}</p> : null}
      {action.unlocked?.length ? (
        <>
          <h3 className="label mt-4 mb-1">{t("alsoHeading")}</h3>
          <KeyValues
            rows={action.unlocked.map((u) => {
              // An app's own step is named once, by its action; any other step keeps its label, then the action.
              const unlockedText = actionText(u.app, u.operation);
              const own = namesAction(u.step, u.app);
              return {
                label: own ? unlockedText : u.step,
                value: (
                  <span className="inline-flex flex-wrap items-center gap-2">
                    {own ? null : <span>{unlockedText}</span>}
                    {u.count != null ? <span className="text-muted">{t("times", { count: u.count })}</span> : null}
                    {u.mocked ? <SimTag /> : null}
                  </span>
                ),
              };
            })}
          />
          {[...new Set(action.unlocked.filter((u) => u.mocked).map((u) => u.app))].map((app) => (
            <p key={app} className="mt-2 text-xs text-muted">
              {t("simulatedNote", { app })}
            </p>
          ))}
          <p className="mt-2 text-xs text-muted">{t("alsoNote")}</p>
        </>
      ) : null}
    </>
  );
}

function EmailPreviewBox({ preview }: { preview: EmailPreview }) {
  const t = useTranslations("approvals.card");
  return (
    <>
      <h3 className="label mb-2">{t("emailHeading")}</h3>
      <div className="rounded-[10px] border border-rule">
        <div className="space-y-1 border-b border-rule px-4 py-3 text-sm">
          <div>
            <span className="text-muted">{t("to")} </span>
            {preview.to}
          </div>
          <div>
            <span className="text-muted">{t("subject")} </span>
            <span className="font-medium">{preview.subject}</span>
          </div>
        </div>
        <p className="px-4 py-3 text-sm leading-relaxed whitespace-pre-line">{preview.body}</p>
      </div>
    </>
  );
}
