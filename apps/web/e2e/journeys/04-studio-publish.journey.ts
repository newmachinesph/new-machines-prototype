import { expect, test } from "@playwright/test";
import { reviewTask, waitForRun } from "./support/flows";
import { apiAs, contextAs, mainText, observe, settle, shot, watch } from "./support/qa";

// Journey 4: alice builds an agent and a pack from scratch in the Studio, saves both, runs a sandbox test,
// turns on publishing in Settings and submits both for review, then watches the checks reach "In review".
test.describe.configure({ mode: "serial" });

const STAMP = process.env.QA_STAMP ?? new Date().toISOString().slice(5, 16).replace(/[-T:]/g, "");
const AGENT = `QA Inbox Reader ${STAMP}`;
const PACK = `QA Inbox Digest ${STAMP}`;

test("build and save an agent from scratch", async ({ browser }) => {
  const context = await contextAs(browser, "alice");
  const page = await context.newPage();
  const w = watch(page);
  await page.goto("/studio/agents/new");
  await settle(page);
  await page.getByLabel("Name", { exact: true }).fill(AGENT);
  await page.getByLabel("Summary").fill("Reads recent inbox emails and lists the ones that need an answer.");
  await page.getByLabel("Instructions").fill("List the last week's inbox emails. For each, say who sent it and whether it needs a reply.");
  await page.getByRole("checkbox", { name: /Gmail: List threads/ }).click();
  await page.getByRole("button", { name: "Add a skill" }).click();
  await page.getByLabel("Skill 1 title").fill("Spot a question");
  await page.getByLabel("Skill 1 text").fill("An email needs a reply when it asks a question or requests something.");
  await page.getByRole("button", { name: "Save agent" }).click();
  await expect(page.getByText(/Agent saved|Version 1 is saved/).first()).toBeVisible();
  await page.waitForURL(/\/studio\/agents\/(?!new)/);
  await shot(page, "j4-agent-saved");
  observe({ journey: 4, agentUrl: page.url(), ...w });
  expect.soft(w.failed).toEqual([]);
  await context.close();
});

test("build a pack that uses the agent, save it and run a sandbox test", async ({ browser }) => {
  const context = await contextAs(browser, "alice");
  const page = await context.newPage();
  const w = watch(page);
  await page.goto("/studio/packs/new");
  await settle(page);
  // Put the new agent after the start step.
  await page.getByRole("button", { name: "Add a step after step 1" }).click();
  await page.waitForTimeout(500);
  await shot(page, "j4-pack-add-step");
  observe({ journey: 4, addStepMenu: (await mainText(page)).slice(0, 3000) });
  await page.getByRole("menuitem", { name: "Agent", exact: true }).click();
  await page.waitForTimeout(700);
  await shot(page, "j4-pack-agent-step");
  observe({ journey: 4, agentStep: (await mainText(page)).slice(0, 3000) });
  const agentPicker = page.getByRole("combobox", { name: /Agent/ }).first();
  await agentPicker.click();
  await page.getByRole("option", { name: new RegExp(AGENT) }).first().click();
  await page.waitForTimeout(500);
  const task = page.getByLabel(/Task for the agent/);
  if (await task.isVisible().catch(() => false)) await task.fill("List the inbox emails that need an answer.");
  await page.getByRole("button", { name: "Pack details" }).click().catch(() => undefined);
  await page.getByLabel("Name", { exact: true }).fill(PACK);
  await page.getByLabel("Outcome").fill("A short list of inbox emails that need an answer, checked by a person.");
  await page.getByLabel("Description").fill("Reads the inbox with the QA agent and asks a person to review the list.");
  await page.getByLabel("Most a run may spend on agents (USD)").fill("2");
  await page.getByLabel("Most a run may pay reviewers (USD)").fill("0").catch(() => undefined);
  await page.getByLabel("Name of field 1").fill("query");
  await page.getByLabel("Label of field 1").fill("Gmail search");
  await page.getByRole("button", { name: "Check for problems" }).click();
  await page.waitForTimeout(800);
  await shot(page, "j4-pack-checked");
  await page.getByRole("button", { name: "Save pack" }).click();
  await expect(page.getByText(/saved/i).first()).toBeVisible();
  await page.waitForURL(/\/studio\/packs\/(?!new)/, { timeout: 15_000 });
  await shot(page, "j4-pack-saved");
  observe({ journey: 4, packUrl: page.url(), afterSave: (await mainText(page)).slice(0, 2500) });

  await page.getByRole("button", { name: "Test in sandbox" }).click();
  const dialog = page.locator("[role=dialog], [role=alertdialog]").filter({ hasText: "Test in sandbox" }).last();
  await expect(dialog.getByRole("button", { name: "Start the test run" })).toBeVisible();
  const query = dialog.getByLabel(/Gmail search/);
  if (await query.isVisible().catch(() => false)) await query.fill("in:inbox newer_than:7d");
  await shot(page, "j4-pack-test-dialog");
  await dialog.getByRole("button", { name: "Start the test run" }).click();
  await page.waitForURL(/\/app\/runs\/run_/, { timeout: 20_000 }).catch(() => undefined);
  await page.waitForTimeout(3000);
  await shot(page, "j4-pack-test-run");
  observe({ journey: 4, testRun: page.url(), text: (await mainText(page)).slice(0, 3000), ...w });
  expect(page.url()).toMatch(/run_/);
  expect.soft(w.failed).toEqual([]);
  await context.close();
});

