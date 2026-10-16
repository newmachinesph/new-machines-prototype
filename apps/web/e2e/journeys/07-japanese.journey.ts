import { expect, test } from "@playwright/test";
import { contextAs, mainText, observe, overflowCulprits, overflowX, settle, shot } from "./support/qa";

// Journey 7: alice switches to Japanese and every page from the journeys above is spot-checked for English
// left in product copy (fixture and user data stay English), overflow at 1440 and 390, and raw ICU syntax.
const PAGES = [
  "/app",
  "/app/runs",
  "/app/marketplace",
  "/app/agents",
  "/app/approvals",
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
  "/studio/agents/new",
  "/app/runs/new",
];

// English sentences of product copy: 4+ consecutive English words.
const ENGLISH_RUN = /\b(?:[A-Z]?[a-z]{2,}[,.]? ){3,}[a-z]{2,}\b/g;

for (const width of [1440, 390]) {
  test(`Japanese at ${width}: no untranslated copy, overflow or raw plurals`, async ({ browser }) => {
    // F-11: server-written copy (attention items, policies, run summaries, approval titles, tool and input
    // help) stays English in Japanese; English is checked at 1440 only. The /studio overflow at 390 is fixed.
    test.fail(width === 1440, "F-11: untranslated server copy in Japanese");
    const context = await contextAs(browser, "alice", { locale: "ja", width, height: 900 });
    const page = await context.newPage();
    const problems: string[] = [];
    for (const path of PAGES) {
      await page.goto(path);
      await settle(page);
      const text = await mainText(page);
      await shot(page, `j7-ja${path.replaceAll("/", "_")}-${width}`);
      const english = [...new Set(text.match(ENGLISH_RUN) ?? [])].slice(0, 6);
      const over = await overflowX(page);
      if (over > 0) problems.push(`${path}: overflow ${over}px ${(await overflowCulprits(page)).join("; ")}`);
      if (/\{[a-z]+, (plural|select)/.test(text)) problems.push(`${path}: raw ICU`);
      observe({ journey: 7, width, path, english, over });
      if (english.length && width === 1440) problems.push(`${path}: English: ${english.join(" | ")}`);
    }
    observe({ journey: 7, width, problems });
    expect.soft(problems).toEqual([]);
    await context.close();
  });
}
