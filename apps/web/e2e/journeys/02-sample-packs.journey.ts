import { expect, test, type Page } from "@playwright/test";
import {
  addPack,
  connectSimulated,
  decideApproval,
  eligibleTasks,
  reviewTask,
  SAMPLE_PACKS,
  setPerRunCap,
  startRun,
  waitForRun,
} from "./support/flows";
import { apiAs, contextAs, mainText, observe, settle, shot, VENDOR_WORDS, watch } from "./support/qa";

// Journey 2: alice adds each of the four sample packs from the marketplace, connects simulated apps, runs
// each one through its approvals (one approved, one declined) and the reviewer path, and checks the
// decision-model step, the receipt and Usage.
test.describe.configure({ mode: "serial" });

const OPEN = ["WAITING_FOR_EVENT", "WAITING_FOR_HUMAN", "WAITING_FOR_APPROVAL", "COMPLETED", "FAILED", "CANCELLED", "DECLINED", "STOPPED"];

async function runPageChecks(page: Page, runId: string, tag: string) {
  await page.goto(`/app/runs/${runId}`);
  await settle(page);
  await page.waitForTimeout(800);
  await shot(page, `j2-${tag}-run`);
  return mainText(page);
}

// F-01 (fixed): these packs refuse any budget above $10 (BUDGET_TOO_HIGH); the start form offers only budgets
// within the pack's maximum and the per-run cap less the pack fee, so a run starts with the defaults.
const BUDGET_BLOCKED = new Set(["meeting-follow-ups", "inbox-lead-tracker"]);

for (const pack of SAMPLE_PACKS.filter((p) => BUDGET_BLOCKED.has(p.slug))) {
  test(`${pack.name}: a run starts with the default choices`, async ({ browser }) => {
    const context = await contextAs(browser, "alice");
    const page = await context.newPage();
    await addPack(page, pack);
    await connectSimulated(page, pack.apps);
    // The caps offered stop at the pack's maximum; take the highest, in case an earlier run lowered it.
    await setPerRunCap(page, pack.slug, "max");
    try {
      await startRun(page, pack.slug);
    } finally {
      await shot(page, `j2-${pack.slug}-start-refused`);
      await context.close();
    }
  });
}

for (const pack of SAMPLE_PACKS) {
  test(`add ${pack.name}, connect simulated apps, run it to approvals or review`, async ({ browser }) => {
    const context = await contextAs(browser, "alice");
    const page = await context.newPage();
    const w = watch(page);
    const outcome = await addPack(page, pack);
    await shot(page, `j2-${pack.slug}-added`);
    await connectSimulated(page, pack.apps);
    await shot(page, `j2-${pack.slug}-connections`);
    const runId = await startRun(page, pack.slug);
    const run = await waitForRun("alice", runId, OPEN);
    const text = await runPageChecks(page, runId, pack.slug);
    observe({ journey: 2, pack: pack.slug, outcome, runId, status: run.status, text: text.slice(0, 5000), ...w });
    expect.soft(w.consoleErrors, "console errors").toEqual([]);
    expect.soft(w.failed, "failed API calls").toEqual([]);
    expect.soft(text, "sandbox / simulated label on the run page").toMatch(/sandbox|simulated/i);
    expect.soft(text).not.toMatch(VENDOR_WORDS);
    expect(OPEN).toContain(run.status);
    test.info().annotations.push({ type: "run", description: `${pack.slug}=${runId}` });
    await context.close();
  });
}

test("decision-model steps explain themselves on the run page", async ({ browser }) => {
  const context = await contextAs(browser, "alice");
  const page = await context.newPage();
  await page.goto("/app/runs");
  await settle(page);
  // The support triage and lead tracker runs each ask the decision model.
  for (const name of ["Support Inbox Triage", "Inbox Lead Tracker"]) {
    await page.goto("/app/runs");
    await settle(page);
    await page.getByRole("link", { name: new RegExp(name) }).filter({ visible: true }).first().click();
    await page.waitForURL(/\/app\/runs\/run_/);
    await settle(page);
    // Select the decision-model step through its timeline event (the canvas nodes are tiny at default zoom).
    const decision = page.getByText("Decision step").first();
    await expect.soft(decision, `${name}: decision step in the timeline`).toBeVisible();
    if (await decision.isVisible().catch(() => false)) {
      await decision.click({ force: true });
      await page.waitForTimeout(800);
    }
    const selected = page.locator("section, div").filter({ hasText: /^Selected step/ }).first();
    await expect.soft(page.getByText("Decision model").first(), `${name}: "Decision model" named`).toBeVisible();
    observe({ journey: 2, decisionSelected: name, text: (await selected.innerText().catch(() => "")).slice(0, 2000) });
    const text = await mainText(page);
    await shot(page, `j2-decision-${name.replaceAll(" ", "-").toLowerCase()}`);
    observe({ journey: 2, decision: name, text: text.slice(0, 5000) });
    expect.soft(text).not.toMatch(VENDOR_WORDS);
  }
  await context.close();
});

