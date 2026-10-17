import { expect, test } from "@playwright/test";
import { expectNoSeriousA11yViolations, signInThroughLanding, waitForPageReady } from "./helpers";

test("the demo path works end to end", async ({ page }) => {
  await signInThroughLanding(page);
  await expect(page).toHaveURL(/\/app$/);

  await page.getByRole("button", { name: "Start a run" }).click();
  await page.getByRole("menuitem", { name: "Order & Payment Reconciliation" }).click();
  await expect(page.getByRole("heading", { name: "Start a run" })).toBeVisible();
  await page.getByRole("button", { name: "Start run" }).click();
  await expect(page).toHaveURL(/\/app\/runs\/run_\d+$/);
  await expect(page.getByText("Started the run")).toBeVisible();

  await page.goto("/app/approvals");
  await waitForPageReady(page, page.getByText("Send a payment reminder to Cedarline Home").first());
  await page.getByRole("button", { name: "Approve and send" }).first().click();
  await expect(page.getByText("Approved and queued to send")).toBeVisible();
  await expectNoSeriousA11yViolations(page);
  await page.reload();
  await expect(page.getByRole("button", { name: "Approve and send" })).toHaveCount(0);

  await page.goto("/work/tasks/ht_011");
  await page.getByRole("button", { name: "Claim this task" }).click();
  await expect(page.getByRole("timer", { name: /left on your hold/ })).toBeVisible();
  await expectNoSeriousA11yViolations(page);
  for (const order of ["HP-21044", "HP-21051", "HP-21063"]) {
    await page
      .getByRole("radiogroup", { name: `Your call on ${order}` })
      .getByRole("radio", { name: "Same payment" })
      .check();
  }
  await page.getByRole("textbox", { name: "Feedback for the agent" }).fill("All three records are the same payment.");
  await page.getByRole("button", { name: "Submit review" }).click();
  await expect(page.getByText("Simulated check")).toBeVisible();
  await expect(page.getByText(/Accepted\. .* is owed to you\./)).toBeVisible();
  await expectNoSeriousA11yViolations(page);

  await page
    .getByRole("button", { name: /account menu/ })
    .first()
    .click();
  await page.getByRole("menuitemradio", { name: "日本語" }).click();
  await page.goto("/app/runs/run_1042");
  await expect(page.locator("html")).toHaveAttribute("lang", "ja");
  // The interface is Japanese while the run's data stays English.
  await expect(
    page.getByRole("navigation", { name: "メイン" }).first().getByRole("link", { name: /^承認/ }),
  ).toBeVisible();
  await expect(page.getByText("Reconcile Oct 1–10 orders").first()).toBeVisible();
});
