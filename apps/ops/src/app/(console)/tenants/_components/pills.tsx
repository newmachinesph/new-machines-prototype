import { Pill, type Tone } from "@/components/ui";
import type { Tenant } from "@/lib/api/gen/types.gen";

const STATUS: Record<Tenant["status"], { tone: Tone; label: string }> = {
  active: { tone: "ink", label: "Active" },
  trial: { tone: "machine", label: "Trial" },
  suspended: { tone: "blocked", label: "Suspended" },
  churned: { tone: "quiet", label: "Churned" },
};
const HEALTH: Record<Tenant["health"], { tone: Tone; label: string }> = {
  healthy: { tone: "machine", label: "Healthy" },
  watch: { tone: "human", label: "Watch" },
  at_risk: { tone: "blocked", label: "At risk" },
};
const PLAN: Record<Tenant["plan"], Tone> = { Starter: "quiet", Pro: "policy", Enterprise: "policy" };

export const StatusPill = ({ status }: { status: Tenant["status"] }) => (
  <Pill tone={STATUS[status].tone}>{STATUS[status].label}</Pill>
);
export const HealthPill = ({ health }: { health: Tenant["health"] }) => (
  <Pill tone={HEALTH[health].tone}>{HEALTH[health].label}</Pill>
);
export const PlanPill = ({ plan }: { plan: Tenant["plan"] }) => <Pill tone={PLAN[plan]}>{plan}</Pill>;
