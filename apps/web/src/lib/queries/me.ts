"use client";

import { type UseQueryResult, useQuery } from "@tanstack/react-query";
import { getMeOptions } from "@/lib/api/gen/@tanstack/react-query.gen";
import type { Me } from "@/lib/api/gen/types.gen";

/** The signed-in user and the workspace they act in. Read once per session; sign-out clears the cache. */
export const useMe = () => useQuery({ ...getMeOptions(), staleTime: Infinity });

/** The signed-in user's org id; undefined until /v1/me has answered. */
export const useOrgId = () => useMe().data?.orgId;

/** True in the seeded demo workspace, false in a live workspace or while /v1/me loads. Only labels and the
 * pinned clock depend on it; data never does. */
export const useIsDemo = () => useMe().data?.workspace === "demo";

/** True once /v1/me says this is a live workspace: times then follow the real clock. */
export const useIsLive = () => useMe().data?.workspace === "live";

/**
 * An org-scoped query waits for /v1/me (it is disabled until then). Should /v1/me fail, the query reports
 * that error instead of loading forever.
 */
export function orgScoped<T extends UseQueryResult<unknown, unknown>>(me: UseQueryResult<Me, unknown>, query: T): T {
  if (!me.isError) return query;
  return { ...query, isPending: false, isError: true, error: me.error, status: "error" } as T;
}

/** Matches every cached query of one generated operation, whatever its parameters. */
export const byOperation =
  (id: string) =>
  (query: { queryKey: readonly unknown[] }): boolean =>
    (query.queryKey[0] as { _id?: string } | undefined)?._id === id;
