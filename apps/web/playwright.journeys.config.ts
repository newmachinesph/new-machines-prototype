import { defineConfig, devices } from "@playwright/test";

// Realistic journeys against an already-running local stack (see e2e/journeys/README section in the QA
// findings): the API with the real Temporal runtime in the live workspace, launched through
// e2e/journeys/support/qa_api.py so specs can act as several users, a mock-auth web build and a mock-auth
// ops build. Nothing is started or stopped here: every server is reused through its port.
const WEB_PORT = process.env.QA_WEB_PORT ?? "3600";
const OPS_PORT = process.env.QA_OPS_PORT ?? "3610";
const API_PORT = process.env.QA_API_PORT ?? "8600";

process.env.QA_WEB_URL ??= `http://localhost:${WEB_PORT}`;
process.env.QA_OPS_URL ??= `http://localhost:${OPS_PORT}`;
process.env.QA_API_URL ??= `http://127.0.0.1:${API_PORT}`;

export default defineConfig({
  testDir: "./e2e/journeys",
  testMatch: "*.journey.ts",
  outputDir: "./test-results/qa/artifacts",
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  expect: { timeout: 15_000 },
  reporter: [["list"], ["json", { outputFile: "test-results/qa/results.json" }]],
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.QA_WEB_URL,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
