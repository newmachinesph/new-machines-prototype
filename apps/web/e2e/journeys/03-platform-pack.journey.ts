import { expect, test } from "@playwright/test";
import { addPack, connectSimulated, RECON, reviewTask, startRun, waitForRun } from "./support/flows";
import { contextAs, mainText, observe, settle, shot, watch } from "./support/qa";

// Journey 3: an existing platform pack (order-payment reconciliation) end to end: add, connect, run, review
// the mismatches as the team reviewer, approve the sheet write, read the deliverable.
test("order-payment reconciliation: full run path with review tasks", async ({ browser }) => {
  test.setTimeout(300_000);
  const context = await contextAs(browser, "alice");
  const page = await context.newPage();
  const w = watch(page);
  await addPack(page, RECON);
  await connectSimulated(page, RECON.apps);
  const runId = await startRun(page, RECON.slug);
  let run = await waitForRun("alice", runId, ["WAITING_FOR_HUMAN", "WAITING_FOR_EVENT", "COMPLETED", "FAILED"]);
  await shot(page, "j3-recon-run-waiting");
  if (run.status === "WAITING_FOR_HUMAN") {
    await reviewTask(page, `ht_${runId}_review_1`);
    await shot(page, "j3-recon-review-submitted");
    run = await waitForRun("alice", runId, ["WAITING_FOR_EVENT", "COMPLETED", "FAILED"]);
  }
  for (let i = 0; i < 3 && run.status === "WAITING_FOR_EVENT"; i++) {
    await page.goto("/app/approvals");
    await settle(page);
    await page.getByRole("button", { name: /^Approve( and send)?$/ }).first().click();
    await page.waitForTimeout(2500);
    run = await waitForRun("alice", runId, ["WAITING_FOR_EVENT", "COMPLETED", "FAILED"]);
  }
  observe({ journey: 3, runId, status: run.status });
  expect(run.status).toBe("COMPLETED");
  await page.goto(`/app/runs/${runId}/evidence`);
  await settle(page);
  await shot(page, "j3-recon-deliverable");
  const text = await mainText(page);
  observe({ journey: 3, deliverable: text.slice(0, 4000), ...w });
  expect.soft(text).toMatch(/sandbox|Simulated/);
  expect.soft(w.failed).toEqual([]);
  await context.close();
});
