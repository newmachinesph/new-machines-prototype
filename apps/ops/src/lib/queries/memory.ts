"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  opsAddMemoryItemMutation,
  opsDeleteMemoryItemMutation,
  opsListMemoryItemsOptions,
  opsListMemorySpacesOptions,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import { byOp, OPS_SIDE_EFFECTS } from "./invalidate";

/** Adding or deleting an item changes the space's items and its item count. */
const MEMORY_QUERIES = ["opsListMemorySpaces", "opsListMemoryItems", ...OPS_SIDE_EFFECTS] as const;

export const useMemorySpaces = () => useQuery(opsListMemorySpacesOptions());

/** Items of one space, newest first. Idle until a space is chosen. */
export const useMemoryItems = (space: string | null) =>
  useQuery({ ...opsListMemoryItemsOptions({ path: { space: space ?? "" } }), enabled: Boolean(space) });

export function useAddMemoryItem() {
  const qc = useQueryClient();
  return useMutation({
    ...opsAddMemoryItemMutation(),
    onSuccess: () => qc.invalidateQueries(byOp(...MEMORY_QUERIES)),
  });
}

export function useDeleteMemoryItem() {
  const qc = useQueryClient();
  return useMutation({
    ...opsDeleteMemoryItemMutation(),
    onSuccess: () => qc.invalidateQueries(byOp(...MEMORY_QUERIES)),
  });
}
