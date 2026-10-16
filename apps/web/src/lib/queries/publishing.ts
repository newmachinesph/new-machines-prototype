"use client";

import { useQuery } from "@tanstack/react-query";
import * as q from "@/lib/api/gen/@tanstack/react-query.gen";
import type { StudioListing } from "@/lib/api/gen/types.gen";
import { isManager } from "@/lib/roles";
import { orgScoped, useIsLive } from "./me";
import { useOrgPath } from "./org";

/** How often a listing whose newest version is still being checked is read again. */
const CHECKING_POLL_MS = 5_000;

/** Checks settle only when a listing is read, so one still checking is read again until it moves on. */
export const listingPoll = (listing: StudioListing | undefined) =>
  listing?.latest.status === "checking" ? CHECKING_POLL_MS : false;

/** The list is read again while any of its listings is still being checked. */
export const listingsPoll = (list: StudioListing[] | undefined) =>
  list?.some((l) => l.latest.status === "checking") ? CHECKING_POLL_MS : false;

/** Publishing is part of the Developer Studio, so its queries never run in the demo workspace; only owners
 * and admins see it, so a member never asks (the API answers 403). */
function usePublishingPath() {
  const { me, path, ready } = useOrgPath();
  const live = useIsLive();
  return { me, orgId: path.path.org_id, path, enabled: ready && live && isManager(me.data?.role) };
}

/** The org's listings, each with its latest version and this month's numbers. */
export function useStudioListings() {
  const { me, path, enabled } = usePublishingPath();
  return orgScoped(
    me,
    useQuery({ ...q.listStudioListingsOptions(path), enabled, refetchInterval: (s) => listingsPoll(s.state.data) }),
  );
}

/** One listing with every version, newest first as the page shows them. */
export function useStudioListing(id: string | undefined) {
  const { me, orgId, enabled } = usePublishingPath();
  const options = q.getStudioListingOptions({ path: { org_id: orgId, listing_id: id ?? "" } });
  return orgScoped(
    me,
    useQuery({
      ...options,
      enabled: enabled && id !== undefined,
      refetchInterval: (s) => listingPoll(s.state.data),
    }),
  );
}

/** This month's earnings and the payout history; simulated money. */
export function useStudioEarnings() {
  const { me, path, enabled } = usePublishingPath();
  return orgScoped(me, useQuery({ ...q.getStudioEarningsOptions(path), enabled }));
}
