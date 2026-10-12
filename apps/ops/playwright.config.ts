import { defineConfig, devices } from "@playwright/test";

// The web server serves a mock-auth production build from .next-e2e (see the `e2e` script),
// kept apart from .next so a mock build is never served by mistake.
const webEnv = {
  NEXT_DIST_DIR: ".next-e2e",
  NEXT_PUBLIC_AUTH_MOCK: "1",
  ALLOW_AUTH_MOCK_BUILD: "1",
  NEXT_PUBLIC_API_URL: "http://localhost:8400",
  // next start loads next.config.ts, which validates the env; mock sign-in never calls Firebase.
  NEXT_PUBLIC_FIREBASE_API_KEY: "e2e",
  NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN: "e2e",
  NEXT_PUBLIC_FIREBASE_PROJECT_ID: "e2e",
  NEXT_PUBLIC_FIREBASE_APP_ID: "e2e",
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: "http://localhost:3410", trace: "retain-on-failure" },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: [
    {
      command: "uv run uvicorn app.main:app --port 8400",
      cwd: "../api",
      url: "http://localhost:8400/healthz",
      reuseExistingServer: false,
      env: { AUTH_MODE: "dev", ALLOWED_ORIGINS: "http://localhost:3410" },
    },
    {
      command: "pnpm exec next start --port 3410",
      url: "http://localhost:3410",
      reuseExistingServer: false,
      env: webEnv,
    },
  ],
});
