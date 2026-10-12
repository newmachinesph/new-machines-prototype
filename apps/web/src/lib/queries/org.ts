"use client";

import { useQuery } from "@tanstack/react-query";
import { ORG_ID } from "@/lib/api/client";
import {
  getOrganizationOptions,
  listAttentionOptions,
  listConnectionsOptions,
} from "@/lib/api/gen/@tanstack/react-query.gen";

const org = { path: { org_id: ORG_ID } };
export const useOrg = () => useQuery(getOrganizationOptions(org));
export const useAttention = () => useQuery({ ...listAttentionOptions(org), refetchInterval: 10_000 });
export const useConnections = () => useQuery(listConnectionsOptions());
