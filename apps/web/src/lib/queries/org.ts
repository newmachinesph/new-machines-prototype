"use client";

import { useQuery } from "@tanstack/react-query";
import {
  getOrganizationOptions,
  listAttentionOptions,
  listConnectionsOptions,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import type { Connection as ApiConnection } from "@/lib/api/gen/types.gen";
import type { Connection } from "@/lib/types";
import { orgScoped, useMe } from "./me";

/** `{ path: { org_id } }` for the signed-in user's org, and whether it is known yet. */
export function useOrgPath() {
  const me = useMe();
  const orgId = me.data?.orgId;
  return { me, path: { path: { org_id: orgId ?? "" } }, ready: orgId !== undefined };
}

export function useOrg() {
  const { me, path, ready } = useOrgPath();
  return orgScoped(me, useQuery({ ...getOrganizationOptions(path), enabled: ready }));
}

export function useAttention() {
  const { me, path, ready } = useOrgPath();
  return orgScoped(me, useQuery({ ...listAttentionOptions(path), refetchInterval: 10_000, enabled: ready }));
}

/** The API may leave `revoked` out (it defaults to `[]` on the wire); every card can count on the list. */
export const withRevoked = (rows: ApiConnection[]): Connection[] =>
  rows.map((c) => ({ ...c, revoked: c.revoked ?? [] }));

export const useConnections = () => useQuery({ ...listConnectionsOptions(), select: withRevoked });

/** Apps a run can use: connected, or connected to sandbox data. */
export const isUsable = (c: Connection) => c.status === "connected" || c.status === "sandbox";

/** The apps of `needs` (app names) that are not usable yet, in the order given. */
export function missingApps(needs: string[], conns: Connection[]): string[] {
  const usable = new Set(conns.filter(isUsable).map((c) => c.app.toLowerCase()));
  return [...new Set(needs)].filter((a) => !usable.has(a.toLowerCase()));
}
