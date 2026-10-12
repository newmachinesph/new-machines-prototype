import { test } from "@playwright/test";
import { expectNoSeriousA11yViolations, presignIn, setLocale, waitForPageReady } from "./helpers";
import { ROUTES } from "./routes";

// Read-only: the demo-path spec has its own axe checks for the states it creates.
const PAGES = ["/", "/app", "/app/runs/run_1042", "/work/tasks/ht_011"].map((path) =>
  ROUTES.find((r) => r.path === path)!,
);

for (const locale of ["en", "ja"] as const) {
  for (const { path, ready } of PAGES) {
    test(`no serious accessibility violations on ${path} (${locale})`, async ({ context, page }) => {
      await setLocale(context, locale);
      if (path !== "/") await presignIn(context);
      await page.goto(path);
      await waitForPageReady(page, ready(page));
      await expectNoSeriousA11yViolations(page);
    });
  }
}
