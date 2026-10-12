import { Stat } from "@/components/stat";
import type { OpsOverview } from "@/lib/api/gen/types.gen";
import { count, money, pct } from "@/lib/format";
import { capRatio, meterFill } from "@/lib/cap";
import { CAP_FULL, CAP_WARN, isSimulated } from "./logic";

/** Spend against the platform daily cap. The fill turns amber past 80% and red at the cap. */
export function CapMeter({ spentMinor, capMinor }: { spentMinor: number; capMinor: number }) {
  const ratio = capRatio(spentMinor, capMinor);
  const fill = ratio >= CAP_FULL ? "bg-blocked" : ratio >= CAP_WARN ? "bg-human" : "bg-ink";
  return (
    <div>
      <div
        role="meter"
        aria-label="AI spend today against the platform daily cap"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(meterFill(ratio) * 100)}
        aria-valuetext={`${Math.round(ratio * 100)}% of the daily cap`}
        className="h-1.5 overflow-hidden rounded-full bg-grey-100"
      >
        <div className={`h-full rounded-full ${fill}`} style={{ width: `${meterFill(ratio) * 100}%` }} />
      </div>
      <div className="mt-1.5">
        {Math.round(ratio * 100)}% of {money(capMinor)} cap
      </div>
    </div>
  );
}

export function KpiStrip({ overview }: { overview: OpsOverview }) {
  const { kpis: k, simulatedFields: sim } = overview;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
      <Stat
        label="Active tenants"
        value={count(k.activeTenants)}
        sub={`${count(k.trialTenants)} on trial`}
        href="/tenants?status=active"
      />
      <Stat label="Runs today" value={count(k.runsToday)} simulated={isSimulated(sim, "kpis.runsToday")} href="/runs" />
      <Stat label="Success, 7d" value={pct(k.runSuccessRate7d)} simulated={isSimulated(sim, "kpis.runSuccessRate7d")} />
      <Stat
        label="Open reviewer tasks"
        value={count(k.openHumanTasks)}
        sub={`${count(k.pendingApprovals)} pending approval${k.pendingApprovals === 1 ? "" : "s"}`}
        tone={k.openHumanTasks > 0 ? "human" : "default"}
        href="/workforce"
      />
      <Stat
        label="Open incidents"
        value={count(k.incidentsOpen)}
        sub={k.incidentsOpen === 0 ? "All services normal" : "See platform health"}
        tone={k.incidentsOpen > 0 ? "blocked" : "default"}
        href="/health"
      />
      <Stat
        label="AI spend"
        value={money(k.aiSpendToday)}
        sub={<CapMeter spentMinor={k.aiSpendToday.amountMinor} capMinor={k.platformDailyCap.amountMinor} />}
        simulated={isSimulated(sim, "kpis.aiSpendToday")}
      />
    </div>
  );
}
