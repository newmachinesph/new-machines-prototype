"use client";

import { useReactFlow } from "@xyflow/react";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useContext, useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { MenuItem, MenuLabel, MenuPopup, MenuRoot, MenuTrigger, useToast } from "@/components/base";
import { ActorGlyph } from "@/components/ui";
import type { StepNode } from "@/lib/builder/graph";
import { readingOrder } from "@/lib/builder/guided";
import { ADD_KINDS, BLANK_STEPS } from "@/lib/builder/palette";
import { FAILURE_OUTCOMES, outcomesOf, STEP_ACTOR } from "@/lib/builder/routes";
import { isWrite } from "@/lib/builder/rules";
import { useEditor, useEditorApi } from "@/lib/builder/store";
import { stepTitle } from "@/lib/builder/titles";
import { cn } from "@/lib/cn";
import { StepIssuesContext } from "./step-node";

/** A title that already ends a sentence; the sentence around it then drops its own full stop. */
const ENDS_SENTENCE = /[.?!。？！]$/;
const FULL_STOP = /[.。]$/;
const once = (sentence: string, title: string) =>
  ENDS_SENTENCE.test(title) ? sentence.replace(FULL_STOP, "") : sentence;

/** One plain sentence per step, for builders who work from the list rather than the canvas. */
function useSentence() {
  const t = useTranslations("studioPalette");
  const { palette, tools } = useEditor(useShallow((s) => ({ palette: s.palette, tools: s.tools })));
  return (node: StepNode): string => {
    const { data } = node;
    const title = stepTitle(data, palette);
    switch (data.type) {
      case "trigger":
        return t("say.trigger");
      case "memory":
        return title ? t("say.memory", { space: title }) : t("say.memoryBlank");
      case "connector":
        if (!title) return t("say.connectorBlank");
        return isWrite(data, tools) ? t("say.write", { tool: title }) : t("say.read", { tool: title });
      case "agent":
        return title ? t("say.agent", { agent: title }) : t("say.agentBlank");
      case "decision":
        return title ? t("say.decision", { question: title }) : t("say.decisionBlank");
      case "human_workforce":
        return title ? once(t("say.review", { title }), title) : t("say.reviewBlank");
      case "approval":
        return title ? once(t("say.approval", { title }), title) : t("say.approvalBlank");
      case "verification":
        return t("say.verification");
      case "end":
        return data.config.status === "FAILED" ? t("say.endFailed") : t("say.endCompleted");
    }
  };
}

/**
 * The workflow as a numbered list beside the canvas: each step's sentence and problems, choose a row to select
 * and centre its step, and add a step after it. Everything here works without the canvas. `disabled` leaves the
 * rows selectable but offers no way to add a step, for a pack the signed-in member may only read.
 */
export function StepList({ disabled = false }: { disabled?: boolean }) {
  const t = useTranslations("studioPalette");
  const tc = useTranslations("studioCanvas");
  const api = useEditorApi();
  const { nodes, edges, selectedId } = useEditor(
    useShallow((s) => ({ nodes: s.nodes, edges: s.edges, selectedId: s.selectedId })),
  );
  const problems = useContext(StepIssuesContext);
  const sentence = useSentence();
  const { fitView } = useReactFlow();
  const order = useMemo(() => readingOrder(nodes, edges), [nodes, edges]);

  const focus = (id: string) => {
    api.getState().select(id);
    void fitView({ nodes: [{ id }], maxZoom: 1, duration: 200 });
  };

  return (
    <ol className="space-y-1 p-2" aria-label={t("listLabel")}>
      {order.map((node, i) => {
        const count = problems.get(node.id) ?? 0;
        return (
          <li key={node.id}>
            <div
              className={cn(
                "flex items-start gap-2 rounded-md px-2 py-2",
                node.id === selectedId ? "bg-grey-50 ring-1 ring-ink/10" : "hover:bg-grey-50",
              )}
            >
              <span className="tnum mt-0.5 w-5 shrink-0 text-right text-xs text-muted">{i + 1}</span>
              <button
                type="button"
                className="min-w-0 flex-1 text-left"
                aria-current={node.id === selectedId ? "step" : undefined}
                onClick={() => focus(node.id)}
              >
                {/* The kind of step in plain words; its name (an identifier) is in the settings. */}
                <span className="flex items-center gap-1.5 text-xs font-medium text-muted">
                  <ActorGlyph actor={STEP_ACTOR[node.data.type]} className="size-2.5" />
                  {tc(`type.${node.data.type}`)}
                  <span className="font-mono text-[11px] font-normal">{node.id}</span>
                </span>
                <span className="mt-0.5 block text-sm leading-snug text-ink">{sentence(node)}</span>
                {count ? (
                  <span className="mt-0.5 block text-xs text-blocked">{tc("problems", { n: count })}</span>
                ) : null}
              </button>
              {disabled ? null : <AddAfter node={node} n={i + 1} />}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Adds a step on the step's first onward outcome, and moves what that outcome led to after the new step. Says so
 * when the new step cannot be connected (nothing is added), when the step that followed could not be wired after
 * it (it is left unconnected, for the builder to place), and when the new step has no outcome yet to carry it
 * (a decision, until its rules are added).
 */
function AddAfter({ node, n }: { node: StepNode; n: number }) {
  const t = useTranslations("studioPalette");
  const tc = useTranslations("studioCanvas");
  const toast = useToast();
  const api = useEditorApi();
  const outcomes = outcomesOf(node.data);
  const outcome = outcomes.find((o) => !FAILURE_OUTCOMES.has(o)) ?? outcomes[0];
  if (!outcome) return null;
  return (
    <MenuRoot>
      {/* Named by the row's number, as the list shows it. A finger gets a 40px target. */}
      <MenuTrigger
        aria-label={t("addAfter", { n })}
        className="grid size-7 shrink-0 place-items-center rounded-md text-grey-500 hover:bg-grey-100 hover:text-ink pointer-coarse:-my-1.5 pointer-coarse:size-10"
      >
        <Plus className="size-4" aria-hidden />
      </MenuTrigger>
      <MenuPopup>
        <MenuLabel>{t("addAfterOutcome", { outcome })}</MenuLabel>
        {ADD_KINDS.map((kind) => (
          <MenuItem
            key={kind}
            onClick={() => {
              const { refusal, unlinked, cut } = api.getState().insertAfter(node.id, outcome, BLANK_STEPS[kind]);
              if (refusal) toast(tc("refused"), tc(`refusal.${refusal}`), "blocked");
              else if (unlinked) toast(t("unlinked"), tc(`refusal.${unlinked}`), "blocked");
              else if (cut) toast(t("unlinked"), t(`cut.${cut}`), "blocked");
            }}
          >
            {t(`add.${kind}`)}
          </MenuItem>
        ))}
      </MenuPopup>
    </MenuRoot>
  );
}
