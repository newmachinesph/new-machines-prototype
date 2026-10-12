import "./src/lib/env";
import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

// Server-side only (build and start), so the browser bundle never evaluates it.
// Task 14's Playwright production build sets ALLOW_AUTH_MOCK_BUILD=1 to opt in; a real deploy must not.
if (
  process.env.NODE_ENV === "production" &&
  process.env.NEXT_PUBLIC_AUTH_MOCK === "1" &&
  process.env.ALLOW_AUTH_MOCK_BUILD !== "1"
) {
  throw new Error(
    "NEXT_PUBLIC_AUTH_MOCK=1 would ship a sign-in bypass in a production build. Unset it, or set ALLOW_AUTH_MOCK_BUILD=1 for a test build.",
  );
}

const nextConfig: NextConfig = {
  // The e2e run builds the mock-auth app into its own directory so it can never be served from .next.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  devIndicators: false,
  // The build type-checks app code only: some tests import the API's fixtures from apps/api, which
  // deploys never upload. `pnpm typecheck` still checks everything, tests included.
  typescript: { tsconfigPath: "tsconfig.build.json" },
  // The demo is reviewed from a private URL; keep it out of search engines.
  async headers() {
    return [{ source: "/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] }];
  },
};

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

export default withNextIntl(nextConfig);
