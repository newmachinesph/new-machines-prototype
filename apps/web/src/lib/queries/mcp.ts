"use client";

import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as q from "@/lib/api/gen/@tanstack/react-query.gen";
import { byOperation, orgScoped, useIsLive } from "./me";
import { useOrgPath } from "./org";

/** The org's own MCP servers. Part of the live workspace: the query never runs in the demo. */
export function useMcpServers() {
  const { me, path, ready } = useOrgPath();
  const live = useIsLive();
  return orgScoped(me, useQuery({ ...q.listMcpServersOptions(path), enabled: ready && live }));
}

/** A server change shows in its list, the org's connections and the Studio palette. */
function refresh(qc: QueryClient) {
  for (const id of ["listMcpServers", "listConnections", "getStudioPalette"])
    void qc.invalidateQueries({ predicate: byOperation(id) });
}

export function useAddMcpServer() {
  const qc = useQueryClient();
  return useMutation({ ...q.addMcpServerMutation(), gcTime: 0, onSettled: () => refresh(qc) });
}

export function useRefreshMcpServer() {
  const qc = useQueryClient();
  return useMutation({ ...q.refreshMcpServerMutation(), onSettled: () => refresh(qc) });
}

/** `on` and `off` switch one tool; a blocked tool cannot be switched on (409 TOOL_BLOCKED). */
export function useSwitchMcpTool() {
  const qc = useQueryClient();
  const on = useMutation({ ...q.switchMcpToolOnMutation(), onSettled: () => refresh(qc) });
  const off = useMutation({ ...q.switchMcpToolOffMutation(), onSettled: () => refresh(qc) });
  return { on, off };
}

export function useReplaceMcpToken() {
  const qc = useQueryClient();
  return useMutation({ ...q.replaceMcpServerTokenMutation(), gcTime: 0, onSettled: () => refresh(qc) });
}

export function useRemoveMcpServer() {
  const qc = useQueryClient();
  return useMutation({ ...q.removeMcpServerMutation(), onSettled: () => refresh(qc) });
}
