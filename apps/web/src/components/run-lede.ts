"use client";

import { useTranslations } from "next-intl";
import type { Run } from "@/lib/types";
import { useCodes } from "./run-codes";

/** The summary the API gives a run until it ends; the lede says what the run is doing instead. */
export const RUN_SUMMARY_PLACEHOLDER = "Starting.";
const LEDE_STATES = ["WAITING_FOR_HUMAN", "WAITING_FOR_EVENT", "RUNNING", "VERIFYING"] as const;

type LedeRun = Pick<Run, "summary" | "status"> & { nodes?: Run["nodes"] };

/**
 * A run's one-line description, the same on its page and in a list: its summary or, while that is still
 * the placeholder, what the run is doing now. Without its nodes (a list row) a running run counts as started.
 */
export function useRunLede(): (run: LedeRun) => string {
  const t = useTranslations("run.list");
  const { line } = useCodes();
  return (r) => {
    if (r.summary !== RUN_SUMMARY_PLACEHOLDER) return line(r.summary);
    const state = LEDE_STATES.find((s) => s === r.status);
    const started = r.nodes ? r.nodes.some((n) => n.status !== "CREATED") : true;
    return state && (state !== "RUNNING" || started) ? t(`lede.${state}`) : t("lede.starting");
  };
}
