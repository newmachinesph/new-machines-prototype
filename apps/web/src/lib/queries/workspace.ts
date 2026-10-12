"use client";

import {
  type QueryClient,
  type QueryKey,
  type UseMutationOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { ORG_ID } from "@/lib/api/client";
import * as q from "@/lib/api/gen/@tanstack/react-query.gen";
import type {
  ListApprovalsResponse,
  ListConnectionsResponse,
  ListMemoryResponse,
  ListTokensResponse,
} from "@/lib/api/gen/types.gen";

const org = { path: { org_id: ORG_ID } };

/** Apply `update` to cached data now; return a rollback for onError. */
export async function optimistic<T>(qc: QueryClient, key: QueryKey, update: (old: T) => T) {
  await qc.cancelQueries({ queryKey: key });
  const previous = qc.getQueryData<T>(key);
  if (previous !== undefined) qc.setQueryData<T>(key, update(previous));
  return () => {
    if (previous !== undefined) qc.setQueryData<T>(key, previous);
  };
}

type Rollback = { rollback: () => void };

/** A mutation that edits a cached list at once, rolls back on error, and refetches when it settles. */
function useListMutation<TData, TError, TVars, T>(
  options: UseMutationOptions<TData, TError, TVars>,
  key: QueryKey,
  update: (old: T[], vars: TVars) => T[],
  alsoInvalidate: (qc: QueryClient) => void = () => {},
) {
  const qc = useQueryClient();
  return useMutation<TData, TError, TVars, Rollback>({
    ...options,
    onMutate: async (vars) => ({ rollback: await optimistic<T[]>(qc, key, (old) => update(old, vars)) }),
    onError: (_error, _vars, ctx) => ctx?.rollback(),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: key });
      alsoInvalidate(qc);
    },
  });
}

/** Deciding an approval changes what the overview, the palette and the run page show. */
function invalidateApprovalViews(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: q.listAttentionQueryKey(org) });
  void qc.invalidateQueries({ queryKey: q.listWorkflowRunsQueryKey() });
  void qc.invalidateQueries({
    predicate: (query) => {
      const head = query.queryKey[0];
      return typeof head === "object" && head !== null && "_id" in head && head._id === "getWorkflowRun";
    },
  });
}

export const useApprovals = (enabled = true) =>
  useQuery({ ...q.listApprovalsOptions(), refetchInterval: 10_000, enabled });
export const useMemory = (enabled = true) => useQuery({ ...q.listMemoryOptions(), enabled });
export const useMembers = () => useQuery(q.listMembersOptions(org));
export const useTokens = () => useQuery(q.listTokensOptions());
export const usePolicies = () => useQuery(q.listPoliciesOptions(org));
export const useUsage = () => useQuery(q.getUsageOptions(org));

export function useDecideApproval(decision: "approve" | "decline") {
  const status = decision === "approve" ? "GRANTED" : "DECLINED";
  return useListMutation(
    decision === "approve" ? q.approveApprovalMutation() : q.declineApprovalMutation(),
    q.listApprovalsQueryKey(),
    (old: ListApprovalsResponse, vars) => old.map((a) => (a.id === vars.path.approval_id ? { ...a, status } : a)),
    invalidateApprovalViews,
  );
}

export const useRetractMemory = () =>
  useListMutation(q.retractMemoryMutation(), q.listMemoryQueryKey(), (old: ListMemoryResponse, vars) =>
    old.map((m) => (m.id === vars.path.memory_id ? { ...m, retracted: true } : m)),
  );

export function useReviewMemory() {
  const qc = useQueryClient();
  return useMutation({
    ...q.reviewMemoryCandidateMutation(),
    // Put the server's answer in the cache at once; refetch without holding the mutation open.
    onSuccess: (item) =>
      qc.setQueryData<ListMemoryResponse>(q.listMemoryQueryKey(), (old) =>
        old?.map((m) => (m.id === item.id ? item : m)),
      ),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: q.listMemoryQueryKey() });
    },
  });
}

export const useDisconnect = () =>
  useListMutation(q.disconnectConnectionMutation(), q.listConnectionsQueryKey(), (old: ListConnectionsResponse, vars) =>
    old.map((c) => (c.app === vars.path.app_name ? { ...c, status: "not_connected" as const, grants: [] } : c)),
  );

export const useRevokeGrant = () =>
  useListMutation(q.revokeGrantMutation(), q.listConnectionsQueryKey(), (old: ListConnectionsResponse, vars) =>
    old.map((c) =>
      c.app !== vars.query.app
        ? c
        : {
            ...c,
            grants: c.grants.filter(
              (g) => !(g.install === vars.query.install && g.capability === vars.query.capability),
            ),
          },
    ),
  );

export const useRevokeToken = () =>
  useListMutation(q.revokeTokenMutation(), q.listTokensQueryKey(), (old: ListTokensResponse, vars) =>
    old.filter((t) => t.id !== vars.path.token_id),
  );

export function useInvite() {
  const qc = useQueryClient();
  return useMutation({
    ...q.inviteMemberMutation(),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: q.listMembersQueryKey(org) });
    },
  });
}

export function useCreateToken() {
  const qc = useQueryClient();
  return useMutation({
    ...q.createTokenMutation(),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: q.listTokensQueryKey() });
    },
  });
}
