import type { IntlLocale } from "./format";

/** A zone's short name for the viewer, such as "PDT" or "GMT+8"; the zone's own id if there is none. Times in
 * the business zone carry its label from the shared formatter (see format.ts). */
export function zoneName(zone: string, locale: IntlLocale, at = new Date()): string {
  const parts = new Intl.DateTimeFormat(locale, { timeZone: zone, timeZoneName: "short" }).formatToParts(at);
  return parts.find((p) => p.type === "timeZoneName")?.value ?? zone;
}
