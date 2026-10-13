"use client";

import { useQuery } from "@tanstack/react-query";
import { opsGetMeOptions } from "@/lib/api/gen/@tanstack/react-query.gen";

/** The signed-in operator: email and ops role. Stable for the session, so it is never refetched in the background. */
export const useMe = () => useQuery({ ...opsGetMeOptions(), staleTime: Infinity });

/** Owners and admins can change things; support is read-only and the API answers its writes with 403. */
export function useCanWrite(): boolean {
  const role = useMe().data?.role;
  return role === "owner" || role === "admin";
}

export type OpsWorkspace = "demo" | "live";

/**
 * Which workspace the API serves. Demo while the ops `me` query is loading or failed, so the demo console
 * never flickers into its live layout.
 */
export function useOpsWorkspace(): OpsWorkspace {
  return useMe().data?.workspace === "live" ? "live" : "demo";
}
