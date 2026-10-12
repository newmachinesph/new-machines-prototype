"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  opsCreateTenantMutation,
  opsGetTenantOptions,
  opsListAuditOptions,
  opsListTenantsOptions,
  opsReactivateTenantMutation,
  opsSetTenantPlanMutation,
  opsSetTenantSpendCapMutation,
  opsSuspendTenantMutation,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import type { Tenant } from "@/lib/api/gen/types.gen";
import { byOp, OPS_SIDE_EFFECTS } from "./invalidate";

export type TenantStatus = Tenant["status"];

export const useTenants = (q: { status?: TenantStatus; q?: string } = {}) =>
  useQuery(opsListTenantsOptions({ query: { status: q.status ?? null, q: q.q || null } }));

export const useTenant = (id: string) => useQuery(opsGetTenantOptions({ path: { tenant_id: id } }));

export const useTenantAudit = (id: string) =>
  useQuery(opsListAuditOptions({ query: { targetType: "tenant", targetId: id, limit: 10 } }));

function useInvalidate() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries(byOp("opsListTenants", "opsGetTenant", ...OPS_SIDE_EFFECTS));
}

export function useCreateTenant() {
  const invalidate = useInvalidate();
  return useMutation({ ...opsCreateTenantMutation(), onSuccess: invalidate });
}

export function useSuspendTenant() {
  const invalidate = useInvalidate();
  return useMutation({ ...opsSuspendTenantMutation(), onSuccess: invalidate });
}

export function useReactivateTenant() {
  const invalidate = useInvalidate();
  return useMutation({ ...opsReactivateTenantMutation(), onSuccess: invalidate });
}

export function useSetTenantPlan() {
  const invalidate = useInvalidate();
  return useMutation({ ...opsSetTenantPlanMutation(), onSuccess: invalidate });
}

export function useSetTenantSpendCap() {
  const invalidate = useInvalidate();
  return useMutation({ ...opsSetTenantSpendCapMutation(), onSuccess: invalidate });
}
