import { expect, test } from "@playwright/test";
import { expectNoSeriousA11yViolations } from "./helpers";

// Mock auth accepts any account, so the create path can be walked without a sign-in service.
test("creating an account from the landing page lands in the workspace overview", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Create an account", exact: true }).click();
  await expect(
    page.getByText("To accept an invitation to another workspace, sign in with Google instead."),
  ).toBeVisible();
  await expectNoSeriousA11yViolations(page);

  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByText("Enter your name.")).toBeVisible();

  await page.getByRole("textbox", { name: "Name" }).fill("Nora Ito");
  await page.getByRole("textbox", { name: "Email" }).fill("nora@example.com");
  await page.getByLabel("Password", { exact: true }).fill("longenough1");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await page.waitForURL(/\/app$/);
});
