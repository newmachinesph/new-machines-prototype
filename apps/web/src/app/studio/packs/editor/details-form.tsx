"use client";

import { Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId } from "react";
import { Checkbox, Select } from "@/components/base";
import { Button } from "@/components/ui";
import type { InputField } from "@/lib/api/gen/types.gen";
import {
  MAX_BUDGET_MINOR,
  MAX_INPUT_FIELDS,
  MIN_BUDGET_MINOR,
  type BudgetDetail,
  type DetailsIssue,
  type TextDetail,
} from "@/lib/builder/details";
import { useEditor, useEditorApi, type PackDetails } from "@/lib/builder/store";
import { FIELD_CLASS } from "./cel-field";
import { useIssueText } from "./issues-panel";
import { useReadOnly } from "./read-only";
import { useRowIds } from "./row-ids";

type FieldType = NonNullable<InputField["type"]>;
const FIELD_TYPES: readonly FieldType[] = ["text", "date", "number"];
const CENTS = 100;
// The API's defaults (apps/api/app/models/studio.py PackDraft), shown when a loaded draft leaves a budget out.
const DEFAULT_BUDGET_MINOR = 1500;
const DEFAULT_HUMAN_BUDGET_MINOR = 0;

const toMinor = (dollars: string) => {
  const n = Number(dollars);
  return Number.isFinite(n) ? Math.round(n * CENTS) : 0;
};

/** A request to put the cursor in the input an issue is about; `n` makes each request its own. */
export type DetailsFocus = { issue: DetailsIssue; n: number };

/** The input an issue is about, within one form (`fid`). */
const inputIdOf = (fid: string, issue: DetailsIssue) =>
  issue.field === "inputFields"
    ? `${fid}-field-${issue.index}-${issue.code === "badFieldName" ? "name" : "label"}`
    : `${fid}-${issue.field}`;

function FieldError({ id, messages }: { id: string; messages: string[] }) {
  if (!messages.length) return null;
  return (
    <p id={id} className="mt-1 text-xs text-blocked">
      {messages.join(" ")}
    </p>
  );
}

/**
 * What the marketplace shows about the pack, the run's start form, and its budgets. `issues` are the editor's
 * own findings about these details, shown under their inputs; `nameErrors` are the API's words about the name
 * (another pack of the org's already has it). For a member who may only read, the surrounding fieldset reaches
 * the native fields and the Base UI controls take the read-only context.
 */
