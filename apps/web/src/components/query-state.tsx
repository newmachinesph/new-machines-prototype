"use client";

import type { UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api/errors";

/**
 * Pending shows the skeleton, errors go to the nearest error.tsx, success renders the data. A 401 keeps the
 * skeleton: the client is already signing out and redirecting, so an error panel would only flash.
 */
export function QueryState<T>({
  query,
  skeleton,
  children,
}: {
  query: UseQueryResult<T, unknown>;
  skeleton: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (query.isPending) return <>{skeleton}</>;
  // A failed background refetch keeps the data it already has; only a failure with nothing to show is an error.
  const { data } = query;
  if (query.isError && data === undefined) {
    if (query.error instanceof ApiError && query.error.status === 401) return <>{skeleton}</>;
    throw query.error;
  }
  return <>{children(data as T)}</>;
}
