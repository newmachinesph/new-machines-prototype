import type { Metadata } from "next";
import "./globals.css";
import { UiProviders } from "@/components/base";
import { Providers } from "@/components/providers";
import { fontClassNames } from "@/design-system/fonts";

export const metadata: Metadata = {
  title: { default: "Operator console | New Machines", template: "%s | New Machines operator console" },
  description: "Staff-only console for running New Machines: tenants, catalog, workforce, guardrails and health.",
  robots: { index: false, follow: false, nocache: true },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={fontClassNames}>
      <body className="relative min-h-dvh font-sans text-ink antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:bg-paper focus:px-3 focus:py-2"
        >
          Skip to content
        </a>
        <UiProviders>
          <Providers>
            {/* Base UI portals render above this isolated root. */}
            <div className="isolate">{children}</div>
          </Providers>
        </UiProviders>
      </body>
    </html>
  );
}
