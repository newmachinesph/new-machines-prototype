"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  opsApproveReviewerMutation,
  opsListReviewersOptions,
  opsReinstateReviewerMutation,
  opsSetReviewerLevelMutation,
  opsSuspendReviewerMutation,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import { OPS_SIDE_EFFECTS, byOp } from "./invalidate";

/** Every reviewer; the page splits them into tabs so the counts are always known. */
export const useReviewers = () => useQuery(opsListReviewersOptions());

function useRefreshReviewers() {
  const qc = useQueryClient();
  return { onSuccess: () => qc.invalidateQueries(byOp("opsListReviewers", ...OPS_SIDE_EFFECTS)) };
}

export const useApproveReviewer = () => useMutation({ ...opsApproveReviewerMutation(), ...useRefreshReviewers() });
export const useSuspendReviewer = () => useMutation({ ...opsSuspendReviewerMutation(), ...useRefreshReviewers() });
export const useReinstateReviewer = () => useMutation({ ...opsReinstateReviewerMutation(), ...useRefreshReviewers() });
export const useSetReviewerLevel = () => useMutation({ ...opsSetReviewerLevelMutation(), ...useRefreshReviewers() });
