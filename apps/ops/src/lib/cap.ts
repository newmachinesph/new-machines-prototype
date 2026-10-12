/** Share of a cap used, never below 0 and not capped above, so overspend shows (1.5 = 150%). A zero cap reads as
 * full. Meters clamp their own bar with `meterFill`. */
export function capRatio(spentMinor: number, capMinor: number): number {
  if (capMinor <= 0) return 1;
  return Math.max(0, spentMinor / capMinor);
}

/** The ratio a meter bar can draw: 0..1. */
export const meterFill = (ratio: number) => Math.min(1, ratio);
