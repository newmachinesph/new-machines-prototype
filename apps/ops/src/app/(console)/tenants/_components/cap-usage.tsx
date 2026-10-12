import { capRatio as ratioOf, meterFill } from "@/lib/cap";
import { cn } from "@/lib/cn";
import { money, pct } from "@/lib/format";
import type { Money } from "@/lib/types";

export type CapLevel = "ok" | "warn" | "blocked";

/** Below 80% of the cap is fine, 80% to under 90% is a warning, 90% and over is blocked territory. */
export function capLevel(ratio: number): CapLevel {
  if (ratio >= 0.9) return "blocked";
  if (ratio >= 0.8) return "warn";
  return "ok";
}

const FILL: Record<CapLevel, string> = { ok: "bg-ink", warn: "bg-human", blocked: "bg-blocked" };
const TEXT: Record<CapLevel, string> = { ok: "text-ink", warn: "text-human", blocked: "text-blocked" };

export function CapUsage({
  spent,
  cap,
  showAmounts,
  className,
}: {
  spent: Money;
  cap: Money;
  showAmounts?: boolean;
  className?: string;
}) {
  const ratio = ratioOf(spent.amountMinor, cap.amountMinor);
  const level = capLevel(ratio);
  const width = `${Math.round(meterFill(ratio) * 100)}%`;
  return (
    <div className={cn("min-w-32", className)}>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className={cn("tnum font-medium", TEXT[level])}>{pct(ratio, 0)}</span>
        {showAmounts ? (
          <span className="tnum text-muted">
            {money(spent)} of {money(cap)}
          </span>
        ) : null}
      </div>
      <div
        role="meter"
        aria-label="Monthly cap used"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(meterFill(ratio) * 100)}
        aria-valuetext={`${pct(ratio, 0)} of the monthly cap`}
        className="mt-1 h-1.5 overflow-hidden rounded-full bg-grey-100"
      >
        <div className={cn("h-full rounded-full", FILL[level])} style={{ width }} />
      </div>
    </div>
  );
}
