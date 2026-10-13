"use client";

import { parseAsStringLiteral, useQueryState } from "nuqs";
import { useEffect } from "react";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { useHealth } from "@/lib/queries/health";
import { useCanWrite, useMe, useOpsWorkspace } from "@/lib/queries/ops";
import { DeclareIncident } from "./declare-incident";
import { IncidentList } from "./incident-list";
import { sortIncidents } from "./incidents";
import { ServiceGrid } from "./service-grid";

const ACTIONS = ["declare"] as const;

export function HealthView() {
  const q = useHealth();
  const me = useMe();
  const canWrite = useCanWrite();
  // Incidents are fixtures in the live workspace, and the API refuses to declare or update them there.
  const live = useOpsWorkspace() === "live";
  const canDeclare = canWrite && !live;
  const [action, setAction] = useQueryState("action", parseAsStringLiteral(ACTIONS));

  // Support and the live workspace cannot declare, so a stale ?action=declare link is dropped once the role is
  // known.
  const roleKnown = me.data !== undefined;
  useEffect(() => {
    if (roleKnown && !canDeclare && action === "declare") void setAction(null);
  }, [roleKnown, canDeclare, action, setAction]);

  return (
    <QueryState
      query={q}
      skeleton={
        <div className="space-y-6">
          <Skeleton className="h-56" />
          <Skeleton className="h-64" />
        </div>
      }
    >
      {(h) => (
        <div className="space-y-6">
          <ServiceGrid services={h.services} />
          <IncidentList
            incidents={sortIncidents(h.incidents)}
            names={new Map(h.services.map((s) => [s.key, s.name]))}
            canWrite={canWrite}
            live={live}
            aside={
              live ? undefined : (
                <DeclareIncident
                  open={action === "declare"}
                  onOpenChange={(o) => void setAction(o ? "declare" : null)}
                  services={h.services}
                  canWrite={canWrite}
                />
              )
            }
          />
        </div>
      )}
    </QueryState>
  );
}
