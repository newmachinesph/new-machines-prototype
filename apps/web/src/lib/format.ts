import type { Money } from "./types";

/** The prototype's fixed "now", so every relative time on every screen agrees. */
export const NOW = "2026-10-12T16:40:00Z";

export const BUSINESS_TZ = "America/Los_Angeles";
export const WORKER_TZ = "Asia/Manila";

export const usd = (amountMinor: number): Money => ({ amountMinor, currency: "USD" });

/** Locales the interface speaks, as Intl tags. Dates, times and numbers follow the interface language. */
export type IntlLocale = "en-US" | "ja-JP";
const DEFAULT_LOCALE: IntlLocale = "en-US";

// Money is integer minor units; display formatting is not an accounting representation.
export function money(m: Money | number, opts: { sign?: boolean } = {}, locale: IntlLocale = DEFAULT_LOCALE): string {
  const minor = typeof m === "number" ? m : m.amountMinor;
  const s = new Intl.NumberFormat(locale, { style: "currency", currency: "USD" }).format(Math.abs(minor) / 100);
  if (minor < 0) return `−${s}`;
  return opts.sign && minor > 0 ? `+${s}` : s;
}

export const sumMoney = (...ms: Money[]): Money => usd(ms.reduce((t, m) => t + m.amountMinor, 0));

function fmt(iso: string, tz: string, o: Intl.DateTimeFormatOptions, locale: IntlLocale) {
  return new Intl.DateTimeFormat(locale, { timeZone: tz, ...o }).format(new Date(iso));
}

/** The business time zone's short name, in each interface language. */
const BUSINESS_TZ_LABEL: Record<IntlLocale, string> = { "en-US": "PT", "ja-JP": "太平洋時間" };

/** A time in the business zone carries the zone's short name ("9:40 AM PT"), so no time reads as the viewer's
 * own. A caller showing another zone names it in its own words ("Manila time"). */
const zoned = (text: string, tz: string, locale: IntlLocale) =>
  tz === BUSINESS_TZ ? `${text} ${BUSINESS_TZ_LABEL[locale]}` : text;

export const time = (iso: string, tz = BUSINESS_TZ, locale: IntlLocale = DEFAULT_LOCALE) =>
  zoned(fmt(iso, tz, { hour: "numeric", minute: "2-digit" }, locale), tz, locale);
/** With seconds and no zone name: for a list of times under one heading that names the zone (a run's timeline). */
export const timeSec = (iso: string, tz = BUSINESS_TZ, locale: IntlLocale = DEFAULT_LOCALE) =>
  fmt(iso, tz, { hour: "numeric", minute: "2-digit", second: "2-digit" }, locale);
export const date = (iso: string, tz = BUSINESS_TZ, locale: IntlLocale = DEFAULT_LOCALE) =>
  fmt(iso, tz, { month: "short", day: "numeric" }, locale);
export const dateTime = (iso: string, tz = BUSINESS_TZ, locale: IntlLocale = DEFAULT_LOCALE) =>
  zoned(fmt(iso, tz, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }, locale), tz, locale);

/** The calendar day (YYYY-MM-DD) `iso` falls on in the business zone. */
export const businessDay = (iso: string) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: BUSINESS_TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(iso),
  );
export const utc = (iso: string) =>
  `${fmt(iso, "UTC", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }, DEFAULT_LOCALE)} UTC`;

/** Looks up a `common.time` message. Callers pass next-intl's `t`, or ENGLISH_TIME for plain English. */
export type TimeKey =
  "justNow" | "minAgo" | "hAgo" | "yesterday" | "daysAgo" | "overdue" | "minLeft" | "hLeft" | "hMinLeft";
export type TimeTranslator = (key: TimeKey, values?: Record<string, number>) => string;

const ENGLISH_TIME: Record<TimeKey, (v: Record<string, number>) => string> = {
  justNow: () => "just now",
  minAgo: (v) => `${v.n} min ago`,
  hAgo: (v) => `${v.n} h ago`,
  yesterday: () => "yesterday",
  daysAgo: (v) => `${v.n} days ago`,
  overdue: () => "overdue",
  minLeft: (v) => `${v.n} min left`,
  hLeft: (v) => `${v.n} h left`,
  hMinLeft: (v) => `${v.h} h ${v.m} min left`,
};
const english: TimeTranslator = (key, values = {}) => ENGLISH_TIME[key](values);

export function agoParts(iso: string, tr: TimeTranslator, now = NOW): string {
  const mins = Math.round((Date.parse(now) - Date.parse(iso)) / 60000);
  if (mins < 1) return tr("justNow");
  if (mins < 60) return tr("minAgo", { n: mins });
  const h = Math.round(mins / 60);
  if (h < 24) return tr("hAgo", { n: h });
  const d = Math.round(h / 24);
  return d === 1 ? tr("yesterday") : tr("daysAgo", { n: d });
}

export function untilParts(iso: string, tr: TimeTranslator, now = NOW): string {
  const mins = Math.round((Date.parse(iso) - Date.parse(now)) / 60000);
  if (mins <= 0) return tr("overdue");
  if (mins < 60) return tr("minLeft", { n: mins });
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? tr("hMinLeft", { h, m }) : tr("hLeft", { n: h });
}

/** English only, for server components and the landing page. Client components use useFormat(). */
export const ago = (iso: string, now = NOW) => agoParts(iso, english, now);
export const until = (iso: string, now = NOW) => untilParts(iso, english, now);

export function duration(s: number): string {
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  if (m < 60) return r ? `${m}m ${r}s` : `${m}m`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}
