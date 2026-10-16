"use client";

import { Copy, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { useStoreWithEqualityFn } from "zustand/traditional";
import { Select, useToast } from "@/components/base";
import { Button } from "@/components/ui";
import type { Palette } from "@/lib/api/gen/types.gen";
import { celOptions, itemOptions } from "@/lib/builder/cel-fields";
import type { StepEdge, StepNode, StepNodeData } from "@/lib/builder/graph";
import { readingOrder } from "@/lib/builder/guided";
import { outcomesOf } from "@/lib/builder/routes";
import { STEP_SCHEMAS, withDerived } from "@/lib/builder/step-schemas";
import { useEditor, useEditorApi, type PackDetails } from "@/lib/builder/store";
import { useOutcomeLabel } from "@/lib/outcome-label";
import { FIELD_CLASS } from "./cel-field";
import { useReadOnly } from "./read-only";
import { RulesEditor } from "./rules-editor";
import { SchemaForm } from "./schema-form";

/**
 * The selected step's settings. Choosing another step starts the panel afresh; renaming the open step keeps it as
 * it is. `afterRemove` runs once the step is gone, for the page to move focus somewhere that still exists.
 */
export function StepSettings({ afterRemove }: { afterRemove?: () => void } = {}) {
  const t = useTranslations("studioFields");
  const api = useEditorApi();
  // Its id and settings only: a drag moves the node without changing either, so the panel stays as it is.
  const step = useEditor(
    useShallow((s) => {
      const node = s.nodes.find((n) => n.id === s.selectedId);
      return node ? { id: node.id, data: node.data } : null;
    }),
  );
  // The panel's key. A rename changes the selected id too, but the renamed step is the one that was open (its old
  // id is gone), so the key is kept: the fields stay mounted and keyboard focus stays where Tab or Enter left it.
  const [mount, setMount] = useState(() => (step ? { id: step.id, key: step.id } : null));
  if (step && step.id !== mount?.id) {
    const renamed = mount !== null && !api.getState().nodes.some((n) => n.id === mount.id);
    setMount({ id: step.id, key: renamed ? mount.key : step.id });
  } else if (!step && mount) setMount(null);
  // The step whose name field takes focus once its panel is up: set by Duplicate, read after the render.
  const wantName = useRef<string | null>(null);
  useLayoutEffect(() => {
    const id = wantName.current;
    if (id === null || step?.id !== id) return;
    wantName.current = null;
    document.getElementById(`${id}-name`)?.focus();
  });
  if (!step || !mount) return <p className="p-5 text-sm text-muted">{t("nothingSelected")}</p>;
  const duplicate = () => {
    api.getState().duplicate(step.id);
    // The store selects the copy.
    wantName.current = api.getState().selectedId;
  };
  const remove = () => {
    api.getState().removeStep(step.id);
    afterRemove?.();
  };
  return <Settings key={mount.key} id={step.id} data={step.data} onDuplicate={duplicate} onRemove={remove} />;
}

type Graph = { nodes: StepNode[]; edges: StepEdge[]; details: PackDetails; palette: Palette };

const sameSteps = (a: StepNode[], b: StepNode[]) =>
  a.length === b.length && a.every((n, i) => n.id === b[i].id && n.data === b[i].data);
const sameEdges = (a: StepEdge[], b: StepEdge[]) =>
  a.length === b.length && a.every((e, i) => e.id === b[i].id && e.target === b[i].target);

/**
 * The graph as the panel reads it: step ids and settings, which outcome leads where, the pack's details and the
 * palette. Positions and routes are left out, so a drag frame neither redraws the panel nor recomputes what the
 * step can read.
 */
function useGraph(): Graph {
  const api = useEditorApi();
  return useStoreWithEqualityFn(
    api,
    (s) => ({ nodes: s.nodes, edges: s.edges, details: s.details, palette: s.palette }),
    (a, b) =>
      sameSteps(a.nodes, b.nodes) && sameEdges(a.edges, b.edges) && a.details === b.details && a.palette === b.palette,
  );
}

function Settings({
  id,
  data,
  onDuplicate,
  onRemove,
}: {
  id: string;
  data: StepNodeData;
  onDuplicate: () => void;
  onRemove: () => void;
}) {
  const t = useTranslations("studioFields");
  const tc = useTranslations("studioCanvas");
  const api = useEditorApi();
  const { nodes, edges, details, palette } = useGraph();
  const cel = useMemo(() => celOptions(id, nodes, edges, details, palette), [id, nodes, edges, details, palette]);
  // Only a repeating app step's own tool settings can read `item`; the form passes it to those alone.
  const item = data.type === "connector" ? itemOptions(data.config.for_each, nodes, palette) : [];
  // The store's actions never change, so reading one per render is safe.
  const update = api.getState().updateStep;
  // A pack keeps one start, so the only start cannot be removed: no button that would do nothing.
  const starts = nodes.filter((n) => n.data.type === "trigger").length;
  const removable = data.type !== "trigger" || starts > 1;

  return (
    // One undo step per field visit: the store watches from focus to blur (see the store's startEdit).
    <div
      className="space-y-5 p-5"
      onFocus={() => api.getState().startEdit()}
      onBlur={() => api.getState().finishEdit()}
    >
      <div className="text-xs text-muted">{tc(`type.${data.type}`)}</div>
      <StepName id={id} />
      {data.type === "decision" ? (
        <RulesEditor
          stepId={id}
          rules={data.rules}
          options={cel}
          onChange={(rules, record) => update(id, { rules }, record)}
        />
      ) : (
        <SchemaForm
          stepId={id}
          schema={STEP_SCHEMAS[data.type]}
          value={data.config}
          cel={cel}
          item={item}
          palette={palette}
          onChange={(next, record) => update(id, { config: withDerived(data, next, palette) }, record)}
        />
      )}
      <Outcomes id={id} data={data} nodes={nodes} edges={edges} />
      {data.type === "trigger" && !removable ? null : (
        <div className="flex flex-wrap gap-2 border-t border-rule pt-4">
          {data.type === "trigger" ? null : (
            <Button variant="secondary" onClick={onDuplicate}>
              <Copy className="size-4" aria-hidden />
              {t("duplicate")}
            </Button>
          )}
          {removable ? (
            <Button variant="danger" onClick={onRemove}>
              <Trash2 className="size-4" aria-hidden />
              {t("remove")}
            </Button>
          ) : null}
        </div>
      )}
    </div>
  );
}

/** The step's id, which expressions use (`nodes.<id>.output`). Committed on Enter or when the field is left. */
function StepName({ id }: { id: string }) {
  const t = useTranslations("studioFields");
  const api = useEditorApi();
  const [draft, setDraft] = useState(id);
  const [error, setError] = useState<"badId" | "taken" | null>(null);
  const commit = () => {
    const next = draft.trim();
    const result = api.getState().renameStep(id, next);
    setError(result === "ok" ? null : result);
    // The field stays mounted through the rename, so it shows the name as it was taken.
    if (result === "ok") setDraft(next);
  };
  const fieldId = `${id}-name`;
  const hint = `${fieldId}-help`;
  return (
    <div>
      <label htmlFor={fieldId} className="block text-sm font-medium">
        {t("stepName")}
      </label>
      <input
        id={fieldId}
        className={`${FIELD_CLASS} h-10 font-mono text-[13px]`}
        value={draft}
        aria-describedby={hint}
        aria-invalid={error ? true : undefined}
        onChange={(e) => {
          setDraft(e.target.value);
          setError(null);
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
      />
      {error ? (
        <p id={hint} role="alert" className="mt-1 text-xs text-blocked">
          {t(`rename.${error}`)}
        </p>
      ) : (
        <p id={hint} className="mt-1 text-xs text-muted">
          {t("stepNameHelp")}
        </p>
      )}
    </div>
  );
}

/** Where each outcome goes: the way to connect steps without dragging, checked by the same rules as the canvas. */
function Outcomes({
  id,
  data,
  nodes,
  edges,
}: {
  id: string;
  data: StepNodeData;
  nodes: StepNode[];
  edges: StepEdge[];
}) {
  const t = useTranslations("studioFields");
  const tc = useTranslations("studioCanvas");
  const outcomeLabel = useOutcomeLabel();
  const toast = useToast();
  const api = useEditorApi();
  const readOnly = useReadOnly();
  const outcomes = outcomesOf(data);
  if (!outcomes.length) return null;
  // Named as the step list names them: its number in reading order and the kind of step, then the id.
  const targets = [
    { value: "", label: t("nowhere") },
    ...readingOrder(nodes, edges).flatMap((n, i) =>
      n.id === id || n.data.type === "trigger"
        ? []
        : [{ value: n.id, label: t("stepTarget", { n: i + 1, kind: tc(`type.${n.data.type}`), id: n.id }) }],
    ),
  ];
  const choose = (outcome: string, target: string) => {
    if (!target) {
      api.getState().disconnect(id, outcome);
      return;
    }
    const refusal = api.getState().connect({ source: id, sourceHandle: outcome, target });
    if (refusal) toast(tc("refused"), tc(`refusal.${refusal}`), "blocked");
  };
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{t("outcomes")}</legend>
      {outcomes.map((outcome) => {
        const target = edges.find((e) => e.source === id && e.sourceHandle === outcome)?.target ?? "";
        return (
          <div key={outcome} className="flex items-center gap-3">
            <span className="w-24 shrink-0 truncate text-[12px]">{outcomeLabel(outcome)}</span>
            <Select
              label={t("goesTo", { outcome: outcomeLabel(outcome) })}
              className="min-w-0 flex-1"
              disabled={readOnly}
              value={target}
              onValueChange={(v) => choose(outcome, v)}
              items={targets}
            />
          </div>
        );
      })}
    </fieldset>
  );
}
