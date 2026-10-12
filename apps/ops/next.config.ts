import "./src/lib/env";
import type { NextConfig } from "next";
import { PHASE_PRODUCTION_BUILD } from "next/constants";

const nextConfig: NextConfig = {
  // The e2e run builds the mock-auth app into its own directory so it can never be served from .next.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  devIndicators: false,
  // The build type-checks app code only; `pnpm typecheck` still checks everything, tests included.
  typescript: { tsconfigPath: "tsconfig.build.json" },
  // The operator console is staff-only; keep it out of search engines.
  async headers() {
    return [{ source: "/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] }];
  },
};

// Runs server-side only (build, dev, start), keyed on the build phase rather than NODE_ENV, which a
// caller can override. The Playwright production build sets ALLOW_AUTH_MOCK_BUILD=1 to opt in; a real deploy must not.
export default function config(phase: string): NextConfig {
  if (
    phase === PHASE_PRODUCTION_BUILD &&
    process.env.NEXT_PUBLIC_AUTH_MOCK === "1" &&
    process.env.ALLOW_AUTH_MOCK_BUILD !== "1"
  ) {
    throw new Error(
      "NEXT_PUBLIC_AUTH_MOCK=1 would ship a sign-in bypass in a production build. Unset it, or set ALLOW_AUTH_MOCK_BUILD=1 for a test build.",
    );
  }
  return nextConfig;
}
