"use client";

import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Select } from "@/components/base";
import { Button } from "@/components/ui";
import type { DecisionRule, DecisionRules } from "@/lib/api/gen/types.gen";
import type { CelOption } from "@/lib/builder/cel-fields";
import { CelField, FIELD_CLASS } from "./cel-field";
import { useReadOnly } from "./read-only";
import { useRowIds } from "./row-ids";

type Verdict = NonNullable<DecisionRule["verdict"]>;
const VERDICTS: readonly Verdict[] = ["APPROVED", "HUMAN_REVIEW", "BLOCKED", "REJECTED"];
/** The API's limit on rules per decision. */
const MAX_RULES = 20;

/** The first of route_1, route_2, ... that no route of the decision has yet. */
function freeRoute(taken: string[]): string {
  for (let n = 1; ; n++) if (!taken.includes(`route_${n}`)) return `route_${n}`;
}

/**
 * A decision's question, its rules (the first whose condition is true picks the route) and its default. Each
 * route is an outcome on the canvas: renaming one keeps its edge (see the store's updateStep).
 */
export function RulesEditor({
  stepId,
  rules,
  onChange,
  options,
}: {
  stepId: string;
  rules?: DecisionRules;
  onChange: (rules: DecisionRules, record: boolean) => void;
  options: CelOption[];
}) {
  const t = useTranslations("studioFields");
  const verdicts = VERDICTS.map((v) => ({ value: v, label: t(`verdict.${v}`) }));
  const list = rules?.rules ?? [];
  const rows = useRowIds(list.length);

  if (!rules)
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted">{t("rules.empty")}</p>
        <Button
          variant="secondary"
          onClick={() =>
            onChange(
              {
                question: t("rules.starterQuestion"),
                rules: [{ when: "", route: "yes", verdict: "HUMAN_REVIEW", explanation: t("rules.starterYes") }],
                default: { route: "no", verdict: "APPROVED", explanation: t("rules.starterNo") },
              },
              true,
            )
          }
        >
          {t("rules.start")}
        </Button>
      </div>
    );

  const routes = [...list.map((r) => r.route), rules.default.route];
  const setRule = (i: number, patch: Partial<DecisionRule>, record: boolean) =>
    onChange({ ...rules, rules: list.map((r, j) => (j === i ? { ...r, ...patch } : r)) }, record);
  const setDefault = (patch: Partial<DecisionRules["default"]>, record: boolean) =>
    onChange({ ...rules, default: { ...rules.default, ...patch } }, record);

  return (
    <div className="space-y-4">
      <div>
        <label htmlFor={`${stepId}-question`} className="block text-sm font-medium">
          {t("rules.question")}
        </label>
        <input
          id={`${stepId}-question`}
          className={`${FIELD_CLASS} h-10`}
          maxLength={200}
          value={rules.question}
          onChange={(e) => onChange({ ...rules, question: e.target.value }, false)}
        />
      </div>
      {list.map((rule, i) => {
        const row = rows.ids[i];
        return (
          <fieldset key={row} className="space-y-3 rounded-md border border-rule p-3">
            <legend className="px-1 text-sm font-medium">{t("rules.rule", { n: i + 1 })}</legend>
            <CelField
              id={`${stepId}-${row}-when`}
              label={t("rules.when", { n: i + 1 })}
              value={rule.when}
              options={options}
              bare
              onChange={(when, record) => setRule(i, { when }, record)}
            />
            <RouteFields
              idPrefix={`${stepId}-${row}`}
              n={i + 1}
              route={rule.route}
              others={routes.filter((_, j) => j !== i)}
              verdict={rule.verdict ?? "APPROVED"}
              explanation={rule.explanation}
              verdicts={verdicts}
              onChange={(patch, record) => setRule(i, patch, record)}
            />
            <Button
              variant="ghost"
              className="h-8"
              onClick={() => {
                rows.remove(i);
                onChange({ ...rules, rules: list.filter((_, j) => j !== i) }, true);
              }}
            >
              {t("rules.remove", { n: i + 1 })}
            </Button>
          </fieldset>
        );
      })}
      <Button
        variant="secondary"
        className="h-8"
        disabled={list.length >= MAX_RULES}
        onClick={() =>
          onChange(
            {
              ...rules,
              rules: [...list, { when: "", route: freeRoute(routes), verdict: "APPROVED", explanation: "" }],
            },
            true,
          )
        }
      >
        <Plus className="size-4" aria-hidden />
        {t("rules.add")}
      </Button>
      <fieldset className="space-y-3 rounded-md border border-rule p-3">
        <legend className="px-1 text-sm font-medium">{t("rules.otherwise")}</legend>
        <RouteFields
          idPrefix={`${stepId}-default`}
          route={rules.default.route}
          others={routes.slice(0, -1)}
          verdict={rules.default.verdict ?? "HUMAN_REVIEW"}
          explanation={rules.default.explanation}
          verdicts={verdicts}
          onChange={setDefault}
        />
      </fieldset>
    </div>
  );
}

