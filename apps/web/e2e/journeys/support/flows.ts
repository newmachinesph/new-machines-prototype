import { expect, type APIRequestContext, type Page } from "@playwright/test";
import { apiAs, mainText, settle, type QaUser } from "./qa";

export type SamplePack = { slug: string; name: string; apps: string[] };

export const SAMPLE_PACKS: SamplePack[] = [
  { slug: "meeting-follow-ups", name: "Meeting Follow-ups", apps: ["Google Calendar", "Gmail"] },
  { slug: "weekly-expense-check", name: "Weekly Expense Check", apps: ["Google Sheets", "Gmail"] },
  { slug: "support-inbox-triage", name: "Support Inbox Triage", apps: ["Gmail", "Google Sheets"] },
  { slug: "inbox-lead-tracker", name: "Inbox Lead Tracker", apps: ["Gmail", "Google Sheets"] },
];

export const RECON: SamplePack = {
  slug: "order-payment-reconciliation",
  name: "Order & Payment Reconciliation",
  apps: ["Shopify", "Stripe", "Google Sheets"],
};

/** Marketplace -> pack page -> install review -> agree -> add. Skips when the pack is already added. */
export async function addPack(page: Page, pack: { slug: string; name: string }) {
  await page.goto("/app/marketplace");
  await settle(page);
  await page.locator(`a[href="/app/marketplace/${pack.slug}"]`).first().click();
  await page.waitForURL(new RegExp(`/app/marketplace/${pack.slug}$`));
  await settle(page);
  const add = page.locator(`a[href="/app/marketplace/${pack.slug}/install"]`).first();
  if (!(await add.isVisible().catch(() => false))) return "already-added";
  await add.click();
  await page.waitForURL(/\/install$/);
  await settle(page);
  const agree = page.getByText("I agree to the work contract");
  await agree.or(page.getByRole("button", { name: "Save pack settings" })).first().waitFor();
  if (!(await agree.isVisible())) return "already-added";
  await agree.click();
  await page.getByRole("button", { name: `Add ${pack.name}` }).click();
  await expect(page.getByText(/added to your workspace|added/i).first()).toBeVisible();
  return "added";
}

/** Connections page: switch every app the pack needs to simulated data. */
export async function connectSimulated(page: Page, apps: string[]) {
  await page.goto("/app/connections");
  await settle(page);
  for (const app of apps) {
    const button = page.getByRole("button", { name: `Use simulated data for ${app}` }).first();
    if (await button.isVisible().catch(() => false)) {
      await button.click();
      await expect(page.getByText(`${app} uses simulated data`).or(page.getByText(/sandbox/i)).first()).toBeVisible();
      await page.waitForTimeout(400);
    }
  }
}

/** Start a run from /app/runs/new?pack=<slug>; returns the run id from the URL it lands on. */
export const RUN_INPUTS: Record<string, Record<string, string>> = {
  // The sandbox calendar holds meetings on 2026-10-15 and the sandbox sheet a week from 2026-10-05.
  "meeting-follow-ups": { Day: "2026-10-15", Signature: "Alice" },
  "weekly-expense-check": { "Week start": "2026-10-05", "Email to": "alice@qa.example" },
  "order-payment-reconciliation": { Since: "2026-10-01", Until: "2026-10-10" },
};

export async function startRun(page: Page, slug: string, inputs = RUN_INPUTS[slug] ?? {}): Promise<string> {
  await page.goto(`/app/runs/new?pack=${slug}`);
  await settle(page);
  for (const [label, value] of Object.entries(inputs)) {
    const field = page.getByLabel(new RegExp(`^${label}`, "i")).first();
    if (!(await field.isVisible().catch(() => false))) continue;
    await field.fill(value);
  }
  // What was typed must still be there once the page has settled: the form keeps typed values whatever loads after.
  await page.waitForTimeout(600);
  for (const [label, value] of Object.entries(inputs)) {
    const field = page.getByLabel(new RegExp(`^${label}`, "i")).first();
    if (await field.isVisible().catch(() => false)) await expect(field).toHaveValue(value);
  }
  const started = page.waitForResponse((r) => r.url().endsWith("/v1/workflow-runs") && r.request().method() === "POST", {
    timeout: 20_000,
  });
  await page.getByRole("button", { name: "Start run" }).click();
  const resp = await started;
  if (resp.status() >= 400) {
    await page.waitForTimeout(1200);
    const shown = await page
      .locator("[role=alert], [role=status], [data-sonner-toast], li[role=status]")
      .allInnerTexts()
      .catch(() => []);
    throw new Error(`start run ${slug}: HTTP ${resp.status()} ${await resp.text()} | shown to the user: ${JSON.stringify(shown)}`);
  }
  await page.waitForURL(/\/app\/runs\/run_[A-Za-z0-9_]+$/, { timeout: 30_000 });
  return page.url().split("/").pop() as string;
}

