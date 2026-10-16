"use client";

import { useTranslations } from "next-intl";
import { useMemo } from "react";
import { useAgentById } from "@/lib/queries/catalog";
import type { Run, RunNode } from "@/lib/types";

/** A workspace's own definition key is `<org namespace>--<name>`; platform keys never contain "--". */
const ORG_SEPARATOR = "--";

/** The agent an agent step pinned: its version ref is `<agent key>@<version>`. */
const agentKey = (node: RunNode) => (node.type === "agent" && node.version ? node.version.split("@")[0] : undefined);

/** Lowercase, with every run of spaces and dashes as one dash, so "Org 5c81  helper" and "org-5c81--helper" agree. */
const squash = (text: string) =>
  text
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "-");

/** True when `label` carries the org namespace of the org key `key` (the key in words, the key, or the id). */
const carriesOrgId = (label: string, key: string) => {
  const namespace = key.split(ORG_SEPARATOR)[0] ?? "";
  return namespace !== "" && squash(label).includes(squash(namespace));
};

/**
 * Run steps with each agent step under its agent's display name. Older runs label a workspace's own agent step
 * by its key in words, which shows the org id; when the agent has no name to show here, such a step reads as
 * `fallback` instead. A name the run itself gives the step is kept. Steps that need no change are returned as
 * they are.
 */
export function nameAgentSteps(
  nodes: RunNode[],
  nameOf: (key: string) => string | undefined,
  fallback: string,
): RunNode[] {
  return nodes.map((node) => {
    const key = agentKey(node);
    if (!key) return node;
    const leaksKey = key.includes(ORG_SEPARATOR) && carriesOrgId(node.label, key);
    const label = nameOf(key) ?? (leaksKey ? fallback : node.label);
    return label === node.label ? node : { ...node, label };
  });
}

/** The run with its agent steps named from the agent catalog (see `nameAgentSteps`). */
export function useRunWithAgentNames(run: Run): Run {
  const t = useTranslations("run.canvas.nodeType");
  const agentById = useAgentById();
  const fallback = t("agent");
  return useMemo(() => {
    const nodes = nameAgentSteps(run.nodes, (key) => agentById(key)?.name, fallback);
    return nodes.every((n, i) => n === run.nodes[i]) ? run : { ...run, nodes };
  }, [run, agentById, fallback]);
}
