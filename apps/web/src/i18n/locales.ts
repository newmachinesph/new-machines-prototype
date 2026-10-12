/** Client-safe locale list and helpers. Never import next/headers here. */
export const LOCALES = ["en", "ja"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_COOKIE = "NEXT_LOCALE";

/** Name of each locale in its own language, for the switch. */
export const LOCALE_LABELS: Record<Locale, string> = { en: "English", ja: "日本語" };

/** The Intl tag dates, times and numbers use for each interface locale. */
export const INTL_TAGS = { en: "en-US", ja: "ja-JP" } as const satisfies Record<Locale, string>;

/** An unknown or missing cookie value means English. */
export function resolveLocale(value: string | undefined | null): Locale {
  return LOCALES.find((l) => l === value) ?? DEFAULT_LOCALE;
}

export type MessageTree = { [key: string]: string | MessageTree };

/** Per-key fallback: every key in `base` is present in the result, taking `own` where it has a string there. */
export function mergeMessages<T extends MessageTree>(base: T, own: MessageTree | undefined): T {
  const out: MessageTree = {};
  for (const [key, value] of Object.entries(base)) {
    const mine = own?.[key];
    if (typeof value === "string") out[key] = typeof mine === "string" ? mine : value;
    else out[key] = mergeMessages(value, typeof mine === "object" ? mine : undefined);
  }
  return out as T;
}
