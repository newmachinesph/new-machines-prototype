import { defineConfig, devices } from "@playwright/test";

// The web server serves a mock-auth production build from .next-e2e (see the `e2e` script),
// kept apart from .next so a mock build is never served by mistake.
const webEnv = {
  NEXT_DIST_DIR: ".next-e2e",
  NEXT_PUBLIC_AUTH_MOCK: "1",
  ALLOW_AUTH_MOCK_BUILD: "1",
};

// Ports can be moved aside when another session holds the defaults. The web build bakes in
// NEXT_PUBLIC_API_URL, so build with the same E2E_API_PORT (e.g. NEXT_PUBLIC_API_URL=http://localhost:8150).
const WEB_PORT = process.env.E2E_PORT ?? "3100";
const API_PORT = process.env.E2E_API_PORT ?? "8100";
const WEB_URL = `http://localhost:${WEB_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: WEB_URL, trace: "retain-on-failure" },
  // The API keeps its state in memory, and the demo path changes it (starts a run, approves, claims and
  // submits a task). The read-only specs therefore run first, against untouched fixtures, and the demo
  // project depends on them so the order is explicit rather than an accident of file names.
  projects: [
    {
      name: "readonly",
      testMatch: ["a11y.spec.ts", "overflow.spec.ts"],
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      name: "demo",
      testMatch: ["demo-path.spec.ts", "create-account.spec.ts"],
      dependencies: ["readonly"],
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      // Answers its API calls from an in-memory fake in the spec, so it can run in any order.
      name: "publishing",
      testMatch: "publishing.spec.ts",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      // Only reads, and replays tours by hand: the build turns the first-visit tours off.
      name: "tour",
      testMatch: "tour.spec.ts",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: [
    {
      command: `uv run uvicorn app.main:app --port ${API_PORT}`,
      cwd: "../api",
      url: `http://localhost:${API_PORT}/healthz`,
      reuseExistingServer: false,
      env: { ALLOWED_ORIGINS: WEB_URL },
    },
    {
      command: `pnpm exec next start --port ${WEB_PORT}`,
      url: WEB_URL,
      reuseExistingServer: false,
      env: webEnv,
    },
  ],
});
