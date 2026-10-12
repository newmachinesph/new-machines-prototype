"use client";

import { useQuery } from "@tanstack/react-query";
import { opsListRunsOptions, opsListTenantsOptions } from "@/lib/api/gen/@tanstack/react-query.gen";
import type { RunStatus } from "@/lib/types";

export const useRuns = (q: { status?: RunStatus | null; tenant?: string | null }) =>
  useQuery(opsListRunsOptions({ query: { status: q.status ?? undefined, tenant: q.tenant ?? undefined } }));

/** Tenants for the filter's options. */
export const useTenantOptions = () => useQuery(opsListTenantsOptions());
