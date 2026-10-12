"use client";

import { useLocale, useTranslations } from "next-intl";
import { INTL_TAGS, resolveLocale } from "@/i18n/locales";
import * as f from "./format";

/** Formatters bound to the interface language. Use this in client components instead of importing from ./format. */
export function useFormat() {
  const locale = INTL_TAGS[resolveLocale(useLocale())];
  const t = useTranslations("common.time");
  return {
    money: (m: Parameters<typeof f.money>[0], o?: { sign?: boolean }) => f.money(m, o, locale),
    date: (iso: string, tz?: string) => f.date(iso, tz, locale),
    dateTime: (iso: string, tz?: string) => f.dateTime(iso, tz, locale),
    time: (iso: string, tz?: string) => f.time(iso, tz, locale),
    timeSec: (iso: string, tz?: string) => f.timeSec(iso, tz, locale),
    list: (items: string[]) => new Intl.ListFormat(locale, { type: "conjunction" }).format(items),
    ago: (iso: string) => f.agoParts(iso, (key, values) => t(key, values)),
    until: (iso: string) => f.untilParts(iso, (key, values) => t(key, values)),
  };
}