function RouteFields({
  idPrefix,
  n,
  route,
  others,
  verdict,
  explanation,
  verdicts,
  onChange,
}: {
  idPrefix: string;
  /** The rule's number; none for the default. */
  n?: number;
  route: string;
  /** The decision's other route names, to say when this one is shared. */
  others: string[];
  verdict: Verdict;
  explanation: string;
  verdicts: { value: Verdict; label: string }[];
  onChange: (patch: { route?: string; verdict?: Verdict; explanation?: string }, record: boolean) => void;
}) {
  const t = useTranslations("studioFields");
  const readOnly = useReadOnly();
  const routeLabel = n ? t("rules.routeFor", { n }) : t("rules.defaultRoute");
  const verdictLabel = n ? t("rules.verdictFor", { n }) : t("rules.defaultVerdict");
  return (
    <>
      <RouteName
        id={`${idPrefix}-route`}
        label={routeLabel}
        value={route}
        shared={others.includes(route)}
        onChange={(next) => onChange({ route: next }, false)}
      />
      <div>
        <label htmlFor={`${idPrefix}-verdict`} className="block text-sm font-medium">
          {verdictLabel}
        </label>
        <div className="mt-1.5">
          <Select
            id={`${idPrefix}-verdict`}
            label={verdictLabel}
            className="w-full"
            disabled={readOnly}
            value={verdict}
            onValueChange={(v) => onChange({ verdict: v }, true)}
            items={verdicts}
          />
        </div>
      </div>
      <div>
        <label htmlFor={`${idPrefix}-explanation`} className="block text-sm font-medium">
          {t("rules.explanation")}
        </label>
        <input
          id={`${idPrefix}-explanation`}
          className={`${FIELD_CLASS} h-10`}
          maxLength={400}
          value={explanation}
          onChange={(e) => onChange({ explanation: e.target.value }, false)}
        />
      </div>
    </>
  );
}

/**
 * A route's name, committed when the field is left or on Enter rather than on every keystroke: a name passed
 * through on the way (one that another route already has) would otherwise take that route's edge, since the
 * decision's outcomes are its route names. Two rules may share a route; the help says so.
 */
function RouteName({
  id,
  label,
  value,
  shared,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  shared: boolean;
  onChange: (route: string) => void;
}) {
  const t = useTranslations("studioFields");
  const [draft, setDraft] = useState(value);
  const [seen, setSeen] = useState(value);
  if (seen !== value) {
    // The route changed from outside the field (a commit, an undo): show it as it now is.
    setSeen(value);
    setDraft(value);
  }
  const commit = () => {
    const next = draft.trim();
    if (!next || next === value) setDraft(value);
    else onChange(next);
  };
  const hint = `${id}-help`;
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        className={`${FIELD_CLASS} h-10 font-mono text-[13px]`}
        maxLength={40}
        value={draft}
        aria-describedby={hint}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
      />
      <p id={hint} className="mt-1 text-xs text-muted">
        {t("rules.routeHelp")}
        {shared ? ` ${t("rules.sharedRoute")}` : ""}
      </p>
    </div>
  );
}
