"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  opsApprovePackMutation,
  opsCertifyPackMutation,
  opsCreatePackMutation,
  opsDeprecatePackMutation,
  opsGetPackOptions,
  opsListPacksOptions,
  opsRejectPackMutation,
  opsRepublishPackMutation,
  opsSubmitPackMutation,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import { byOp, OPS_SIDE_EFFECTS } from "./invalidate";

export type PackAction = "submit" | "approve" | "reject" | "deprecate" | "republish" | "certify";

/** Every pack list and detail variant, plus the overview and audit log every ops mutation touches. */
const PACK_QUERIES = ["opsListPacks", "opsGetPack", ...OPS_SIDE_EFFECTS] as const;

export const usePacks = () => useQuery(opsListPacksOptions());

export const usePack = (slug: string) => useQuery(opsGetPackOptions({ path: { slug } }));

export function useCreatePack() {
  const qc = useQueryClient();
  return useMutation({
    ...opsCreatePackMutation(),
    onSuccess: () => qc.invalidateQueries(byOp(...PACK_QUERIES)),
  });
}

/** One entry point for the state machine: `run("approve", slug, reason)`. Rejects with the API's problem on a bad move. */
export function usePackAction() {
  const qc = useQueryClient();
  const onSuccess = () => qc.invalidateQueries(byOp(...PACK_QUERIES));
  const submit = useMutation({ ...opsSubmitPackMutation(), onSuccess });
  const approve = useMutation({ ...opsApprovePackMutation(), onSuccess });
  const reject = useMutation({ ...opsRejectPackMutation(), onSuccess });
  const deprecate = useMutation({ ...opsDeprecatePackMutation(), onSuccess });
  const republish = useMutation({ ...opsRepublishPackMutation(), onSuccess });
  const certify = useMutation({ ...opsCertifyPackMutation(), onSuccess });

  return (action: PackAction, slug: string, reason: string) => {
    const options = { path: { slug }, body: { reason } };
    switch (action) {
      case "submit":
        return submit.mutateAsync(options);
      case "approve":
        return approve.mutateAsync(options);
      case "reject":
        return reject.mutateAsync(options);
      case "deprecate":
        return deprecate.mutateAsync(options);
      case "republish":
        return republish.mutateAsync(options);
      case "certify":
        return certify.mutateAsync(options);
    }
  };
}
