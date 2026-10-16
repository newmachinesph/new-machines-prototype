import { cookies } from "next/headers";
import { getRequestConfig } from "next-intl/server";
import { BUSINESS_TZ } from "@/lib/format";
import { LOCALE_COOKIE, mergeMessages, resolveLocale } from "./locales";

export { LOCALES, type Locale } from "./locales";

export default getRequestConfig(async () => {
  const locale = resolveLocale((await cookies()).get(LOCALE_COOKIE)?.value);
  const en = (await import("../../messages/en.json")).default;
  const own = locale === "en" ? en : (await import(`../../messages/${locale}.json`)).default;
  // The business time zone, as the shared formatter (lib/format) shows it with its label.
  return { locale, messages: mergeMessages(en, own), timeZone: BUSINESS_TZ };
});
