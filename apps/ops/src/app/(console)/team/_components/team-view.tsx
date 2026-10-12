"use client";

import { ShieldAlert, ShieldCheck } from "lucide-react";
import { type Column, DataTable } from "@/components/data-table";
import { RolePill } from "@/components/ops-shell";
import { QueryState } from "@/components/query-state";
import { Skeleton } from "@/components/skeleton";
import { Callout, Section } from "@/components/ui";
import type { OpsTeamMember } from "@/lib/api/gen/types.gen";
import { ago } from "@/lib/format";
import { useTeam } from "@/lib/queries/team";

const columns: Column<OpsTeamMember>[] = [
  { key: "name", header: "Name", cell: (m) => <span className="font-medium">{m.name}</span> },
  { key: "email", header: "Email", className: "hidden sm:table-cell", cell: (m) => m.email },
  { key: "role", header: "Role", cell: (m) => <RolePill role={m.role} /> },
  { key: "active", header: "Last active", cell: (m) => ago(m.lastActiveAt) },
  {
    key: "mfa",
    header: "MFA",
    cell: (m) =>
      m.mfa ? (
        <span className="inline-flex items-center gap-1.5 text-sm">
          <ShieldCheck className="size-4 text-machine" aria-hidden /> On
        </span>
      ) : (
        <span className="inline-flex items-center gap-1.5 text-sm font-medium text-blocked">
          <ShieldAlert className="size-4" aria-hidden /> Off
        </span>
      ),
  },
];

export function TeamView() {
  const team = useTeam();
  return (
    <div className="space-y-4">
      <QueryState query={team} skeleton={<Skeleton className="h-64" />}>
        {(rows) => (
          <Section>
            <DataTable
              label="Ops team"
              columns={columns}
              rows={rows}
              rowKey={(m) => m.email}
              empty="No operators found. Check the OPS_ADMIN_EMAILS setting on the API."
            />
          </Section>
        )}
      </QueryState>
      <Callout tone="info" title="Membership is not edited here">
        Operator access is managed by the API&apos;s OPS_ADMIN_EMAILS and OPS_SUPPORT_EMAILS settings.
      </Callout>
    </div>
  );
}
