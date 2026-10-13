import { Stat } from "@/components/stat";
import { SampleTag } from "@/components/ui";
import type { OpsOverview } from "@/lib/api/gen/types.gen";
import { cn } from "@/lib/cn";
import { count, money, pct } from "@/lib/format";
import { capRatio, meterFill } from "@/lib/cap";
import { CAP_FULL, CAP_WARN, failedToday, fieldTag } from "./logic";

/** Spend against the platform daily cap. The fill turns amber past 80% and red at the cap. */
export function CapMeter({
  spentMinor,
  capMinor,
  sampleCap = false,
}: {
  spentMinor: number;
  capMinor: number;
  /** The cap is a fixture in the live workspace, so its share line carries a Sample tag. */
  sampleCap?: boolean;
}) {
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
      <div className={cn("mt-1.5", sampleCap && "flex flex-wrap items-center gap-1.5")}>
        {`${Math.round(ratio * 100)}% of ${money(capMinor)} cap`}
        {sampleCap ? <SampleTag /> : null}
      </div>
    </div>
  );
}

/**
 * The overview's headline figures. The live workspace adds failed runs and month-to-date spend, and tags its
 * remaining fixture figures Sample; the demo keeps its six tiles and Simulated tags.
 */
export function KpiStrip({ overview, live = false }: { overview: OpsOverview; live?: boolean }) {
  const { kpis: k, simulatedFields: sim } = overview;
  const tag = (name: string) => fieldTag(sim, name, live);
  const failed = failedToday(overview.runsByHour);
  return (
    <div className={cn("grid grid-cols-2 gap-3 md:grid-cols-3", live ? "xl:grid-cols-4" : "xl:grid-cols-6")}>
      <Stat
        label="Active tenants"
        value={count(k.activeTenants)}
        sub={`${count(k.trialTenants)} on trial`}
        href="/tenants?status=active"
        {...tag("kpis.activeTenants")}
      />
      <Stat label="Runs today" value={count(k.runsToday)} href="/runs" {...tag("kpis.runsToday")} />
      {live ? (
        <Stat
          label="Failed today"
          value={count(failed)}
          sub="The link lists all failed runs"
          tone={failed > 0 ? "blocked" : "default"}
          href="/runs?status=FAILED"
          {...tag("runsByHour")}
        />
      ) : null}
      <Stat label="Success, 7d" value={pct(k.runSuccessRate7d)} {...tag("kpis.runSuccessRate7d")} />
      <Stat
        label="Open reviewer tasks"
        value={count(k.openHumanTasks)}
        sub={`${count(k.pendingApprovals)} pending approval${k.pendingApprovals === 1 ? "" : "s"}`}
        tone={k.openHumanTasks > 0 ? "human" : "default"}
        href={live ? "/runs?status=WAITING_FOR_HUMAN" : "/workforce"}
        {...tag("kpis.openHumanTasks")}
      />
      <Stat
        label="Open incidents"
        value={count(k.incidentsOpen)}
        sub={
          tag("kpis.incidentsOpen").sample
            ? "Not tracked in the live workspace yet"
            : k.incidentsOpen === 0
              ? "All services normal"
              : "See platform health"
        }
        tone={k.incidentsOpen > 0 ? "blocked" : "default"}
        href="/health"
        {...tag("kpis.incidentsOpen")}
      />
      <Stat
        label="AI spend"
        value={money(k.aiSpendToday)}
        sub={
          <CapMeter
            spentMinor={k.aiSpendToday.amountMinor}
            capMinor={k.platformDailyCap.amountMinor}
            sampleCap={tag("kpis.platformDailyCap").sample}
          />
        }
        {...tag("kpis.aiSpendToday")}
      />
      {overview.spendMonth ? (
        <Stat
          label="Spend this month"
          value={money(overview.spendMonth)}
          sub="What runs spent across all tenants, UTC month"
          {...tag("spendMonth")}
        />
      ) : null}
    </div>
  );
}
