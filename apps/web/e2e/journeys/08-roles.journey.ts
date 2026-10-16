import { expect, test } from "@playwright/test";
import { apiAs, contextAs, ensureMember, mainText, observe, settle, shot } from "./support/qa";

// Journey 8: roles in alice's workspace. mia (member) cannot submit or manage publishing; rita (reviewer)
// sees only her review tasks.
test.beforeAll(async () => {
  await ensureMember("alice", "mia", "member");
  await ensureMember("alice", "rita", "reviewer");
});

test("a member cannot submit for review or manage publishing", async ({ browser }) => {
  const context = await contextAs(browser, "mia");
  const page = await context.newPage();
  await page.goto("/app/settings");
  await settle(page);
  await shot(page, "j8-member-settings");
  const settings = await mainText(page);
  observe({ journey: 8, memberSettings: settings.slice(-1500) });
  await expect(page.getByRole("button", { name: "Turn on publishing" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Turn off publishing" })).toHaveCount(0);
  await page.goto("/studio/agents");
  await settle(page);
  await page.getByRole("link", { name: /QA Inbox Reader/ }).first().click();
  await settle(page);
  await shot(page, "j8-member-agent");
  const submit = page.getByRole("button", { name: "Submit for review" });
  expect.soft(await submit.isVisible().catch(() => false) && (await submit.isEnabled()), "member sees an enabled Submit").toBe(false);
  // The API refuses too.
  const api = await apiAs("mia");
  const me = await (await api.get("/v1/me")).json();
  const pub = await api.put(`/v1/organizations/${me.orgId}/publisher`, { data: { name: "Mia's takeover" } });
  observe({ journey: 8, memberRole: me.role, publisherPut: pub.status() });
  expect(me.role).toBe("member");
  expect(pub.status()).toBe(403);
  await api.dispose();
  await context.close();
});

test("a reviewer sees only their review tasks", async ({ browser }) => {
  test.fail(true, "F-10: a Reviewer gets the whole business workspace: runs, approvals, spend, Start a run");
  const context = await contextAs(browser, "rita");
  const page = await context.newPage();
  await page.goto("/app");
  await settle(page);
  await shot(page, "j8-reviewer-app");
  const app = await mainText(page);
  await page.goto("/work");
  await settle(page);
  await shot(page, "j8-reviewer-work");
  const work = await mainText(page);
  const api = await apiAs("rita");
  const runs = await api.get("/v1/workflow-runs");
  const approvals = await api.get("/v1/approvals");
  observe({ journey: 8, reviewerApp: app.slice(0, 2000), reviewerWork: work.slice(0, 2000), runs: runs.status(), approvals: approvals.status() });
  await api.dispose();
  expect.soft(page.url()).toContain("/work");
  expect.soft(runs.status(), "reviewer reading every run of the workspace").toBe(403);
  expect.soft(approvals.status(), "reviewer reading approvals").toBe(403);
  await context.close();
});
