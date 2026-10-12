"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  opsDeclareIncidentMutation,
  opsGetHealthOptions,
  opsUpdateIncidentMutation,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import { byOp, OPS_SIDE_EFFECTS } from "./invalidate";

export const useHealth = () => useQuery(opsGetHealthOptions());

const refresh = (qc: ReturnType<typeof useQueryClient>) =>
  qc.invalidateQueries(byOp("opsGetHealth", ...OPS_SIDE_EFFECTS));

export function useDeclareIncident() {
  const qc = useQueryClient();
  return useMutation({ ...opsDeclareIncidentMutation(), onSuccess: () => refresh(qc) });
}

export function useUpdateIncident() {
  const qc = useQueryClient();
  return useMutation({ ...opsUpdateIncidentMutation(), onSuccess: () => refresh(qc) });
}
