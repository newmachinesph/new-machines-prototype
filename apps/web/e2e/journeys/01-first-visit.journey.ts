import { expect, test } from "@playwright/test";
import {
  contextAs,
  HIRE_WORDS,
  mainText,
  observe,
  overflowCulprits,
  overflowX,
  settle,
  shot,
  VENDOR_WORDS,
  watch,
} from "./support/qa";

// Journey 1: a brand-new owner (nora, a fresh workspace) signs in and walks every top-level page.
export const TOP_LEVEL = [
  "/app",
  "/app/runs",
  "/app/runs/new",
  "/app/marketplace",
  "/app/agents",
  "/app/approvals",
  "/app/memory",
  "/app/connections",
  "/app/reviewers",
  "/app/usage",
  "/app/settings",
  "/work",
  "/work/earnings",
  "/studio",
  "/studio/agents",
  "/studio/packs",
  "/studio/publisher",
];

test.describe("journey 1: first visit", () => {
  test("sign in from the landing page lands in the workspace overview", async ({ browser }) => {
    const context = await contextAs(browser, "nora", { signedIn: false });
    const page = await context.newPage();
    const w = watch(page);
    await page.goto("/");
    await settle(page);
    await shot(page, "j1-landing-1440");
    await page.getByRole("button", { name: "Sign in" }).first().click();
    await page.waitForURL(/\/app$/);
    await settle(page);
    await shot(page, "j1-overview-first-visit");
    const text = await mainText(page);
    observe({ journey: 1, path: "/app", text: text.slice(0, 3000), ...w });
    expect.soft(w.consoleErrors, "console errors on landing + overview").toEqual([]);
    expect.soft(w.failed, "failed API calls on landing + overview").toEqual([]);
    await context.close();
  });

  for (const width of [1440, 390]) {
    test(`every top-level page renders cleanly at ${width}`, async ({ browser }) => {
      const context = await contextAs(browser, "nora", { width, height: width === 390 ? 844 : 900 });
      const page = await context.newPage();
      const problems: string[] = [];
      for (const path of TOP_LEVEL) {
        const w = watch(page);
        const resp = await page.goto(path);
        await settle(page);
        await page.waitForTimeout(500);
        const text = await mainText(page);
        const over = await overflowX(page);
        const name = `j1-${path.replaceAll("/", "_").replace(/^_/, "")}-${width}`;
        await shot(page, name);
        if (!resp || resp.status() >= 400) problems.push(`${path}: HTTP ${resp?.status()}`);
        if (over > 0) problems.push(`${path}: overflows by ${over}px: ${(await overflowCulprits(page)).join("; ")}`);
        if (w.consoleErrors.length) problems.push(`${path}: console ${w.consoleErrors.join(" | ")}`);
        if (w.failed.length) problems.push(`${path}: network ${w.failed.join(" | ")}`);
        if (VENDOR_WORDS.test(text)) problems.push(`${path}: vendor name "${text.match(VENDOR_WORDS)?.[0]}"`);
        if (HIRE_WORDS.test(text)) problems.push(`${path}: "hire" copy: ${text.match(new RegExp(`.{0,60}${HIRE_WORDS.source}.{0,60}`, "i"))?.[0]}`);
        observe({ journey: 1, width, path, over, text: text.slice(0, 4000), ...w });
      }
      observe({ journey: 1, width, problems });
      expect.soft(problems, `problems at ${width}`).toEqual([]);
      await context.close();
    });
  }

  test("links on top-level pages lead somewhere", async ({ browser }) => {
    const context = await contextAs(browser, "nora");
    const page = await context.newPage();
    const hrefs = new Set<string>();
    for (const path of TOP_LEVEL) {
      await page.goto(path);
      await settle(page);
      for (const href of await page.locator("a[href^='/']").evaluateAll((as) => as.map((a) => a.getAttribute("href") ?? ""))) {
        hrefs.add(href.split("#")[0]);
      }
    }
    const broken: string[] = [];
    for (const href of hrefs) {
      if (!href) continue;
      const resp = await page.request.get(href);
      if (resp.status() >= 400) broken.push(`${href} -> ${resp.status()}`);
    }
    observe({ journey: 1, links: [...hrefs], broken });
    expect.soft(broken, "broken internal links").toEqual([]);
    await context.close();
  });
});