export function DetailsForm({
  issues = [],
  nameErrors = [],
  focus = null,
  onFocused,
}: {
  issues?: DetailsIssue[];
  nameErrors?: string[];
  focus?: DetailsFocus | null;
  /** The request was carried out: the owner clears it, so a later visit to the form does not replay it. */
  onFocused?: () => void;
}) {
  const t = useTranslations("studioEditor");
  const text = useIssueText();
  const readOnly = useReadOnly();
  const api = useEditorApi();
  const details = useEditor((s) => s.details);
  const fid = useId();
  const fieldsHelpId = `${fid}-fields-help`;
  const budgetHelpId = `${fid}-budget-help`;
  const set = (patch: Partial<PackDetails>, record = false) => api.getState().setDetails(patch, record);
  const fields = details.inputFields ?? [];
  const rows = useRowIds(fields.length);
  const setField = (i: number, patch: Partial<InputField>, record = false) =>
    set({ inputFields: fields.map((f, j) => (j === i ? { ...f, ...patch } : f)) }, record);
  const freeName = () => {
    for (let n = fields.length + 1; ; n++) if (!fields.some((f) => f.name === `field_${n}`)) return `field_${n}`;
  };
  // A new field starts complete, so adding one never holds a save back by itself.
  const addField = () => {
    const n = fields.length + 1;
    set(
      {
        inputFields: [...fields, { name: freeName(), label: t("newFieldLabel", { n }), type: "text", required: true }],
      },
      true,
    );
  };
  const removeField = (i: number) => {
    rows.remove(i);
    set({ inputFields: fields.filter((_, j) => j !== i) }, true);
  };

  // The messages for one input, and the attributes that tie them to it.
  const errorsOf = (id: string, messages: string[], ...help: string[]) => ({
    id: `${id}-error`,
    messages,
    props: {
      id,
      "aria-invalid": messages.length ? true : undefined,
      "aria-describedby": [...help, ...(messages.length ? [`${id}-error`] : [])].join(" ") || undefined,
    },
  });
  const textErrors = (field: TextDetail, server: string[] = []) =>
    errorsOf(`${fid}-${field}`, [...issues.filter((i) => i.field === field).map(text), ...server]);
  const budgetErrors = (field: BudgetDetail) =>
    errorsOf(`${fid}-${field}`, issues.filter((i) => i.field === field).map(text), budgetHelpId);
  const fieldErrors = (index: number, part: "name" | "label") =>
    errorsOf(
      `${fid}-field-${index}-${part}`,
      issues
        .filter((i) => i.field === "inputFields" && i.index === index)
        .filter((i) => (part === "name" ? i.code === "badFieldName" : i.code === "missingFieldLabel"))
        .map(text),
    );
  const name = textErrors("name", nameErrors);
  const outcome = textErrors("outcome");
  const description = textErrors("description");
  const humanReview = textErrors("humanReview");
  const budget = budgetErrors("budgetMinor");
  const humanBudget = budgetErrors("humanBudgetMinor");

  // An issue picked under the canvas puts the cursor in its input, once.
  useEffect(() => {
    if (!focus) return;
    document.getElementById(inputIdOf(fid, focus.issue))?.focus();
    onFocused?.();
  }, [focus, fid, onFocused]);

  return (
    // One undo step per field visit: the store watches from focus to blur (see the store's startEdit).
    <div
      className="space-y-4 p-5"
      onFocus={() => api.getState().startEdit()}
      onBlur={() => api.getState().finishEdit()}
    >
      <div>
        <label htmlFor={name.props.id} className="block text-sm font-medium">
          {t("name")}
        </label>
        <input
          className={`${FIELD_CLASS} h-10`}
          maxLength={80}
          value={details.name}
          onChange={(e) => set({ name: e.target.value })}
          {...name.props}
        />
        <FieldError {...name} />
      </div>
      <div>
        <label htmlFor={outcome.props.id} className="block text-sm font-medium">
          {t("outcome")}
        </label>
        <input
          className={`${FIELD_CLASS} h-10`}
          maxLength={280}
          value={details.outcome}
          onChange={(e) => set({ outcome: e.target.value })}
          {...outcome.props}
        />
        <FieldError {...outcome} />
      </div>
      <div>
        <label htmlFor={description.props.id} className="block text-sm font-medium">
          {t("description")}
        </label>
        <textarea
          rows={4}
          className={`${FIELD_CLASS} py-2 leading-relaxed`}
          maxLength={2000}
          value={details.description}
          onChange={(e) => set({ description: e.target.value })}
          {...description.props}
        />
        <FieldError {...description} />
      </div>
      <div>
        <label htmlFor={humanReview.props.id} className="block text-sm font-medium">
          {t("humanReview")}
        </label>
        <textarea
          rows={2}
          className={`${FIELD_CLASS} py-2 leading-relaxed`}
          maxLength={400}
          value={details.humanReview}
          onChange={(e) => set({ humanReview: e.target.value })}
          {...humanReview.props}
        />
        <FieldError {...humanReview} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor={budget.props.id} className="block text-sm font-medium">
            {t("budget")}
          </label>
          <input
            type="number"
            min={MIN_BUDGET_MINOR / CENTS}
            max={MAX_BUDGET_MINOR / CENTS}
            step={0.01}
            className={`${FIELD_CLASS} h-10`}
            value={(details.budgetMinor ?? DEFAULT_BUDGET_MINOR) / CENTS}
            onChange={(e) => set({ budgetMinor: toMinor(e.target.value) })}
            {...budget.props}
          />
          <FieldError {...budget} />
        </div>
        <div>
          <label htmlFor={humanBudget.props.id} className="block text-sm font-medium">
            {t("humanBudget")}
          </label>
          <input
            type="number"
            min={0}
            max={MAX_BUDGET_MINOR / CENTS}
            step={0.01}
            className={`${FIELD_CLASS} h-10`}
            value={(details.humanBudgetMinor ?? DEFAULT_HUMAN_BUDGET_MINOR) / CENTS}
            onChange={(e) => set({ humanBudgetMinor: toMinor(e.target.value) })}
            {...humanBudget.props}
          />
          <FieldError {...humanBudget} />
        </div>
      </div>
      <p id={budgetHelpId} className="text-xs text-muted">
        {t("budgetHelp")}
      </p>

      <fieldset className="space-y-3 rounded-md border border-rule p-3" aria-describedby={fieldsHelpId}>
        <legend className="px-1 text-sm font-medium">{t("inputFields")}</legend>
        <p id={fieldsHelpId} className="text-xs text-muted">
          {t("inputFieldsHelp")}
        </p>
        {fields.map((f, i) => {
          const fieldName = fieldErrors(i, "name");
          const fieldLabel = fieldErrors(i, "label");
          return (
            <div key={rows.ids[i]} className="space-y-2 rounded-md bg-grey-50 p-2.5">
              <div className="grid gap-2 sm:grid-cols-2">
                <div>
                  <label htmlFor={fieldName.props.id} className="block text-sm font-medium">
                    {t("fieldName", { n: i + 1 })}
                  </label>
                  <input
                    className={`${FIELD_CLASS} h-9 font-mono text-[13px]`}
                    value={f.name}
                    onChange={(e) => setField(i, { name: e.target.value })}
                    {...fieldName.props}
                  />
                  <FieldError {...fieldName} />
                </div>
                <div>
                  <label htmlFor={fieldLabel.props.id} className="block text-sm font-medium">
                    {t("fieldLabel", { n: i + 1 })}
                  </label>
                  <input
                    className={`${FIELD_CLASS} h-9`}
                    maxLength={80}
                    value={f.label}
                    onChange={(e) => setField(i, { label: e.target.value })}
                    {...fieldLabel.props}
                  />
                  <FieldError {...fieldLabel} />
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <Select
                  label={t("fieldType", { n: i + 1 })}
                  disabled={readOnly}
                  value={f.type ?? "text"}
                  onValueChange={(v) => setField(i, { type: v }, true)}
                  items={FIELD_TYPES.map((v) => ({ value: v, label: t(`type.${v}`) }))}
                />
                <Checkbox
                  checked={f.required ?? true}
                  disabled={readOnly}
                  onCheckedChange={(v) => setField(i, { required: v }, true)}
                >
                  {t("fieldRequired")}
                </Checkbox>
                <Button
                  variant="ghost"
                  className="ml-auto h-8 px-2"
                  aria-label={t("removeField", { n: i + 1 })}
                  onClick={() => removeField(i)}
                >
                  <X className="size-4" aria-hidden />
                </Button>
              </div>
            </div>
          );
        })}
        <Button variant="secondary" className="h-8" disabled={fields.length >= MAX_INPUT_FIELDS} onClick={addField}>
          <Plus className="size-4" aria-hidden />
          {t("addField")}
        </Button>
      </fieldset>
    </div>
  );
}
