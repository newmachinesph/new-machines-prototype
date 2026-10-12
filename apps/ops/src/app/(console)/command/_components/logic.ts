import type { HourPoint, OpsAttentionItem } from "@/lib/api/gen/types.gen";

const SEVERITY_RANK: Record<OpsAttentionItem["severity"], number> = { critical: 0, warn: 1, info: 2 };

/** Critical first, then warn, then info; newest first within a severity. Does not mutate the input. */
export function sortAttention(items: readonly OpsAttentionItem[]): OpsAttentionItem[] {
  return [...items].sort(
    (a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || Date.parse(b.at) - Date.parse(a.at),
  );
}

/** Meter turns amber at this share of the daily cap, and red at CAP_FULL. */
export const CAP_WARN = 0.8;
export const CAP_FULL = 1;

export const isSimulated = (fields: readonly string[], name: string) => fields.includes(name);

/** The tallest stacked bar in the series, at least 1 so an empty day does not divide by zero. */
export function maxHourTotal(points: readonly HourPoint[]): number {
  return Math.max(1, ...points.map((p) => p.completed + p.failed + p.waiting));
}
