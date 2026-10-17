import { appendFileSync, mkdirSync } from "node:fs";
import type { APIRequestContext, Browser, BrowserContext, Page } from "@playwright/test";
import { request } from "@playwright/test";

export const WEB_URL = process.env.QA_WEB_URL ?? "http://localhost:3600";
export const OPS_URL = process.env.QA_OPS_URL ?? "http://localhost:3610";
export const API_URL = process.env.QA_API_URL ?? "http://127.0.0.1:8600";
export const SHOTS = "test-results/qa";
const MOCK_SESSION_KEY = "nm-mock-session";

/**
 * The QA users. qa_api.py turns the bearer token `qa.<name>` into a verified identity `<name>@qa.example`.
 * alice owns the publisher workspace; mia (member) and rita (reviewer) are invited into it; bob owns a
 * second workspace.
 */
export type QaUser = "alice" | "mia" | "rita" | "bob" | "nora";

export type Watch = { consoleErrors: string[]; failed: string[] };

/** Console errors and failed API calls (4xx/5xx or network failures) seen by a page. */
export function watch(page: Page): Watch {
  const w: Watch = { consoleErrors: [], failed: [] };
  page.on("console", (m) => {
    if (m.type() === "error") w.consoleErrors.push(`${page.url()} :: ${m.text().slice(0, 300)}`);
  });
  page.on("pageerror", (e) => w.consoleErrors.push(`${page.url()} :: pageerror ${e.message.slice(0, 300)}`));
  page.on("requestfailed", (r) => {
    const why = r.failure()?.errorText ?? "";
    // Polls abort when a page navigates away; that is not a failure a user sees.
    if (why.includes("ERR_ABORTED")) return;
    w.failed.push(`${r.method()} ${r.url()} :: ${why}`);
  });
  page.on("response", (r) => {
    if (r.status() >= 400 && r.url().startsWith(API_URL)) w.failed.push(`${r.status()} ${r.request().method()} ${r.url()}`);
  });
  return w;
}

/** A browser context signed in (mock session) as one QA user. */
export async function contextAs(
  browser: Browser,
  user: QaUser,
  opts: { locale?: "en" | "ja"; width?: number; height?: number; baseURL?: string; signedIn?: boolean } = {},
): Promise<BrowserContext> {
  const context = await browser.newContext({
    baseURL: opts.baseURL ?? WEB_URL,
    viewport: { width: opts.width ?? 1440, height: opts.height ?? 900 },
    extraHTTPHeaders: { Authorization: `Bearer qa.${user}` },
  });
  if (opts.signedIn !== false) await context.addInitScript((key) => {
    try {
      sessionStorage.setItem(key, "1");
    } catch {
      /* storage unavailable on about:blank */
    }
  }, MOCK_SESSION_KEY);
  if (opts.locale) {
    for (const url of [WEB_URL, OPS_URL]) await context.addCookies([{ name: "NEXT_LOCALE", value: opts.locale, url }]);
  }
  return context;
}

/** An API client acting as one QA user, for setup the UI does not offer (invitations to accept). */
export async function apiAs(user: QaUser): Promise<APIRequestContext> {
  return request.newContext({ baseURL: API_URL, extraHTTPHeaders: { Authorization: `Bearer qa.${user}` } });
}

export async function orgIdOf(user: QaUser): Promise<string> {
  const api = await apiAs(user);
  const me = await (await api.get("/v1/me")).json();
  await api.dispose();
  return me.orgId as string;
}

/** Owner alice invites `email` with `role`; the invitee accepts (they verify via the QA identity). */
export async function ensureMember(owner: QaUser, invitee: QaUser, role: "member" | "reviewer") {
  const ownerApi = await apiAs(owner);
  const ownerMe = await (await ownerApi.get("/v1/me")).json();
  const inviteeApi = await apiAs(invitee);
  const inviteeMe = await (await inviteeApi.get("/v1/me")).json();
  if (inviteeMe.orgId !== ownerMe.orgId) {
    // Members come through Settings > Invite (Member or Admin); reviewers through Reviewers > Add reviewer.
    const sent =
      role === "member"
        ? await ownerApi.post(`/v1/organizations/${ownerMe.orgId}/invitations`, {
            data: { email: `${invitee}@qa.example`, role: "Member" },
          })
        : await ownerApi.post(`/v1/organizations/${ownerMe.orgId}/reviewers`, {
            data: { email: `${invitee}@qa.example` },
          });
    const accepted = await inviteeApi.post(`/v1/invitations/${ownerMe.orgId}:accept`);
    if (accepted.status() >= 300) {
      throw new Error(`invite ${invitee}: ${sent.status()} ${await sent.text()} / accept ${accepted.status()} ${await accepted.text()}`);
    }
  }
  await ownerApi.dispose();
  await inviteeApi.dispose();
}

/** Horizontal overflow of the document, in pixels (0 when the page fits). */
export async function overflowX(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

/** Elements wider than the viewport, to name the culprit in a finding. */
export async function overflowCulprits(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const out: string[] = [];
    for (const el of Array.from(document.querySelectorAll("body *"))) {
      const r = el.getBoundingClientRect();
      if (r.right > vw + 1 && r.width > 0) {
        const cls = typeof el.className === "string" ? el.className.slice(0, 60) : "";
        out.push(`${el.tagName.toLowerCase()}.${cls} right=${Math.round(r.right)}`);
      }
      if (out.length >= 5) break;
    }
    return out;
  });
}

/** Text the user can read in <main>, for copy checks. */
export async function mainText(page: Page): Promise<string> {
  return (await page.locator("body").innerText()).replace(/\s+/g, " ");
}

/** Copy rules: product copy must not name model vendors, and agents are never "hired". */
export const VENDOR_WORDS = /\b(Jev|TypeSafe|OpenRouter|OpenAI|GPT|Gemini|Vertex)\b/;
export const HIRE_WORDS = /\bhir(e|ed|es|ing)\b/i;

/** Append an observation (page text, issues) to test-results/qa/observations.jsonl for the findings write-up. */
export function observe(record: Record<string, unknown>) {
  mkdirSync(SHOTS, { recursive: true });
  appendFileSync(`${SHOTS}/observations.jsonl`, `${JSON.stringify({ at: new Date().toISOString(), ...record })}\n`);
}

export async function shot(page: Page, name: string) {
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

/** Wait until the app has rendered and no loading skeleton is left. */
export async function settle(page: Page) {
  await page.waitForLoadState("domcontentloaded");
  await page.locator("main").first().waitFor({ state: "visible", timeout: 20_000 }).catch(() => undefined);
  // Twice: a client page can mount its skeleton only after the first check.
  for (const pause of [0, 700]) {
    await page.waitForTimeout(pause);
    await page
      .locator(".animate-pulse")
      .first()
      .waitFor({ state: "detached", timeout: 15_000 })
      .catch(() => undefined);
  }
}