test("turn on publishing in Settings", async ({ browser }) => {
  const context = await contextAs(browser, "alice");
  const page = await context.newPage();
  await page.goto("/app/settings#workspace");
  await settle(page);
  const turnOn = page.getByRole("button", { name: "Turn on publishing" });
  if (await turnOn.isVisible().catch(() => false)) {
    await turnOn.click();
    await page.getByLabel("Publisher name").fill("Alice Labs QA");
    await page.getByLabel("Description").last().fill("Small automations for busy inboxes.");
    await shot(page, "j4-publishing-form");
    await page.getByRole("button", { name: "Save" }).last().click();
  }
  await expect(page.getByText("Publishing is on.").or(page.getByText("Alice Labs QA")).first()).toBeVisible();
  await shot(page, "j4-publishing-on");
  observe({ journey: 4, publishing: (await mainText(page)).slice(-1500) });
  await context.close();
});

for (const kind of ["agent", "pack"] as const) {
  test(`submit the ${kind} for review and watch the checks reach In review`, async ({ browser }) => {
    const context = await contextAs(browser, "alice");
    const page = await context.newPage();
    const w = watch(page);
    await page.goto(kind === "agent" ? "/studio/agents" : "/studio/packs");
    await settle(page);
    await page.getByRole("link", { name: new RegExp(kind === "agent" ? AGENT : PACK) }).first().click();
    await settle(page);
    await page.getByRole("button", { name: "Submit for review" }).first().click();
    const dialog = page.locator("[role=dialog], [role=alertdialog]").filter({ hasText: "Submit" }).last();
    await expect(dialog.getByText(/Price per (call|run)/).first()).toBeVisible();
    const price = dialog.getByLabel(kind === "agent" ? "Price per call" : "Price per run");
    await price.fill(kind === "agent" ? "0.05" : "0.50");
    const query = dialog.getByLabel(/Gmail search/);
    if (await query.isVisible().catch(() => false)) await query.fill("in:inbox newer_than:7d");
    await shot(page, `j4-submit-${kind}-dialog`);
    observe({ journey: 4, submitDialog: kind, text: (await dialog.innerText()).slice(0, 2000) });
    await dialog.getByRole("button", { name: "Submit for review" }).click();
    // F-05 (fixed): the dialog reads the listing again while its checks run, so it reports them finishing.
    await expect
      .soft(dialog.getByText("Sent for review"), "the dialog reports the checks finishing")
      .toBeVisible({ timeout: 45_000 });
    await shot(page, `j4-submit-${kind}-result`);
    observe({ journey: 4, submitted: kind, result: (await dialog.innerText()).slice(0, 2000), ...w });
    await page.goto("/studio/publisher");
    await settle(page);
    await shot(page, `j4-publisher-after-${kind}`);
    // The publisher page reaches "In review" once the check run completes (polled by reloading).
    for (let i = 0; i < 20 && !(await page.getByText("In review").first().isVisible().catch(() => false)); i++) {
      await page.waitForTimeout(3000);
      await page.reload();
      await settle(page);
    }
    await shot(page, `j4-publisher-after-${kind}`);
    await expect(page.getByText("In review").first()).toBeVisible();
    await context.close();
  });
}

test("the pack's sandbox check waits on a review task the publisher must find and do", async ({ browser }) => {
  // F-07: a pack with a human-review step holds its own listing check in "Checking" until someone in the
  // publisher's workspace reviews the sandbox run's task; neither the dialog nor the listing says so.
  const context = await contextAs(browser, "alice");
  const page = await context.newPage();
  const api = await apiAs("alice");
  const runs = (await (await api.get("/v1/workflow-runs")).json()) as Array<Record<string, string>>;
  await api.dispose();
  const waiting = runs.find((r) => r.title === PACK && r.status === "WAITING_FOR_HUMAN");
  test.skip(!waiting, "no sandbox check is waiting on a reviewer");
  await page.goto("/studio/publisher");
  await settle(page);
  await page.getByRole("link", { name: new RegExp(PACK) }).first().click();
  await settle(page);
  await shot(page, "j4-pack-listing-checking");
  observe({ journey: 4, packListingChecking: (await mainText(page)).slice(0, 2500) });
  await reviewTask(page, `ht_${waiting?.id}_review_1`);
  await page.waitForTimeout(2000);
  const run = await waitForRun("alice", String(waiting?.id), ["COMPLETED", "FAILED"], 60_000);
  observe({ journey: 4, packCheckRun: run.status });
  await page.goto("/studio/publisher");
  for (let i = 0; i < 10; i++) {
    await settle(page);
    if (await page.getByRole("row", { name: new RegExp(`${PACK}.*In review`) }).isVisible().catch(() => false)) break;
    await page.waitForTimeout(3000);
    await page.reload();
  }
  await shot(page, "j4-publisher-pack-in-review");
  await expect(page.getByRole("row", { name: new RegExp(PACK) })).toContainText("In review");
  await context.close();
});
