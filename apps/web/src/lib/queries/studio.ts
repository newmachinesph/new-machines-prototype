"use client";

import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as q from "@/lib/api/gen/@tanstack/react-query.gen";
import { copyStudioPack } from "@/lib/api/gen/sdk.gen";
import { byOperation, orgScoped, useIsLive } from "./me";
import { useOrgPath } from "./org";

/** The Studio is part of the live workspace: its queries never run in the demo. */
function useStudioPath() {
  const { me, path, ready } = useOrgPath();
  const live = useIsLive();
  return { me, orgId: path.path.org_id, path, enabled: ready && live };
}

/** What a pack's steps can use, from the registry. Changes only when something is published. */
export function useStudioPalette() {
  const { me, path, enabled } = useStudioPath();
  return orgScoped(me, useQuery({ ...q.getStudioPaletteOptions(path), enabled, staleTime: 60_000 }));
}

export function useStudioAgents() {
  const { me, path, enabled } = useStudioPath();
  return orgScoped(me, useQuery({ ...q.listStudioAgentsOptions(path), enabled }));
}

export function useStudioAgent(key: string | undefined) {
  const { me, orgId, enabled } = useStudioPath();
  const options = q.getStudioAgentOptions({ path: { org_id: orgId, key: key ?? "" } });
  return orgScoped(me, useQuery({ ...options, enabled: enabled && key !== undefined }));
}

export function useStudioPacks() {
  const { me, path, enabled } = useStudioPath();
  return orgScoped(me, useQuery({ ...q.listStudioPacksOptions(path), enabled }));
}

export function useStudioPack(key: string | undefined) {
  const { me, orgId, enabled } = useStudioPath();
  const options = q.getStudioPackOptions({ path: { org_id: orgId, key: key ?? "" } });
  return orgScoped(me, useQuery({ ...options, enabled: enabled && key !== undefined }));
}

/** An unsaved copy of a ready-made pack or the org's own, to open in the editor. Read once: it is a draft. */
export function useStudioPackCopy(source: string | undefined) {
  const { me, orgId, enabled } = useStudioPath();
  return orgScoped(
    me,
    useQuery({
      queryKey: ["copyStudioPack", orgId, source],
      queryFn: async () => {
        const { data } = await copyStudioPack({
          path: { org_id: orgId },
          body: { source: source ?? "" },
          throwOnError: true,
        });
        return data;
      },
      enabled: enabled && !!source,
      staleTime: Infinity,
      gcTime: 0,
      retry: false,
    }),
  );
}

/** The saved version's workflow.yaml; fetched only while the YAML dialog shows it. */
export function useStudioPackWorkflow(key: string | undefined, open: boolean) {
  const { me, orgId, enabled } = useStudioPath();
  const options = q.getStudioPackWorkflowOptions({ path: { org_id: orgId, key: key ?? "" } });
  return orgScoped(me, useQuery({ ...options, enabled: enabled && open && key !== undefined }));
}

/** An agent change shows in the Studio lists, the palette and the agent catalog. */
function refreshAgents(qc: QueryClient) {
  for (const id of ["listStudioAgents", "getStudioAgent", "getStudioPalette", "listAgents", "getAgent"])
    void qc.invalidateQueries({ predicate: byOperation(id) });
}

/** A pack change shows in the Studio, the org's marketplace and the agents' "used by". */
function refreshPacks(qc: QueryClient) {
  for (const id of [
    "listStudioPacks",
    "getStudioPack",
    "getStudioPackWorkflow",
    "listStudioAgents",
    "listWorkflowPacks",
    "getWorkflowPack",
  ])
    void qc.invalidateQueries({ predicate: byOperation(id) });
}

export function useCreateStudioAgent() {
  const qc = useQueryClient();
  return useMutation({ ...q.createStudioAgentMutation(), onSettled: () => refreshAgents(qc) });
}

/** Saving an agent also rebuilds the packs that use it, so their cached versions are stale too. */
export function useSaveStudioAgent() {
  const qc = useQueryClient();
  return useMutation({
    ...q.saveStudioAgentMutation(),
    onSettled: () => {
      refreshAgents(qc);
      refreshPacks(qc);
    },
  });
}

export const useValidateStudioAgent = () => useMutation(q.validateStudioAgentMutation());

export function useCreateStudioPack() {
  const qc = useQueryClient();
  return useMutation({ ...q.createStudioPackMutation(), onSettled: () => refreshPacks(qc) });
}

/** May answer 409 RUNS_IN_PROGRESS when a rename meets runs in progress; the editor says so. */
export function useSaveStudioPack() {
  const qc = useQueryClient();
  return useMutation({ ...q.saveStudioPackMutation(), onSettled: () => refreshPacks(qc) });
}

/** Pass `query: { key }` for a saved pack, so its own name is not counted against it. */
export const useValidateStudioPack = () => useMutation(q.validateStudioPackMutation());

export const useImportStudioWorkflow = () => useMutation(q.importStudioWorkflowMutation());

/** A sandbox test run (`sandboxTest: true`) appears in the run list at once. */
export function useTestStudioPack() {
  const qc = useQueryClient();
  return useMutation({
    ...q.testStudioPackMutation(),
    onSettled: () => void qc.invalidateQueries({ predicate: byOperation("listWorkflowRuns") }),
  });
}
