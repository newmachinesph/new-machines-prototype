import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";
import "./globals.css";
import { UiProviders } from "@/components/base";
import { Providers } from "@/components/providers";
import { fontClassNames } from "@/design-system/fonts";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("common.meta");
  return {
    title: { default: "New Machines", template: "%s | New Machines" },
    description: t("description"),
    robots: { index: false, follow: false, nocache: true },
  };
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();
  const t = await getTranslations("common");
  return (
    <html lang={locale} className={fontClassNames}>
      <body className="relative min-h-dvh font-sans text-ink antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:bg-paper focus:px-3 focus:py-2"
        >
          {t("skipToContent")}
        </a>
        <NextIntlClientProvider locale={locale} messages={messages}>
          <UiProviders>
            <Providers>
              {/* Base UI portals render above this isolated root. */}
              <div className="isolate">{children}</div>
            </Providers>
          </UiProviders>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
