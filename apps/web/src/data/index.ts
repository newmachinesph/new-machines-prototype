import type { Run } from "@/lib/types";
import { RUN_1036, RUN_1042, RUN_1047 } from "./runs-recon";
import { OLDER_RUNS, RUN_1039, RUN_1044, RUN_1045 } from "./runs-other";

export * from "./catalog";
export * from "./work";
export * from "./org";
export * from "./attention";

/** Runs with a full detail page, newest first. */
export const RUNS: Run[] = [RUN_1047, RUN_1045, RUN_1044, RUN_1039, RUN_1042, RUN_1036];

export const RUN_ROWS = [...RUNS, ...OLDER_RUNS].sort((a, b) => b.startedAt.localeCompare(a.startedAt));

export const runById = (id: string) => RUNS.find((r) => r.id === id);
