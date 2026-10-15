"use client";

import { Handle, Position, useUpdateNodeInternals, type NodeProps } from "@xyflow/react";
import { useTranslations } from "next-intl";
import { createContext, memo, useContext, useEffect } from "react";
import { useShallow } from "zustand/react/shallow";
import { StepCard } from "@/components/step-card";
import { Pill } from "@/components/ui";
import { IN_HANDLE, type StepNode } from "@/lib/builder/graph";
import { stepSize } from "@/lib/builder/layout";
import { FAILURE_OUTCOMES, outcomesOf, SMALL_STEPS, STEP_ACTOR } from "@/lib/builder/routes";
import { isWrite } from "@/lib/builder/rules";
import { useEditor } from "@/lib/builder/store";
import { stepTitle } from "@/lib/builder/titles";
import { cn } from "@/lib/cn";

/** Problems per step id, local and from the API. The pack editor provides it; the canvas marks those steps. */
export const StepIssuesContext = createContext<ReadonlyMap<string, number>>(new Map());

/**
 * A step in the editor: the shared StepCard, one typed source handle per outcome on its right (an edge can only
 * leave from an outcome the step has), and one target handle on its left. An outcome with nowhere to go shows its
 * name beside its handle; a connected one is named on its edge.
 */
export const StepNodeView = memo(function StepNodeView({ id, data, selected }: NodeProps<StepNode>) {
  const t = useTranslations("studioCanvas");
  const palette = useEditor((s) => s.palette);
  const writes = useEditor((s) => isWrite(data, s.tools));
  const routed = useEditor(useShallow((s) => s.edges.filter((e) => e.source === id).map((e) => e.sourceHandle ?? "")));
  const problems = useContext(StepIssuesContext).get(id) ?? 0;
  const outcomes = outcomesOf(data);
  const small = SMALL_STEPS.has(data.type);
  const title =
    data.type === "trigger"
      ? t("startTitle")
      : data.type === "end"
        ? t(data.config.status === "FAILED" ? "endFailed" : "endCompleted")
        : (stepTitle(data, palette) ?? t("untitled"));

  // React Flow measures a node's handles once, when the node's size changes. A decision's handles come from its
  // rules, so a new or renamed route adds a handle without resizing the card: ask for a new measurement, or an
  // edge from the new handle cannot be drawn.
  const updateNodeInternals = useUpdateNodeInternals();
  const handleKey = outcomes.join("\n");
  useEffect(() => updateNodeInternals(id), [id, handleKey, updateNodeInternals]);

  return (
    <>
      {/* Handles are drag targets with no role or focus, so assistive technology is not told about them; the
          settings panel's "goes to" choices are the accessible way to connect steps. */}
      {data.type === "trigger" ? null : <Handle type="target" id={IN_HANDLE} position={Position.Left} aria-hidden />}
      <StepCard
        actor={STEP_ACTOR[data.type]}
        kind={t(`type.${data.type}`)}
        title={title}
        subtitle={id}
        small={small}
        state={selected ? "selected" : problems ? "blocked" : "plain"}
        aside={problems ? t("problems", { n: problems }) : undefined}
        style={{ minHeight: stepSize(data).height }}
      >
        {writes ? (
          <div className="mt-1.5">
            <Pill tone="human">{t("changesData")}</Pill>
          </div>
        ) : null}
      </StepCard>
      {outcomes.map((outcome, i) => (
        <Handle
          key={outcome}
          type="source"
          id={outcome}
          position={Position.Right}
          style={{ top: `${((i + 1) / (outcomes.length + 1)) * 100}%` }}
          className={cn(FAILURE_OUTCOMES.has(outcome) && "failure")}
          aria-hidden
        >
          {routed.includes(outcome) ? null : (
            <span
              className={cn(
                "pointer-events-none absolute bottom-2 left-2 text-[10px] leading-none whitespace-nowrap",
                FAILURE_OUTCOMES.has(outcome) ? "text-blocked" : "text-muted",
              )}
            >
              {outcome}
            </span>
          )}
        </Handle>
      ))}
    </>
  );
});
