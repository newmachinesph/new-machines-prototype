"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  opsExportDefinitionOptions,
  opsGetDefinitionOptions,
  opsGetDefinitionQueryKey,
  opsListDefinitionsOptions,
  opsPublishDefinitionMutation,
  opsValidateDefinitionMutation,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import type { DefinitionSummary } from "@/lib/api/gen/types.gen";
import { ApiError } from "@/lib/api/errors";
import { byOp, OPS_SIDE_EFFECTS } from "./invalidate";

export type DefinitionKind = DefinitionSummary["kind"];

/**
 * A publish changes the registry and everything read from it: the definitions list and details, memory spaces
 * (from memory_space definitions) and marketplace classification (from pack definitions).
 */
const DEFINITION_QUERIES = [
  "opsListDefinitions",
  "opsGetDefinition",
  "opsExportDefinition",
  "opsListMemorySpaces",
  "opsListPacks",
  "opsGetPack",
  ...OPS_SIDE_EFFECTS,
] as const;

export const useDefinitions = () => useQuery(opsListDefinitionsOptions());

/** One definition at `version`, or its latest version when `version` is null. */
export const useDefinition = (kind: DefinitionKind, key: string, version?: number | null) =>
  useQuery(opsGetDefinitionOptions({ path: { kind, key }, query: version ? { version } : undefined }));

/** The latest detail of every definition of one kind, for pages that summarise their bodies (agents, contracts). */
export function useDefinitionsOfKind(kind: DefinitionKind) {
  const list = useDefinitions();
  const keys = (list.data ?? []).filter((d) => d.kind === kind).map((d) => d.key);
  const details = useQueries({ queries: keys.map((key) => opsGetDefinitionOptions({ path: { kind, key } })) });
  return { list, details };
}

/** Checks an edit without saving it. Open to every operator, support included. */
export const useValidateDefinition = () => useMutation(opsValidateDefinitionMutation());

/** Publishes an edit as the next version, or creates an unknown kind/key as version 1. */
export function usePublishDefinition() {
  const qc = useQueryClient();
  return useMutation({
    ...opsPublishDefinitionMutation(),
    onSuccess: (detail, { path }) => {
      // The latest detail is the response, so the editor shows it at once (a new definition's 404 included).
      qc.setQueryData(opsGetDefinitionQueryKey({ path }), detail);
      return qc.invalidateQueries(byOp(...DEFINITION_QUERIES));
    },
    onError: (error) => {
      // Someone published since the edit started: fetch the new latest so the editor can say which version.
      if (error instanceof ApiError && error.code === "VERSION_CONFLICT") {
        return qc.invalidateQueries(byOp("opsGetDefinition", "opsListDefinitions"));
      }
    },
  });
}

/** The files of one version as {path: text}, on demand for Export. */
export function useFetchExport() {
  const qc = useQueryClient();
  return (kind: DefinitionKind, key: string, version?: number | null) =>
    qc.fetchQuery(opsExportDefinitionOptions({ path: { kind, key }, query: version ? { version } : undefined }));
}
