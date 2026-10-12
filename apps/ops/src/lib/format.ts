import type { Money } from "./types";

/** The prototype's fixed "now", shared with the API fixtures, so every relative time on every screen agrees. */
export const NOW = "2026-10-12T16:40:00Z";

/** Operators read times in UTC unless a page says otherwise. */
export const OPS_TZ = "UTC";

const LOCALE = "en-US";

export const usd = (amountMinor: number): Money => ({ amountMinor, currency: "USD" });

// Money is integer minor units; display formatting is not an accounting representation.
export function money(m: Money | number, opts: { sign?: boolean } = {}): string {
  const minor = typeof m === "number" ? m : m.amountMinor;
  const s = new Intl.NumberFormat(LOCALE, { style: "currency", currency: "USD" }).format(Math.abs(minor) / 100);
  if (minor < 0) return `−${s}`;
  return opts.sign && minor > 0 ? `+${s}` : s;
}

/** A count with thousands separators: 12,480. */
export const count = (n: number) => new Intl.NumberFormat(LOCALE).format(n);

/** A 0..1 ratio as a percentage: 0.9734 → "97.3%". */
export const pct = (ratio: number, digits = 1) =>
  new Intl.NumberFormat(LOCALE, { style: "percent", maximumFractionDigits: digits }).format(ratio);

function fmt(iso: string, tz: string, o: Intl.DateTimeFormatOptions) {
  return new Intl.DateTimeFormat(LOCALE, { timeZone: tz, ...o }).format(new Date(iso));
}

export const time = (iso: string, tz = OPS_TZ) => fmt(iso, tz, { hour: "numeric", minute: "2-digit" });
export const date = (iso: string, tz = OPS_TZ) => fmt(iso, tz, { month: "short", day: "numeric" });
export const dateTime = (iso: string, tz = OPS_TZ) =>
  fmt(iso, tz, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

/** "5 min ago", "3 h ago", "yesterday", "4 days ago", relative to the shared NOW. */
export function ago(iso: string, now = NOW): string {
  const mins = Math.round((Date.parse(now) - Date.parse(iso)) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export function duration(s: number): string {
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m < 60) return r ? `${m}m ${r}s` : `${m}m`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
