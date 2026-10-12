"use client";

import { useQuery } from "@tanstack/react-query";
import { opsListAuditOptions } from "@/lib/api/gen/@tanstack/react-query.gen";

export const AUDIT_TARGET_TYPES = ["tenant", "pack", "connector", "reviewer", "guardrail", "incident"] as const;
export type AuditTargetType = (typeof AUDIT_TARGET_TYPES)[number];

export const AUDIT_LIMIT = 500;

export const useAudit = (f: { targetType?: AuditTargetType; targetId?: string }) =>
  useQuery(
    opsListAuditOptions({ query: { targetType: f.targetType, targetId: f.targetId || undefined, limit: AUDIT_LIMIT } }),
  );
