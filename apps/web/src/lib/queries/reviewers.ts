"use client";

import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as q from "@/lib/api/gen/@tanstack/react-query.gen";
import type { OrgReviewers } from "@/lib/api/gen/types.gen";
import { byOperation, orgScoped, useIsLive } from "./me";
import { useOrgPath } from "./org";

/** The org's reviewers and its network switch. Live workspace only: never requested in the demo. */
export function useOrgReviewers() {
  const { me, path, ready } = useOrgPath();
  const live = useIsLive();
  return orgScoped(me, useQuery({ ...q.listOrgReviewersOptions(path), enabled: ready && live }));
}

/** A reviewer change also changes the members list on Settings. */
function refresh(qc: QueryClient) {
  void qc.invalidateQueries({ predicate: byOperation("listOrgReviewers") });
  void qc.invalidateQueries({ predicate: byOperation("listMembers") });
}

export function useAddReviewer() {
  const qc = useQueryClient();
  return useMutation({ ...q.addOrgReviewerMutation(), onSettled: () => refresh(qc) });
}

export function useRemoveReviewer() {
  const qc = useQueryClient();
  return useMutation({ ...q.removeOrgReviewerMutation(), onSettled: () => refresh(qc) });
}

export function useSetReviewerNetwork() {
  const qc = useQueryClient();
  return useMutation({
    ...q.setReviewerNetworkMutation(),
    // The answer is the whole list, so the checkbox and the toast agree at once, before any refetch.
    onSuccess: (data: OrgReviewers) =>
      qc.setQueriesData<OrgReviewers>({ predicate: byOperation("listOrgReviewers") }, data),
    onSettled: () => refresh(qc),
  });
}
