"use client";

import { RunView } from "@/components/run-view";
import { useRunWithAgentNames } from "@/lib/agent-steps";
import type { Run } from "@/lib/types";

/** The run view with each agent step under its agent's display name, never its key. */
export function NamedRunView({ run }: { run: Run }) {
  return <RunView run={useRunWithAgentNames(run)} />;
}
