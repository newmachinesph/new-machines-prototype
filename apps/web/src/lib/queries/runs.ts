"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getWorkflowRunOptions,
  getWorkflowRunQueryKey,
  listWorkflowRunsOptions,
  listWorkflowRunsQueryKey,
  startWorkflowRunMutation,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import type { RunStatus } from "@/lib/types";

export const ACTIVE_STATUSES: RunStatus[] = ["RUNNING", "WAITING_FOR_HUMAN", "WAITING_FOR_EVENT", "VERIFYING"];

export const useRuns = (enabled = true) => useQuery({ ...listWorkflowRunsOptions(), refetchInterval: 10_000, enabled });

export const useRun = (id: string) =>
  useQuery({
    ...getWorkflowRunOptions({ path: { run_id: id } }),
    refetchInterval: (q) => (q.state.data && ACTIVE_STATUSES.includes(q.state.data.status) ? 2_000 : false),
  });

export function useStartRun() {
  const qc = useQueryClient();
  return useMutation({
    ...startWorkflowRunMutation(),
    onSuccess: (run) => {
      qc.setQueryData(getWorkflowRunQueryKey({ path: { run_id: run.id } }), run);
      void qc.invalidateQueries({ queryKey: listWorkflowRunsQueryKey() });
    },
  });
}
