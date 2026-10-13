"use client";

import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getWorkflowRunOptions,
  getWorkflowRunQueryKey,
  getWorkflowRunReceiptOptions,
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

/**
 * The work receipt. Fixture runs have none (404): no retry, and no polling, because the interval only runs
 * while the query holds data. When the run's status changes (for example it finishes and the receipt seals),
 * the receipt is fetched once more so it never stays stale.
 */
export function useReceipt(id: string, status: RunStatus) {
  const qc = useQueryClient();
  const options = getWorkflowRunReceiptOptions({ path: { run_id: id } });
  const live = ACTIVE_STATUSES.includes(status);
  const query = useQuery({
    ...options,
    retry: false,
    refetchInterval: (q) => (live && q.state.data ? 2_000 : false),
  });
  const seen = useRef(status);
  const key = options.queryKey;
  useEffect(() => {
    if (seen.current === status) return;
    seen.current = status;
    void qc.invalidateQueries({ queryKey: key });
  }, [status, qc, key]);
  return query;
}

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
