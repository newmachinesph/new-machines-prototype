"use client";

import { Section, SimTag } from "@/components/ui";
import type { ServiceStatus } from "@/lib/api/gen/types.gen";
import { cn } from "@/lib/cn";
import { pct } from "@/lib/format";

const SERVICE_STATUS: Record<ServiceStatus["status"], { label: string; dot: string }> = {
  operational: { label: "Operational", dot: "bg-ink" },
  degraded: { label: "Degraded", dot: "bg-human" },
  outage: { label: "Outage", dot: "bg-blocked" },
};
function ServiceTile({ s }: { s: ServiceStatus }) {
  const st = SERVICE_STATUS[s.status];
  return (
    <li className="flex flex-col gap-2 rounded-[10px] border border-rule bg-paper px-4 py-3">
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-semibold">{s.name}</span>
        <span className="inline-flex shrink-0 items-center gap-1.5 text-xs font-medium">
          <span aria-hidden className={cn("size-2 rounded-full", st.dot)} />
          {st.label}
        </span>
      </div>
      <dl className="flex gap-6 text-xs text-muted">
        <div>
          <dt>Uptime, 30 days</dt>
          <dd className="tnum mt-0.5 text-sm font-medium text-ink">{pct(s.uptime30d, 2)}</dd>
        </div>
        <div>
          <dt>p95 latency</dt>
          <dd className="tnum mt-0.5 text-sm font-medium text-ink">{s.latencyP95Ms} ms</dd>
        </div>
      </dl>
      {s.note ? <p className="text-xs leading-snug text-grey-700">{s.note}</p> : null}
    </li>
  );
}

export function ServiceGrid({ services }: { services: ServiceStatus[] }) {
  return (
    <Section title="Services" aside={<SimTag />}>
      <ul className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {services.map((s) => (
          <ServiceTile key={s.key} s={s} />
        ))}
      </ul>
    </Section>
  );
}
