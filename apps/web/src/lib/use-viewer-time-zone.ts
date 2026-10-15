"use client";

import { useSyncExternalStore } from "react";
import { BUSINESS_TZ, type IntlLocale } from "./format";

const never = () => () => {};
const browserZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;
const serverZone = () => undefined;

/**
 * The time zone the viewer's device is set to, once the page runs in the browser. The server (and the first
 * client render, which must match it) has no viewer, so it falls back to the business zone with `known` false.
 */
export function useViewerTimeZone(): { zone: string; known: boolean } {
  const zone = useSyncExternalStore(never, browserZone, serverZone);
  return zone ? { zone, known: true } : { zone: BUSINESS_TZ, known: false };
}

/** A zone's short name for the viewer, such as "PDT" or "GMT+8"; the zone's own id if there is none. */
export function zoneName(zone: string, locale: IntlLocale, at = new Date()): string {
  const parts = new Intl.DateTimeFormat(locale, { timeZone: zone, timeZoneName: "short" }).formatToParts(at);
  return parts.find((p) => p.type === "timeZoneName")?.value ?? zone;
}
