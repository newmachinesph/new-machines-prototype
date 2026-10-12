import { defineConfig, devices } from "@playwright/test";

// The web server serves a mock-auth production build from .next-e2e (see the `e2e` script),
// kept apart from .next so a mock build is never served by mistake.
const webEnv = {
  NEXT_DIST_DIR: ".next-e2e",
  NEXT_PUBLIC_AUTH_MOCK: "1",
  ALLOW_AUTH_MOCK_BUILD: "1",
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:3100", trace: "retain-on-failure" },
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
      testMatch: "demo-path.spec.ts",
      dependencies: ["readonly"],
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: [
    {
      command: "uv run uvicorn app.main:app --port 8100",
      cwd: "../api",
      url: "http://localhost:8100/healthz",
      reuseExistingServer: false,
    },
    {
      command: "pnpm exec next start --port 3100",
      url: "http://localhost:3100",
      reuseExistingServer: false,
      env: webEnv,
    },
  ],
});
