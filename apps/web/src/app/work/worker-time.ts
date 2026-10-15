"use client";

import { useLocale } from "next-intl";
import { INTL_TAGS, resolveLocale } from "@/i18n/locales";
import { WORKER_TZ } from "@/lib/format";
import { useFormat } from "@/lib/use-format";
import { zoneName } from "@/lib/use-viewer-time-zone";

/** Date and time in the reviewer portal's zone, with the zone named ("Oct 11, 10:00 PM GMT+8"). */
export function useWorkerDateTime() {
  const { dateTime } = useFormat();
  const locale = INTL_TAGS[resolveLocale(useLocale())];
  return (iso: string) => `${dateTime(iso, WORKER_TZ)} ${zoneName(WORKER_TZ, locale, new Date(iso))}`;
}
