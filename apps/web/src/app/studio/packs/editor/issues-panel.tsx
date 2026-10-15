"use client";

import { useFormatter, useTranslations } from "next-intl";
import { Id, Section } from "@/components/ui";
import type { BudgetDetail, DetailsIssue, EditorIssue } from "@/lib/builder/details";

/** A problem the API reported: from Validate (BuilderIssue) or a refused save (the problem's errors). */
export type ServerIssue = { step?: string; path: string; message: string };

const CENTS = 100;
/** The details form's label for each budget, so an issue names the field as the form does. */
const BUDGET_LABEL: Record<BudgetDetail, "budget" | "humanBudget"> = {
  budgetMinor: "budget",
  humanBudgetMinor: "humanBudget",
};

const stepOf = (i: EditorIssue | ServerIssue) => ("step" in i ? i.step : undefined);
export const isDetailsIssue = (i: EditorIssue): i is DetailsIssue => "field" in i;

/** Problems per step, for the canvas and the step list. */
export function countByStep(local: EditorIssue[], server: ServerIssue[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const i of [...local, ...server]) {
    const step = stepOf(i);
    if (step) counts.set(step, (counts.get(step) ?? 0) + 1);
  }
  return counts;
}

/** The words for an issue the editor found, shared by the panel and the details form. */
export function useIssueText(): (issue: EditorIssue) => string {
  const t = useTranslations("studioIssues");
  const te = useTranslations("studioEditor");
  const format = useFormatter();
  const money = (minor: number) =>
    format.number(minor / CENTS, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  // Each code with a value in its message is named here, so the typed keys still check every other code.
  return (i) => {
    switch (i.code) {
      case "unrouted":
        return t("unrouted", { outcome: i.outcome ?? "" });
      case "missingArg":
      case "unknownArg":
        return t(i.code, { arg: i.arg ?? "" });
      case "missingDetail":
        return t("missingDetail", { field: te(i.field) });
      case "budgetRange":
        return t("budgetRange", { field: te(BUDGET_LABEL[i.field]), min: money(i.min), max: money(i.max) });
      case "badFieldName":
      case "missingFieldLabel":
        return t(i.code, { n: i.index + 1 });
      default:
        return t(i.code);
    }
  };
}

/** What makes an issue itself, for a row key; a second identical issue gets a count. */
const identity = (i: EditorIssue | ServerIssue, server: boolean) =>
  server && !("code" in i)
    ? `server|${i.step ?? ""}|${i.path}|${i.message}`
    : `local|${(i as EditorIssue).code}|${JSON.stringify(i)}`;

/**
 * Every problem the editor and the API found, under the canvas. A step's problem opens the step; a problem in the
 * pack's details (or one the API reports without a step) opens the details, at the field when it is known.
 */
export function IssuesPanel({
  local,
  server,
  checked,
  onPick,
  onPickDetails,
}: {
  local: EditorIssue[];
  server: ServerIssue[];
  /** The server's answer is for the draft as it is now. */
  checked: boolean;
  onPick: (step: string) => void;
  onPickDetails: (issue?: DetailsIssue) => void;
}) {
  const t = useTranslations("studioIssues");
  const text = useIssueText();
  const total = local.length + server.length;
  const seen = new Map<string, number>();
  const keyOf = (i: EditorIssue | ServerIssue, isServer: boolean) => {
    const id = identity(i, isServer);
    const n = (seen.get(id) ?? 0) + 1;
    seen.set(id, n);
    return n === 1 ? id : `${id}#${n}`;
  };
  const rows = [
    ...local.map((i) => {
      const step = stepOf(i);
      return {
        key: keyOf(i, false),
        step,
        text: text(i),
        server: false,
        open: isDetailsIssue(i) ? () => onPickDetails(i) : step ? () => onPick(step) : null,
      };
    }),
    ...server.map((i) => ({
      key: keyOf(i, true),
      step: i.step,
      text: i.message,
      server: true,
      open: i.step ? () => onPick(i.step as string) : () => onPickDetails(),
    })),
  ];
  return (
    <Section
      title={t("title", { n: total })}
      aside={checked ? <span className="text-xs text-muted">{t("checked")}</span> : null}
    >
      {total === 0 ? (
        <p className="px-5 py-4 text-sm text-muted">{t("none")}</p>
      ) : (
        <ul className="divide-y divide-rule">
          {rows.map((row) => {
            const body = (
              <>
                {row.step ? <Id className="mr-2">{row.step}</Id> : null}
                <span>{row.text}</span>
                {row.server ? <span className="ml-2 text-xs text-muted">{t("fromServer")}</span> : null}
              </>
            );
            return (
              <li key={row.key} className="px-5 py-2.5 text-sm">
                {row.open ? (
                  <button type="button" className="text-left hover:underline" onClick={row.open}>
                    {body}
                  </button>
                ) : (
                  body
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}