test("support triage reaches the human reviewer path and the reviewer can complete it", async ({ browser }) => {
  const context = await contextAs(browser, "alice");
  const page = await context.newPage();
  const w = watch(page);
  await page.goto("/work");
  await settle(page);
  await shot(page, "j2-work-queue");
  const tasks = await eligibleTasks("alice");
  let support = tasks.find((t) => String(t.packName).includes("Support"));
  if (!support) {
    // Already claimed by an earlier attempt: a claimed task leaves the eligible list.
    const api = await apiAs("alice");
    const runs = (await (await api.get("/v1/workflow-runs")).json()) as Array<Record<string, string>>;
    await api.dispose();
    const waiting = (Array.isArray(runs) ? runs : []).find(
      (r) => r.packSlug === "support-inbox-triage" && r.status === "WAITING_FOR_HUMAN",
    );
    if (waiting) support = { id: `ht_${waiting.id}_review_1`, runId: waiting.id };
  }
  expect(support, "a support triage review task is offered to the team").toBeTruthy();
  const taskId = String(support?.id);
  await page.goto(`/work/tasks/${taskId}`);
  await settle(page);
  await shot(page, "j2-support-task-offer");
  const offer = await mainText(page);
  observe({ journey: 2, task: taskId, text: offer.slice(0, 5000) });
  // Finding F-SUPPORT-TASK: an email case is shown as an order/payout record ("Payout", "Batch", "$0.00").
  expect.soft(offer, "support review shows order/payout fields for an email case").not.toMatch(/Payout|Batch|Paid out/);
  await reviewTask(page, taskId);
  await page.waitForTimeout(1500);
  await shot(page, "j2-support-task-submitted");
  const after = await mainText(page);
  observe({ journey: 2, taskSubmitted: taskId, text: after.slice(0, 3000), ...w });
  expect.soft(after).toMatch(/Submitted|Accepted|Checking/);
  const runId = String(support?.runId);
  const run = await waitForRun("alice", runId, ["WAITING_FOR_EVENT", "WAITING_FOR_APPROVAL", "COMPLETED", "FAILED"]);
  observe({ journey: 2, supportAfterReview: run.status });
  expect(["WAITING_FOR_EVENT", "WAITING_FOR_APPROVAL", "COMPLETED"]).toContain(run.status);
  await context.close();
});

test("approve one action and decline another", async ({ browser }) => {
  const context = await contextAs(browser, "alice");
  const page = await context.newPage();
  const w = watch(page);
  await page.goto("/app/approvals");
  await settle(page);
  await shot(page, "j2-approvals-pending");
  const listText = await mainText(page);
  observe({ journey: 2, approvals: listText.slice(0, 5000) });
  expect.soft(listText, "approvals name sandbox/simulated").toMatch(/sandbox|simulated/i);
  const approvedText = await decideApproval(page, "first pending", "approve");
  await shot(page, "j2-approval-approved");
  const declinedText = await decideApproval(page, "next pending", "decline");
  await shot(page, "j2-approval-declined");
  observe({ journey: 2, approvedText: approvedText.slice(0, 1500), declinedText: declinedText.slice(0, 1500), ...w });
  expect.soft(w.consoleErrors).toEqual([]);
  expect.soft(w.failed).toEqual([]);
  await context.close();
});

test("drive every sample run to an end: approve what is left", async ({ browser }) => {
  const context = await contextAs(browser, "alice");
  const page = await context.newPage();
  const statuses: Record<string, string> = {};
  for (let round = 0; round < 8; round++) {
    await page.goto("/app/approvals");
    await settle(page);
    const approve = page.getByRole("button", { name: /^Approve( and send)?$/ }).first();
    if (!(await approve.isVisible().catch(() => false))) break;
    await approve.click();
    await page.waitForTimeout(2500);
  }
  // Review tasks (weekly expense flags) the earlier test did not handle.
  for (const t of await eligibleTasks("alice")) {
    await reviewTask(page, String(t.id));
    await page.waitForTimeout(1500);
  }
  for (let round = 0; round < 6; round++) {
    await page.goto("/app/approvals");
    await settle(page);
    const approve = page.getByRole("button", { name: /^Approve( and send)?$/ }).first();
    if (!(await approve.isVisible().catch(() => false))) break;
    await approve.click();
    await page.waitForTimeout(2500);
  }
  await page.goto("/app/runs");
  await settle(page);
  await shot(page, "j2-runs-list");
  const text = await mainText(page);
  observe({ journey: 2, runsList: text.slice(0, 4000) });
  statuses.list = text.slice(0, 200);
  expect.soft(text, "runs list states that costs are simulated").toMatch(/simulated/i);
  await context.close();
});

test("receipt and Usage show the spend, labelled simulated", async ({ browser }) => {
  const context = await contextAs(browser, "alice");
  const page = await context.newPage();
  const w = watch(page);
  await page.goto("/app/runs");
  await settle(page);
  const first = page.locator("a[href^='/app/runs/run_']").filter({ visible: true }).first();
  const href = await first.getAttribute("href");
  await page.goto(`${href}/evidence`);
  await settle(page);
  await page.waitForTimeout(800);
  await shot(page, "j2-receipt");
  const receipt = await mainText(page);
  observe({ journey: 2, receipt: receipt.slice(0, 5000) });
  expect.soft(receipt).toMatch(/deliverable/i);
  expect.soft(receipt).toMatch(/sandbox|simulated/i);
  await page.goto("/app/usage");
  await settle(page);
  await shot(page, "j2-usage");
  const usage = await mainText(page);
  observe({ journey: 2, usage: usage.slice(0, 5000), ...w });
  expect.soft(usage).toMatch(/Simulated billing|simulated/i);
  expect.soft(usage).toMatch(/AI usage|Meeting Follow-ups|Support Inbox Triage/);
  expect.soft(w.failed).toEqual([]);
  await context.close();
});
