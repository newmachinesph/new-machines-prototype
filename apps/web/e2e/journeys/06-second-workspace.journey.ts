import { expect, test } from "@playwright/test";
import { addPack, connectSimulated, reviewTask, startRun, waitForRun } from "./support/flows";
import { apiAs, contextAs, mainText, observe, settle, shot, watch } from "./support/qa";

// Journey 6: bob, in a second workspace, finds alice's listed agent and pack, adds the pack, runs it and
// sees the publisher fee on the deliverable and in Usage; alice then sees her earnings.
test.describe.configure({ mode: "serial" });

const STAMP = process.env.QA_STAMP ?? "A2";
const AGENT = `QA Inbox Reader ${STAMP}`;
const PACK = `QA Inbox Digest ${STAMP}`;
const PUBLISHER = "Alice Labs QA";

test("listed agent and pack show the publisher and their fee in another workspace", async ({ browser }) => {
  const context = await contextAs(browser, "bob");
  const page = await context.newPage();
  const w = watch(page);
  await page.goto("/app/marketplace");
  await settle(page);
  const packCard = page.locator("a, article, li").filter({ hasText: PACK }).first();
  await expect(packCard).toBeVisible();
  await shot(page, "j6-bob-marketplace");
  const packText = await packCard.innerText();
  observe({ journey: 6, packCard: packText });
  expect.soft(packText).toContain(PUBLISHER);
  expect.soft(packText).toMatch(/\$0\.50/);
  await page.goto("/app/agents");
  await settle(page);
  const agentCard = page.locator("a, article, li").filter({ hasText: AGENT }).first();
  await expect(agentCard).toBeVisible();
  const agentText = await agentCard.innerText();
  await shot(page, "j6-bob-agents");
  observe({ journey: 6, agentCard: agentText, ...w });
  expect.soft(agentText).toContain(PUBLISHER);
  expect.soft(agentText).toMatch(/\$0\.05/);
  expect.soft(w.failed).toEqual([]);
  await context.close();
});

test("bob adds the pack, runs it and sees the publisher fee on the deliverable and in Usage", async ({ browser }) => {
  // F-08 is fixed. F-01 does not fail this journey: a refused UI start falls back to the API below.
  const context = await contextAs(browser, "bob");
  const page = await context.newPage();
  const w = watch(page);
  await page.goto("/app/marketplace");
  await settle(page);
  const href = await page.locator("a[href^='/app/marketplace/']").filter({ hasText: PACK }).first().getAttribute("href");
  const slug = String(href).split("/").pop() as string;
  await addPack(page, { slug, name: PACK });
  await shot(page, "j6-bob-pack-added");
  await connectSimulated(page, ["Gmail"]);
  let runId: string;
  try {
    runId = await startRun(page, slug, { "Gmail search": "in:inbox newer_than:7d" });
  } catch (e) {
    // Before the F-01 fix the start form offered no budget within this pack's $2 maximum; should the UI start
    // still fail, start it through the API so the fee checks below still run.
    observe({ journey: 6, uiStartRefused: String(e).slice(0, 400) });
    await shot(page, "j6-bob-start-refused");
    const api = await apiAs("bob");
    const resp = await api.post("/v1/workflow-runs", {
      data: { packSlug: slug, input: { query: "in:inbox newer_than:7d" }, budgetMinor: 200 },
    });
    expect(resp.status(), await resp.text()).toBe(202);
    runId = (await resp.json()).id;
    await api.dispose();
  }
  let run = await waitForRun("bob", runId, ["WAITING_FOR_HUMAN", "COMPLETED", "FAILED"]);
  if (run.status === "WAITING_FOR_HUMAN") {
    await reviewTask(page, `ht_${runId}_review_1`);
    run = await waitForRun("bob", runId, ["COMPLETED", "FAILED"]);
  }
  observe({ journey: 6, bobRun: runId, status: run.status });
  expect(run.status).toBe("COMPLETED");
  await page.goto(`/app/runs/${runId}`);
  await settle(page);
  await shot(page, "j6-bob-run");
  const runText = await mainText(page);
  await page.goto(`/app/runs/${runId}/evidence`);
  await settle(page);
  await shot(page, "j6-bob-deliverable");
  const deliverable = await mainText(page);
  observe({ journey: 6, runText: runText.slice(0, 3000), deliverable: deliverable.slice(0, 4000) });
  expect.soft(runText + deliverable, "publisher fee on the run or deliverable").toMatch(/Publisher fee|publisher/i);
  expect.soft(runText + deliverable).toMatch(/Simulated/);
  await page.goto("/app/usage");
  await settle(page);
  await page.getByText(runId).first().click().catch(() => undefined);
  await page.waitForTimeout(800);
  await shot(page, "j6-bob-usage");
  const usage = await mainText(page);
  observe({ journey: 6, usage: usage.slice(0, 4000), ...w });
  expect.soft(usage).toMatch(/Publisher fees/);
  await page.getByRole("button", { name: "Show fee details" }).first().click().catch(() => undefined);
  await page.waitForTimeout(500);
  await shot(page, "j6-bob-usage-fee-details");
  expect.soft(await mainText(page)).toContain(PUBLISHER);
  // F-08 (fixed): the run's "Total so far" and the deliverable's "Why this is billable" total include the
  // publisher fees, on their own row.
  expect.soft(deliverable, "deliverable total includes publisher fees").toMatch(/Publisher fee/i);
  await context.close();
});

test("alice sees her earnings as publisher", async ({ browser }) => {
  const context = await contextAs(browser, "alice");
  const page = await context.newPage();
  await page.goto("/studio/publisher");
  await settle(page);
  await shot(page, "j6-alice-publisher-earnings");
  const text = await mainText(page);
  observe({ journey: 6, aliceEarnings: text.slice(0, 3000) });
  const row = page.getByRole("row", { name: new RegExp(PACK) });
  await expect(row).toBeVisible();
  // 80% of the $0.50 run fee.
  await expect.soft(row).toContainText("$0.40");
  expect.soft(text).toMatch(/Simulated/);
  await context.close();
});
