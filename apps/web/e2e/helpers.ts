import AxeBuilder from "@axe-core/playwright";
import { expect, type BrowserContext, type Locator, type Page } from "@playwright/test";

export const MOCK_SESSION_KEY = "nm-mock-session";

/** The product tours' "seen" keys (`nm.tour.<name>.v1`). */
export const TOUR_SEEN_KEYS = ["welcome", "studio", "run"].map((name) => `nm.tour.${name}.v1`);

/**
 * Start every page in the context already signed in (the mock session lives in sessionStorage). The product tours
 * count as seen, so none can open over a page under test even in a build with tours on; the tour spec passes
 * `toursSeen: false`.
 */
export async function presignIn(context: BrowserContext, { toursSeen = true }: { toursSeen?: boolean } = {}) {
  await context.addInitScript(
    ({ key, tours }) => {
      try {
        sessionStorage.setItem(key, "1");
        for (const tour of tours) localStorage.setItem(tour, "done");
      } catch {
        /* storage unavailable on about:blank */
      }
    },
    { key: MOCK_SESSION_KEY, tours: toursSeen ? TOUR_SEEN_KEYS : [] },
  );
}

export async function setLocale(context: BrowserContext, locale: "en" | "ja") {
  await context.addCookies([{ name: "NEXT_LOCALE", value: locale, url: "http://localhost:3100" }]);
}

/** Sign in through the landing page the way a person does. */
export async function signInThroughLanding(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/app$/);
}

/**
 * Page-ready signal that does not depend on the network being quiet (the app polls): a locator that only
 * appears once the route's data has rendered is visible, and then no loading skeleton (`animate-pulse`) is left.
 */
export async function waitForPageReady(page: Page, ready: Locator) {
  await expect(ready).toBeVisible();
  await expect(page.locator(".animate-pulse")).toHaveCount(0);
}

/** Fails on serious or critical axe violations, naming the rule and the nodes. React Flow's canvas internals are excluded. */
export async function expectNoSeriousA11yViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page }).exclude(".react-flow__renderer").analyze();
  const serious = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.help} [${v.nodes.map((n) => n.target.join(" ")).join(" | ")}]`)).toEqual([]);
}
