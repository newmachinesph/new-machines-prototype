"use client";

import {
  type QueryClient,
  type QueryKey,
  type UseMutationOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import * as q from "@/lib/api/gen/@tanstack/react-query.gen";
import type {
  Connection as ApiConnection,
  ListApprovalsResponse,
  ListConnectionsResponse,
  ListMemoryResponse,
  ListTokensResponse,
  RevokedGrant,
} from "@/lib/api/gen/types.gen";
import { byOperation, orgScoped } from "./me";
import { useOrgPath } from "./org";

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
  void qc.invalidateQueries({ predicate: byOperation("listAttention") });
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
export const useTokens = () => useQuery(q.listTokensOptions());

export function useMembers() {
  const { me, path, ready } = useOrgPath();
  return orgScoped(me, useQuery({ ...q.listMembersOptions(path), enabled: ready }));
}

export function usePolicies() {
  const { me, path, ready } = useOrgPath();
  return orgScoped(me, useQuery({ ...q.listPoliciesOptions(path), enabled: ready }));
}

export function useUsage() {
  const { me, path, ready } = useOrgPath();
  return orgScoped(me, useQuery({ ...q.getUsageOptions(path), enabled: ready }));
}

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

type Named = Pick<ApiConnection, "key" | "app">;

/** What names an app's card: its connector key in a live workspace, else its app name (demo rows). */
export const connectorKey = (c: Named) => c.key ?? c.app;

/** `old` with the card of `conn`'s app (by connector key, else app name) replaced by `conn`. */
export const replaceConnection = (old: ListConnectionsResponse | undefined, conn: ApiConnection) =>
  old?.map((c) => (connectorKey(c) === connectorKey(conn) ? conn : c));

/**
 * The connection a connector key names, such as the `?connected=<key>` an app's sign-in page returns with.
 * Nothing when the workspace lists no such app, so an unknown key is never shown as one.
 */
export const findConnection = <T extends Named>(conns: readonly T[] | undefined, key: string) =>
  key ? conns?.find((c) => connectorKey(c) === key) : undefined;

/**
 * `c` with the grant taken off and remembered as revoked (once, however often the same grant is revoked), so the
 * card can offer to allow it again.
 */
export const withGrantRevoked = (c: ApiConnection, grant: RevokedGrant): ApiConnection => {
  const same = (g: RevokedGrant) => g.install === grant.install && g.capability === grant.capability;
  const revoked = c.revoked ?? [];
  return {
    ...c,
    grants: c.grants.filter((g) => !same(g)),
    revoked: revoked.some(same) ? revoked : [...revoked, { install: grant.install, capability: grant.capability }],
  };
};

/** A mutation whose answer is the app's new row: it replaces the card at once, then the list is refetched. */
function useConnectionMutation<TData extends ApiConnection, TError, TVars>(
  options: UseMutationOptions<TData, TError, TVars>,
) {
  const qc = useQueryClient();
  const key = q.listConnectionsQueryKey();
  return useMutation({
    ...options,
    onSuccess: (conn) => qc.setQueryData<ListConnectionsResponse>(key, (old) => replaceConnection(old, conn)),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: key });
    },
  });
}

/**
 * Connect an app: `body.mode` "sandbox" (the default) connects it to simulated data; "live" starts signing in to
 * the real account, and the answer carries `redirectUrl`, the app's sign-in page (none when the real account is
 * already connected: the row comes back unchanged). The answer replaces the app's card at once.
 */
export const useConnectApp = () => useConnectionMutation(q.connectConnectionMutation());

/**
 * Ask the API how signing in to an app's real account went (after coming back from its sign-in page). The row
 * may still be `pending` (the sign-in is not finished), or no longer the real account at all (switched to
 * simulated data meanwhile); callers read `status` and `mode` rather than assume success.
 */
export const useSyncConnection = () => useConnectionMutation(q.syncConnectionMutation());

/**
 * Allow a capability a person revoked from a pack again. The API forgets the revocation and answers with the
 * row, holding the grant again when a pack the workspace added still uses the capability.
 */
export const useAllowGrant = () => useConnectionMutation(q.allowGrantMutation());

/** Revoking takes the grant off the card at once and remembers it as revoked, so it can be allowed again. */
export const useRevokeGrant = () =>
  useListMutation(q.revokeGrantMutation(), q.listConnectionsQueryKey(), (old: ListConnectionsResponse, vars) =>
    old.map((c) => (c.app === vars.query.app ? withGrantRevoked(c, vars.query) : c)),
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
      void qc.invalidateQueries({ predicate: byOperation("listMembers") });
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

/** Joining another workspace changes the org behind every query: drop the whole cache so nothing from the
 * old workspace is shown, and let the active queries load again for the new one. */
export function useAcceptInvitation() {
  const qc = useQueryClient();
  return useMutation({
    ...q.acceptInvitationMutation(),
    onSuccess: () => qc.resetQueries(),
  });
}

/** Declining deletes the invitation; the answer is the updated /v1/me, so the notice goes at once. */
export function useDeclineInvitation() {
  const qc = useQueryClient();
  return useMutation({
    ...q.declineInvitationMutation(),
    onSuccess: (me) => qc.setQueryData(q.getMeQueryKey(), me),
  });
}
