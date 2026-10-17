"use client";

import { useMemo } from "react";
import { useRunWithAgentNames } from "./agent-steps";
import { useStepText } from "./content-text";
import { usePacks } from "./queries/catalog";
import type { Run, RunNode } from "./types";

/**
 * The run with each step under the label `labelOf` gives it, and each timeline entry that a step wrote in its
 * own name (`who` is the step's recorded label, on the step's own actor) under the same label, so the timeline
 * and the steps agree. A person whose name happens to be a step's label writes on a person's actor, so their
 * line is never relabelled. The run record itself stays as the API sent it (new objects only where a label
 * changes); a run with nothing to relabel is returned as it is.
 */
export function relabelRun(run: Run, labelOf: (node: RunNode) => string): Run {
  const labels = new Map(run.nodes.map((n) => [n.id, { was: n.label, now: labelOf(n), actor: n.actor }]));
  const nodes = run.nodes.map((n) => {
    const now = labels.get(n.id)?.now ?? n.label;
    return now === n.label ? n : { ...n, label: now };
  });
  const timeline = run.timeline.map((e) => {
    const step = e.nodeId ? labels.get(e.nodeId) : undefined;
    const own = step !== undefined && e.who === step.was && e.actor === step.actor;
    return own && step.now !== step.was ? { ...e, who: step.now } : e;
  });
  const same = nodes.every((n, i) => n === run.nodes[i]) && timeline.every((e, i) => e === run.timeline[i]);
  return same ? run : { ...run, nodes, timeline };
}

/**
 * The run as it reads in the interface language: agent steps under their agent's display name (`agent-steps`),
 * and, for one of our own packs, every step under its label from the messages (`useStepText`), in the steps and
 * in the timeline alike. In English, and for any other pack, the steps read as the run recorded them.
 */
export function useLocalisedRun(run: Run): Run {
  const named = useRunWithAgentNames(run);
  const stepText = useStepText();
  const { data: packs } = usePacks();
  const pack = packs?.find((p) => p.slug === run.packSlug);
  return useMemo(() => {
    const namedLabels = new Map(named.nodes.map((n) => [n.id, n.label]));
    return relabelRun(run, (node) => stepText(pack, node) ?? namedLabels.get(node.id) ?? node.label);
  }, [run, named, pack, stepText]);
}