export async function runOf(api: APIRequestContext, runId: string) {
  return (await api.get(`/v1/workflow-runs/${runId}`)).json();
}

/** Pack settings: choose a per-run spending cap (e.g. "$5.00", or "max" for the highest one offered) and save. */
export async function setPerRunCap(page: Page, slug: string, cap: string) {
  await page.goto(`/app/marketplace/${slug}/install`);
  await settle(page);
  // The caps offered stop at the pack's own maximum, so "max" is the last one in the group.
  const group = page.getByRole("group", { name: "Spending cap per run" });
  const radio = cap === "max" ? group.getByRole("radio").last() : page.getByRole("radio", { name: cap }).first();
  await radio.click();
  await page.getByRole("button", { name: "Save pack settings" }).click();
  await expect(page.getByText("Pack settings saved").first()).toBeVisible();
}

/** Poll the API until the run's status is one of `statuses` (or any non-RUNNING status when omitted). */
export async function waitForRun(user: QaUser, runId: string, statuses?: string[], timeoutMs = 90_000) {
  const api = await apiAs(user);
  const until = Date.now() + timeoutMs;
  let run = await runOf(api, runId);
  while (Date.now() < until) {
    run = await runOf(api, runId);
    const done = statuses ? statuses.includes(run.status) : run.status !== "RUNNING";
    if (done) break;
    await new Promise((r) => setTimeout(r, 1500));
  }
  await api.dispose();
  return run;
}

export async function pendingApprovals(user: QaUser, runId: string) {
  const api = await apiAs(user);
  const all = await (await api.get("/v1/approvals")).json();
  await api.dispose();
  const list = (Array.isArray(all) ? all : (all.items ?? [])) as Array<Record<string, unknown>>;
  return list.filter((a) => a.runId === runId && (a.status ?? "PENDING") === "PENDING");
}

export async function eligibleTasks(user: QaUser, runId?: string) {
  const api = await apiAs(user);
  const all = await (await api.get("/v1/human-tasks/eligible")).json();
  await api.dispose();
  const list = (Array.isArray(all) ? all : (all.items ?? [])) as Array<Record<string, unknown>>;
  return runId ? list.filter((t) => t.runId === runId) : list;
}

/** On /app/approvals, act on the first pending card of this run. */
export async function decideApproval(page: Page, runTitle: string, decision: "approve" | "decline") {
  await page.goto("/app/approvals");
  await settle(page);
  const name = decision === "approve" ? /^Approve( and send)?$/ : /^Decline$/;
  const button = page.getByRole("button", { name }).first();
  await expect(button, `a pending approval for ${runTitle}`).toBeVisible();
  await button.click();
  const done = decision === "approve" ? /Approved/ : /Declined/;
  await expect(page.getByText(done).first()).toBeVisible();
  return mainText(page);
}

/** /work/tasks/<id>: claim, mark every record, choose a verdict and submit. */
export async function reviewTask(page: Page, taskId: string, verdict: RegExp = /^Approve as is/) {
  await page.goto(`/work/tasks/${taskId}`);
  await settle(page);
  const claim = page.getByRole("button", { name: "Claim this task" });
  if (await claim.isVisible().catch(() => false)) await claim.click();
  await expect(page.getByRole("button", { name: "Submit review" })).toBeVisible();
  for (const group of await page.getByRole("radiogroup").all()) {
    const first = group.getByRole("radio").first();
    if (await first.isVisible().catch(() => false)) await first.click();
  }
  const verdictRadio = page.getByRole("radio", { name: verdict }).first();
  if (await verdictRadio.isVisible().catch(() => false)) await verdictRadio.click();
  await page.locator("#feedback").fill("Checked every case during QA.");
  await page.getByRole("button", { name: "Submit review" }).click();
}
