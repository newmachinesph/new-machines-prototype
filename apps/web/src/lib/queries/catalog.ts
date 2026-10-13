"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { ORG_ID } from "@/lib/api/client";
import {
  getAgentOptions,
  getCatalogTaxonomyOptions,
  getWorkflowPackOptions,
  installWorkflowPackMutation,
  listAgentsOptions,
  listWorkflowPacksOptions,
  listWorkflowPacksQueryKey,
  suggestWorkflowPackMutation,
} from "@/lib/api/gen/@tanstack/react-query.gen";

export const usePacks = (enabled = true) => useQuery({ ...listWorkflowPacksOptions(), enabled });
export const usePack = (slug: string) => useQuery(getWorkflowPackOptions({ path: { slug } }));
export const useTaxonomy = () => useQuery({ ...getCatalogTaxonomyOptions(), staleTime: Infinity });
export const useAgents = () => useQuery({ ...listAgentsOptions(), staleTime: Infinity });

export const useAgent = (id: string) => useQuery(getAgentOptions({ path: { agent_id: id } }));

/** An agent's name for breadcrumbs; shares the agent page's query, so it costs no extra request there. */
export function useAgentName(id: string | undefined) {
  const { data } = useQuery({ ...getAgentOptions({ path: { agent_id: id ?? "" } }), enabled: id !== undefined });
  return id ? data?.name : undefined;
}

export function useAgentById() {
  const { data } = useAgents();
  return useCallback((id: string) => data?.find((a) => a.id === id), [data]);
}

/** Pack names for breadcrumbs and rows, from the cached list. */
export function usePackName(slug: string | undefined) {
  const { data } = usePacks();
  return slug ? data?.find((p) => p.slug === slug)?.name : undefined;
}

export function useInstallPack() {
  const qc = useQueryClient();
  return useMutation({
    ...installWorkflowPackMutation(),
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: listWorkflowPacksQueryKey() }),
        // Every cached pack detail, whatever its slug.
        qc.invalidateQueries({
          predicate: (q) => (q.queryKey[0] as { _id?: string } | undefined)?._id === "getWorkflowPack",
        }),
      ]),
  });
}

export const useSuggestPack = () => useMutation(suggestWorkflowPackMutation());

export { ORG_ID };
