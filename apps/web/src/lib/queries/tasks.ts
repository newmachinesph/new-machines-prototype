"use client";

import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as q from "@/lib/api/gen/@tanstack/react-query.gen";
import type { HumanTask } from "@/lib/api/gen/types.gen";

export const useEligibleTasks = (enabled = true) =>
  useQuery({ ...q.listEligibleHumanTasksOptions(), refetchInterval: 10_000, enabled });
export const useTask = (id: string) => useQuery(q.getHumanTaskOptions({ path: { task_id: id } }));
export const useEarnings = () => useQuery(q.listEarningsOptions());

/** A claim or submission changes the task itself, the open offers and, once accepted, the earnings. */
function refreshTask(qc: QueryClient, task: HumanTask) {
  const detail = q.getHumanTaskQueryKey({ path: { task_id: task.id } });
  qc.setQueryData(detail, task);
  void qc.invalidateQueries({ queryKey: detail });
  void qc.invalidateQueries({ queryKey: q.listEligibleHumanTasksQueryKey() });
  void qc.invalidateQueries({ queryKey: q.listEarningsQueryKey() });
}

export function useClaimTask() {
  const qc = useQueryClient();
  return useMutation({ ...q.claimHumanTaskMutation(), onSuccess: (task) => refreshTask(qc, task) });
}

export function useSubmitReview() {
  const qc = useQueryClient();
  return useMutation({ ...q.submitHumanTaskMutation(), onSuccess: (task) => refreshTask(qc, task) });
}

/** The user's network reviewer profile (live workspace only). */
export const useReviewerProfile = (enabled = true) => useQuery({ ...q.getReviewerProfileOptions(), enabled });

/** Saving the profile changes which tasks are offered. */
export function useUpdateReviewerProfile() {
  const qc = useQueryClient();
  return useMutation({
    ...q.updateReviewerProfileMutation(),
    onSuccess: (profile) => {
      qc.setQueryData(q.getReviewerProfileQueryKey(), profile);
      void qc.invalidateQueries({ queryKey: q.listEligibleHumanTasksQueryKey() });
    },
  });
}
