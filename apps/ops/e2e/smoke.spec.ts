import { expect, test } from "@playwright/test";

// Every console route, signed in with the mock session, at desktop and phone width: the page renders its
// heading, the page does not scroll sideways, and the console stays free of errors. Page tasks extend
// the ready check with their own data.
const MOCK_SESSION_KEY = "nm-ops-mock-session";
const ROUTES = [
  ["/command", "Command center"],
  ["/tenants", "Tenants"],
  ["/runs", "Runs"],
  ["/billing", "Billing"],
  ["/marketplace", "Marketplace"],
  ["/connectors", "Connectors"],
  ["/workforce", "Workforce"],
  ["/team", "Ops team"],
  ["/guardrails", "Guardrails"],
  ["/health", "System health"],
  ["/audit", "Audit log"],
] as const;

test.beforeEach(async ({ context }) => {
  await context.addInitScript((key) => {
    try {
      sessionStorage.setItem(key, "1");
    } catch {
      /* storage unavailable on about:blank */
    }
  }, MOCK_SESSION_KEY);
});

for (const width of [390, 1440]) {
  for (const [path, title] of ROUTES) {
    test(`${path} renders cleanly at ${width}px`, async ({ page }) => {
      const errors: string[] = [];
      page.on("console", (m) => {
        if (m.type() === "error") errors.push(m.text());
      });
      page.on("pageerror", (e) => errors.push(String(e)));
      await page.setViewportSize({ width, height: 900 });

      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
      // The operator from GET /v1/ops/me: the role always, the email from md up.
      await expect(page.getByRole("banner").getByText("Owner", { exact: true })).toBeVisible();
      if (width >= 768) await expect(page.getByRole("banner").getByText("ops@newmachin.es")).toBeVisible();

      const { scrollWidth, innerWidth } = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
      }));
      expect(scrollWidth).toBeLessThanOrEqual(innerWidth);
      expect(errors).toEqual([]);
    });
  }
}

// One real write against the API the suite starts: approving a pack moves it out of the review queue and
// leaves an audit entry carrying the operator's reason.
test("approving an in-review pack publishes it and records it in the audit log", async ({ page }) => {
  const name = "Customs Paperwork Prep";
  const reason = "e2e: passport reviewed, connector access matches the outcome";

  await page.goto("/marketplace?tab=in_review");
  await page.getByRole("link", { name: new RegExp(name) }).click();
  await expect(page).toHaveURL(/\/marketplace\/customs-paperwork-prep$/);

  await page.getByRole("button", { name: "Approve and publish" }).click();
  const dialog = page.getByRole("alertdialog");
  await dialog.getByLabel("Reason").fill(reason);
  await dialog.getByRole("button", { name: "Approve and publish" }).click();
  await expect(page.getByText(`${name} published`)).toBeVisible();
  await expect(dialog).toBeHidden();

  await page.goto("/marketplace?tab=in_review");
  await expect(page.getByRole("heading", { level: 1, name: "Marketplace" })).toBeVisible();
  await expect(page.getByText("Subscription Win-back")).toBeVisible();
  await expect(page.getByText(name)).toHaveCount(0);

  await page.goto(`/audit?q=${encodeURIComponent("e2e: passport reviewed")}`);
  const row = page.getByRole("row").filter({ hasText: reason });
  await expect(row).toHaveCount(1);
  await expect(row.getByText("pack.approve")).toBeVisible();
  await expect(row.getByText("customs-paperwork-prep")).toBeVisible();
});

test("signs in through the sign-in page and lands on the command center", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "New Machines operator console" })).toBeVisible();
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/command$/);
  await expect(page.getByRole("heading", { level: 1, name: "Command center" })).toBeVisible();
  await context.close();
});
