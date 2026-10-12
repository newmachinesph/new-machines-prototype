import { render, type RenderOptions } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement, ReactNode } from "react";
import { mergeMessages, type Locale } from "@/i18n/locales";
import en from "../../messages/en.json";
import ja from "../../messages/ja.json";

const OWN = { en, ja } as const;

/** Wraps children in the same provider the root layout uses. English by default; pass locale="ja" to test Japanese. */
export function IntlWrapper({ children, locale = "en" }: { children: ReactNode; locale?: Locale }) {
  return (
    <NextIntlClientProvider locale={locale} messages={mergeMessages(en, OWN[locale])} timeZone="America/Los_Angeles">
      {children}
    </NextIntlClientProvider>
  );
}

/** render() inside the intl provider. Use instead of render() for any component that calls useTranslations. */
export function renderWithIntl(
  ui: ReactElement,
  { locale, ...options }: Omit<RenderOptions, "wrapper"> & { locale?: Locale } = {},
) {
  return render(ui, { wrapper: ({ children }) => <IntlWrapper locale={locale}>{children}</IntlWrapper>, ...options });
}
