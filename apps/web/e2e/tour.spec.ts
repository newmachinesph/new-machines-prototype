import { expect, test, type Page } from "@playwright/test";
import { presignIn, TOUR_SEEN_KEYS, waitForPageReady } from "./helpers";

/**
 * The product tours, in the browser. The e2e build turns the first-visit tours off (NEXT_PUBLIC_TOURS=off), so
 * every tour here is started the way a person replays one: "Take the tour" in the workspace menu, or the palette.
 */

const card = (page: Page) => page.getByRole("dialog", { name: /./ }).filter({ hasText: /Step \d+ of \d+/ });
const accountMenu = (page: Page) => page.locator('[data-tour="account-menu"]:visible');

async function finishTour(page: Page) {
  const tour = card(page);
  for (;;) {
    const done = tour.getByRole("button", { name: "Done" });
    if (await done.isVisible()) {
      await done.click();
      break;
    }
    await tour.getByRole("button", { name: "Next" }).click();
  }
  await expect(tour).toBeHidden();
}

test.beforeEach(async ({ context }) => {
  // The other specs start with every tour seen; these start with none.
  await presignIn(context, { toursSeen: false });
});

const seenState = (page: Page) => page.evaluate((keys) => keys.map((k) => localStorage.getItem(k)), TOUR_SEEN_KEYS);

test("the welcome tour replays from the workspace menu and is remembered", async ({ page }) => {
  await page.goto("/app");
  await waitForPageReady(page, page.locator('[data-tour="ask-box"]'));
  // No tour has been seen, and still none starts by itself in this build.
  expect(await seenState(page)).toEqual([null, null, null]);
  await expect(card(page)).toHaveCount(0);

  await accountMenu(page).click();
  await page.getByRole("menuitem", { name: "Take the tour" }).click();

  const tour = card(page);
  // A replay waits for the page's data to settle, which a cold server can take a while to serve.
  await expect(tour.getByRole("heading", { name: "Start from the outcome" })).toBeVisible({ timeout: 15_000 });
  await expect(tour).toHaveAttribute("aria-modal", "true");
  await expect(tour.getByRole("button", { name: "Next" })).toBeFocused();
  // The page behind the card is inert while the tour shows.
  await expect(page.locator('[data-name="nextstep-site"]')).toHaveAttribute("inert", "");

  await finishTour(page);
  expect(await page.evaluate(() => localStorage.getItem("nm.tour.welcome.v1"))).toBe("done");
  await expect(page.locator('[data-name="nextstep-site"]')).not.toHaveAttribute("inert");
  // Focus goes back to the menu's trigger, which opened the tour.
  await expect(accountMenu(page)).toBeFocused();

  // A finished tour stays finished, and can still be taken again.
  await page.reload();
  await waitForPageReady(page, page.locator('[data-tour="ask-box"]'));
  await expect(card(page)).toHaveCount(0);
  await accountMenu(page).click();
  await page.getByRole("menuitem", { name: "Take the tour" }).click();
  await expect(card(page).getByRole("heading", { name: "Start from the outcome" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(card(page)).toBeHidden();
});

test("replaying from another page of the workspace goes to the overview first", async ({ page }) => {
  await page.goto("/app/marketplace");
  await waitForPageReady(page, accountMenu(page));
  await accountMenu(page).click();
  await page.getByRole("menuitem", { name: "Take the tour" }).click();
  await page.waitForURL(/\/app$/);
  await expect(card(page).getByRole("heading", { name: "Start from the outcome" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(card(page)).toBeHidden();
});

test("a run page has its own tour, started from the palette", async ({ page }) => {
  await page.goto("/app/runs/run_1042");
  await waitForPageReady(page, page.locator('[data-tour="run-steps"]'));
  await expect(card(page)).toHaveCount(0);

  await page.keyboard.press("Control+k");
  await page.getByRole("option", { name: "Take the tour" }).click();
  await expect(card(page).getByRole("heading", { name: "The run's steps" })).toBeVisible();
  await finishTour(page);
  expect(await page.evaluate(() => localStorage.getItem("nm.tour.run.v1"))).toBe("done");
  await expect(page).toHaveURL(/\/app\/runs\/run_1042$/);
});
