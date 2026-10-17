"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import {
  getAgentOptions,
  getCatalogTaxonomyOptions,
  getWorkflowPackOptions,
  installWorkflowPackMutation,
  listConnectionsQueryKey,
  listAgentsOptions,
  listAgentsQueryKey,
  listWorkflowPacksOptions,
  listWorkflowPacksQueryKey,
  suggestWorkflowPackMutation,
  upgradeWorkflowPackMutation,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import { useAgentText, usePackText } from "../content-text";
import { byOperation, useOrgId } from "./me";

export const usePacks = (enabled = true) => useQuery({ ...listWorkflowPacksOptions(), enabled });
export const usePack = (slug: string) => useQuery(getWorkflowPackOptions({ path: { slug } }));
export const useTaxonomy = () => useQuery({ ...getCatalogTaxonomyOptions(), staleTime: Infinity });
export const useAgents = () => useQuery({ ...listAgentsOptions(), staleTime: Infinity });

export const useAgent = (id: string) => useQuery(getAgentOptions({ path: { agent_id: id } }));

/**
 * An agent's name for breadcrumbs, in the interface language for our own agents; shares the agent page's query,
 * so it costs no extra request there.
 */
export function useAgentName(id: string | undefined) {
  const { data } = useQuery({ ...getAgentOptions({ path: { agent_id: id ?? "" } }), enabled: id !== undefined });
  const agentText = useAgentText();
  return id && data ? agentText(data).name : undefined;
}

export function useAgentById() {
  const { data } = useAgents();
  return useCallback((id: string) => data?.find((a) => a.id === id), [data]);
}

/** Pack names for breadcrumbs and rows, from the cached list, in the interface language for our own packs. */
export function usePackName(slug: string | undefined) {
  const { data } = usePacks();
  const packText = usePackText();
  const pack = slug ? data?.find((p) => p.slug === slug) : undefined;
  return pack ? packText(pack).name : undefined;
}

/** What an add or an update of a pack changes: the lists and details, the Studio's pack list, the needed apps. */
const refreshInstalled = (qc: QueryClient) =>
  Promise.all([
    qc.invalidateQueries({ queryKey: listWorkflowPacksQueryKey() }),
    // Agents carry their listing's update state too.
    qc.invalidateQueries({ queryKey: listAgentsQueryKey() }),
    // Every cached pack detail, whatever its slug.
    qc.invalidateQueries({ predicate: byOperation("getWorkflowPack") }),
    // The Studio's pack list says which of the org's own packs are added to the workspace.
    qc.invalidateQueries({ predicate: byOperation("listStudioPacks") }),
    // Adding a pack changes which apps the org needs, and the overview's checklist.
    qc.invalidateQueries({ queryKey: listConnectionsQueryKey() }),
  ]);

export function useInstallPack() {
  const qc = useQueryClient();
  // Settled, not only succeeded: a refused add (CONFLICT) also means the cached lists are out of date.
  return useMutation({ ...installWorkflowPackMutation(), onSettled: () => refreshInstalled(qc) });
}

/** Moves the workspace's added pack to the version its publisher has listed since. `upgrade` needs no ids. */
export function useUpgradePack(slug: string) {
  const qc = useQueryClient();
  const orgId = useOrgId();
  // A refused update (UP_TO_DATE, NOT_LISTED) means the cached "update available" is stale: refresh either way.
  const m = useMutation({ ...upgradeWorkflowPackMutation(), onSettled: () => refreshInstalled(qc) });
  const { mutate } = m;
  const upgrade = useCallback(
    (options?: Parameters<typeof mutate>[1]) => {
      if (orgId) mutate({ path: { org_id: orgId, slug } }, options);
    },
    [mutate, orgId, slug],
  );
  // `ready` is false until the signed-in workspace is known; callers disable the action rather than do nothing.
  return { upgrade, isPending: m.isPending, ready: orgId !== undefined };
}

export const useSuggestPack = () => useMutation(suggestWorkflowPackMutation());
