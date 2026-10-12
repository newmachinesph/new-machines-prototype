"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  opsAddConnectorMutation,
  opsDisableConnectorMutation,
  opsEnableConnectorMutation,
  opsHealthCheckConnectorMutation,
  opsListAvailableToolkitsOptions,
  opsListConnectorsOptions,
  opsSetConnectorDefaultsMutation,
} from "@/lib/api/gen/@tanstack/react-query.gen";
import { byOp, OPS_SIDE_EFFECTS } from "./invalidate";

/** Connector changes reach the connector table, the toolkit list, tenant connection views and the overview's attention queue. */
const CONNECTOR_QUERIES = [
  "opsListConnectors",
  "opsListAvailableToolkits",
  "opsListTenants",
  "opsGetTenant",
  ...OPS_SIDE_EFFECTS,
] as const;

export const useConnectors = () => useQuery(opsListConnectorsOptions());

/** Simulated toolkit discovery. Only fetched while the Add connector dialog is open. */
export const useAvailableToolkits = (enabled: boolean) => useQuery({ ...opsListAvailableToolkitsOptions(), enabled });

export function useAddConnector() {
  const qc = useQueryClient();
  return useMutation({
    ...opsAddConnectorMutation(),
    onSuccess: () => qc.invalidateQueries(byOp(...CONNECTOR_QUERIES)),
  });
}

export function useEnableConnector() {
  const qc = useQueryClient();
  return useMutation({
    ...opsEnableConnectorMutation(),
    onSuccess: () => qc.invalidateQueries(byOp(...CONNECTOR_QUERIES)),
  });
}

export function useDisableConnector() {
  const qc = useQueryClient();
  return useMutation({
    ...opsDisableConnectorMutation(),
    onSuccess: () => qc.invalidateQueries(byOp(...CONNECTOR_QUERIES)),
  });
}

export function useSetConnectorDefaults() {
  const qc = useQueryClient();
  return useMutation({
    ...opsSetConnectorDefaultsMutation(),
    onSuccess: () => qc.invalidateQueries(byOp(...CONNECTOR_QUERIES)),
  });
}

/** Takes no reason, but the API still writes an audit entry. */
export function useHealthCheckConnector() {
  const qc = useQueryClient();
  return useMutation({
    ...opsHealthCheckConnectorMutation(),
    onSuccess: () => qc.invalidateQueries(byOp(...CONNECTOR_QUERIES)),
  });
}
