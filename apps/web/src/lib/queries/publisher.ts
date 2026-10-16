"use client";

import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as q from "@/lib/api/gen/@tanstack/react-query.gen";
import { isManager } from "@/lib/roles";
import { byOperation, orgScoped, useIsLive } from "./me";
import { useOrgPath } from "./org";

/** The workspace's publisher profile. Live workspace only: never requested in the demo. */
export function usePublisher() {
  const { me, path, ready } = useOrgPath();
  const live = useIsLive();
  // Only owners and admins see publishing: a member is never shown it, and the API answers them 403.
  const enabled = ready && live && isManager(me.data?.role);
  return orgScoped(me, useQuery({ ...q.getPublisherOptions(path), enabled }));
}

/** Returned from onSettled so the mutation stays pending until fresh data lands. */
const refresh = (qc: QueryClient) => qc.invalidateQueries({ predicate: byOperation("getPublisher") });

export function useSavePublisher() {
  const qc = useQueryClient();
  return useMutation({ ...q.savePublisherMutation(), onSettled: () => refresh(qc) });
}

export function useDisablePublisher() {
  const qc = useQueryClient();
  return useMutation({ ...q.disablePublisherMutation(), onSettled: () => refresh(qc) });
}
