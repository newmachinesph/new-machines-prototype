"use client";

import { RunView } from "@/components/run-view";
import { useLocalisedRun } from "@/lib/run-text";
import type { Run } from "@/lib/types";

/** The run view with each step labelled in the interface language (our own packs) and each agent step under its
 * agent's display name, never its key. */
export function NamedRunView({ run }: { run: Run }) {
  return <RunView run={useLocalisedRun(run)} />;
}
