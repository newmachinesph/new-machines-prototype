"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  opsApproveListingMutation,
  opsGetListingOptions,
  opsListListingsOptions,
  opsRejectListingMutation,
  opsRelistListingMutation,
  opsRequestListingChangesMutation,
  opsUnlistListingMutation,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import type { OpsListListingsData } from "@/lib/api/gen/types.gen";
import { byOp, OPS_SIDE_EFFECTS } from "./invalidate";

export type ListingAction = "approve" | "request-changes" | "reject" | "unlist" | "relist";
export type ListingStatusFilter = NonNullable<NonNullable<OpsListListingsData["query"]>["status"]>;

const LISTING_QUERIES = ["opsListListings", "opsGetListing", ...OPS_SIDE_EFFECTS] as const;

/** Listings, optionally narrowed to one status; no status means every listing. */
export const useListings = (status?: ListingStatusFilter) =>
  useQuery(opsListListingsOptions(status ? { query: { status } } : undefined));

export const useListing = (id: string) => useQuery(opsGetListingOptions({ path: { listing_id: id } }));

/** One entry point for the review moves: `run("approve", id, reason)`. Rejects with the API's problem on a bad move. */
export function useListingAction() {
  const qc = useQueryClient();
  const onSuccess = () => qc.invalidateQueries(byOp(...LISTING_QUERIES));
  const approve = useMutation({ ...opsApproveListingMutation(), onSuccess });
  const requestChanges = useMutation({ ...opsRequestListingChangesMutation(), onSuccess });
  const reject = useMutation({ ...opsRejectListingMutation(), onSuccess });
  const unlist = useMutation({ ...opsUnlistListingMutation(), onSuccess });
  const relist = useMutation({ ...opsRelistListingMutation(), onSuccess });

  const run = (action: ListingAction, id: string, reason: string) => {
    const options = { path: { listing_id: id }, body: { reason } };
    switch (action) {
      case "approve":
        return approve.mutateAsync(options);
      case "request-changes":
        return requestChanges.mutateAsync(options);
      case "reject":
        return reject.mutateAsync(options);
      case "unlist":
        return unlist.mutateAsync(options);
      case "relist":
        return relist.mutateAsync(options);
    }
  };
  return { run };
}
