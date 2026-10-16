"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as q from "@/lib/api/gen/@tanstack/react-query.gen";
import { byOperation } from "./me";

/**
 * Submits a saved agent or pack for marketplace review. A submission shows in the Publisher tab's list and
 * detail, so both are refreshed once a submission is accepted.
 */
export function useSubmitListing(kind: "agent" | "pack") {
  const qc = useQueryClient();
  const options = kind === "agent" ? q.submitStudioAgentMutation() : q.submitStudioPackMutation();
  return useMutation({
    ...options,
    onSuccess: (data, vars) => {
      // The answer is the listing as it now stands: seed its cache so an earlier visit's version never shows.
      qc.setQueryData(q.getStudioListingQueryKey({ path: { org_id: vars.path.org_id, listing_id: data.id } }), data);
      for (const id of ["listStudioListings", "getStudioListing"])
        void qc.invalidateQueries({ predicate: byOperation(id) });
    },
  });
}
