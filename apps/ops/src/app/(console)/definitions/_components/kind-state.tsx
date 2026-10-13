"use client";

import type { ReactNode } from "react";
import { isRuntimeOff, RuntimeOff } from "@/components/runtime-off";
import { Skeleton } from "@/components/skeleton";
import { ApiError } from "@/lib/api/errors";
import type { DefinitionDetail } from "@/lib/api/gen/types.gen";
import { type DefinitionKind, useDefinitionsOfKind } from "@/lib/queries/definitions";

/**
 * Loads the latest detail of every definition of `kind` and renders them, like `QueryState` does for one query:
 * a skeleton while loading (or signing out after a 401), the runtime-off empty state, or the error boundary.
 */
export function KindState({
  kind,
  what,
  children,
}: {
  kind: DefinitionKind;
  /** The page's subject for the runtime-off message, plural: "Agents". */
  what: string;
  children: (details: DefinitionDetail[]) => ReactNode;
}) {
  const { list, details } = useDefinitionsOfKind(kind);
  const error = list.error ?? details.find((d) => d.error)?.error;
  if (isRuntimeOff(error)) return <RuntimeOff what={what} />;
  const unauthorized = error instanceof ApiError && error.status === 401;
  if (error && !unauthorized) throw error;
  if (unauthorized || list.isPending || details.some((d) => d.isPending)) return <Skeleton className="h-96" />;
  return <>{children(details.flatMap((d) => (d.data ? [d.data] : [])))}</>;
}
