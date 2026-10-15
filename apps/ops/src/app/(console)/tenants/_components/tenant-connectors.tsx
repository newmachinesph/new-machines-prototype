import { Pill, Section, SimTag } from "@/components/ui";
import type { TenantConnection } from "@/lib/api/gen/types.gen";

const CONNECTION: Record<TenantConnection["status"], { tone: "ink" | "quiet" | "human" | "machine"; label: string }> = {
  connected: { tone: "ink", label: "Connected" },
  not_connected: { tone: "quiet", label: "Not connected" },
  sandbox: { tone: "machine", label: "Sandbox" },
  needs_reauth: { tone: "human", label: "Needs sign-in again" },
  pending: { tone: "human", label: "Signing in" },
};

/** How the tenant reaches the app: its own account through Composio, or sandbox data. Demo fixtures have no mode. */
function Mode({ mode }: { mode: TenantConnection["mode"] }) {
  if (mode === "sandbox") return <SimTag />;
  if (mode === "composio")
    return <span className="rounded-sm bg-grey-100 px-1.5 py-px text-[11px] font-medium text-ink">Real</span>;
  return null;
}

/** The tenant's app connections: status, and whether each reaches a real account or simulated data. */
export function TenantConnectors({ connections }: { connections: TenantConnection[] }) {
  return (
    <Section title="Connectors">
      {connections.length === 0 ? (
        <p className="px-5 py-8 text-sm text-muted">No connectors set up.</p>
      ) : (
        <ul className="divide-y divide-rule">
          {connections.map((c) => (
            <li key={c.app} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
              <span className="flex items-center gap-2">
                <span className="font-medium">{c.app}</span>
                <Mode mode={c.mode} />
              </span>
              <Pill tone={CONNECTION[c.status].tone}>{CONNECTION[c.status].label}</Pill>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
