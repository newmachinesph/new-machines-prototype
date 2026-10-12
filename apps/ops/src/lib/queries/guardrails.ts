"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { opsListGuardrailsOptions, opsSetGuardrailMutation } from "@/lib/api/gen/@tanstack/react-query.gen";
import { byOp, OPS_SIDE_EFFECTS } from "./invalidate";

export const useGuardrails = () => useQuery(opsListGuardrailsOptions());

export function useSetGuardrail() {
  const qc = useQueryClient();
  return useMutation({
    ...opsSetGuardrailMutation(),
    onSuccess: () => qc.invalidateQueries(byOp("opsListGuardrails", ...OPS_SIDE_EFFECTS)),
  });
}
