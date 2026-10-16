import { expect, test } from "@playwright/test";
import { mainText, observe, OPS_URL, settle, shot, watch } from "./support/qa";

// Journey 5: the operator (dev mode is an owner operator) reviews the listings queue: approves one
// submission, requests changes on another, and checks the overview's publisher stats are tagged Simulated.
test.describe.configure({ mode: "serial" });

const OPS_MOCK_KEY = "nm-ops-mock-session";

async function opsPage(browser: import("@playwright/test").Browser, width = 1440) {
  const context = await browser.newContext({ baseURL: OPS_URL, viewport: { width, height: 900 } });
  await context.addInitScript((key) => {
    try {
      sessionStorage.setItem(key, "1");
    } catch {
      /* about:blank */
    }
  }, OPS_MOCK_KEY);
  return { context, page: await context.newPage() };
}

async function act(page: import("@playwright/test").Page, label: "Approve" | "Request changes", reason: string) {
  await page.getByRole("button", { name: label }).first().click();
  const dialog = page.locator("[role=dialog], [role=alertdialog]").last();
  await expect(dialog).toBeVisible();
  const box = dialog.locator("textarea, input[type=text]").first();
  if (await box.isVisible().catch(() => false)) await box.fill(reason);
  await dialog.getByRole("button", { name: label }).click();
  await expect(dialog).toBeHidden();
}

test("listings queue: approve one, request changes on another", async ({ browser }) => {
  test.fail(true, "F-06: submitted prices show as No fee in the review queue");
  const { context, page } = await opsPage(browser);
  const w = watch(page);
  await page.goto("/listings");
  await settle(page);
  await page.waitForTimeout(800);
  await shot(page, "j5-ops-listings");
  const queue = await mainText(page);
  observe({ journey: 5, queue: queue.slice(0, 4000) });
  // Names come from journey 4 (QA_STAMP runs): approve one listing, request changes on another.
  const approveName = process.env.QA_APPROVE ?? "QA Inbox Reader A2";
  const changesName = process.env.QA_CHANGES ?? "QA Inbox Reader A1";
  for (const [name, label, reason] of [
    [approveName, "Approve", "Checks passed and the definition matches its description."],
    [changesName, "Request changes", "Please describe which emails count as needing an answer."],
  ] as const) {
    if (!name) continue;
    await page.goto("/listings");
    await settle(page);
    await page.getByRole("button", { name: "All", exact: true }).click();
    await page.waitForTimeout(600);
    await page.getByRole("link", { name: new RegExp(name) }).first().click();
    await page.waitForURL(/\/listings\/lst_/);
    await settle(page);
    const slug = label === "Approve" ? "approve" : "changes";
    await shot(page, `j5-ops-listing-${slug}-before`);
    observe({ journey: 5, listing: name, text: (await mainText(page)).slice(0, 4000) });
    // F-06: the queue and detail say "No fee" for a version submitted with a price.
    expect.soft(await mainText(page), `${name}: submitted price shown`).not.toMatch(/No fee/);
    await act(page, label, reason);
    await page.waitForTimeout(800);
    await shot(page, `j5-ops-listing-${slug}-after`);
    expect.soft(await mainText(page)).toMatch(label === "Approve" ? /Listed|Approved/ : /Changes requested/i);
  }
  observe({ journey: 5, ...w });
  expect.soft(w.failed).toEqual([]);
  expect.soft(w.consoleErrors).toEqual([]);
  await context.close();
});

test("overview publisher stats carry the Simulated tag", async ({ browser }) => {
  const { context, page } = await opsPage(browser);
  const w = watch(page);
  await page.goto("/command");
  await settle(page);
  await page.waitForTimeout(1000);
  await shot(page, "j5-ops-overview");
  const text = await mainText(page);
  observe({ journey: 5, overview: text.slice(0, 5000), ...w });
  const stats = page.getByText(/Publisher earnings|publisher/i).first();
  await expect.soft(stats, "publisher stats on the overview").toBeVisible();
  const section = page.locator("section, div").filter({ has: page.getByText(/Publisher earnings/i) }).last();
  await expect.soft(section.getByText("Simulated").first(), "Simulated tag next to publisher earnings").toBeVisible();
  expect.soft(w.failed).toEqual([]);
  await context.close();
});

test("ops pages fit at 390 wide", async ({ browser }) => {
  const { context, page } = await opsPage(browser, 390);
  const problems: string[] = [];
  for (const path of ["/command", "/listings", "/tenants", "/runs"]) {
    await page.goto(path);
    await settle(page);
    const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    await shot(page, `j5-ops${path.replaceAll("/", "_")}-390`);
    if (over > 0) problems.push(`${path} overflows by ${over}px`);
  }
  observe({ journey: 5, mobile: problems });
  expect.soft(problems).toEqual([]);
  await context.close();
});
