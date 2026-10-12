import { expect, test } from "@playwright/test";
import { ROUTES } from "./routes";
import { presignIn, setLocale, waitForPageReady } from "./helpers";

const WIDTHS = [390, 1440, 1920];
const LOCALES = ["en", "ja"] as const;

for (const locale of LOCALES) {
  for (const width of WIDTHS) {
    for (const { path: route, ready } of ROUTES) {
      test(`no horizontal overflow and a clean console: ${route} at ${width}px (${locale})`, async ({
        context,
        page,
      }) => {
        await setLocale(context, locale);
        await presignIn(context);
        await page.setViewportSize({ width, height: 900 });
        const errors: string[] = [];
        page.on("console", (m) => {
          if (m.type() === "error") errors.push(m.text());
        });
        page.on("pageerror", (e) => errors.push(String(e)));

        await page.goto(route);
        await waitForPageReady(page, ready(page));

        const { scrollWidth, innerWidth } = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
        }));
        expect(scrollWidth, `scrollWidth ${scrollWidth} > innerWidth ${innerWidth}`).toBeLessThanOrEqual(innerWidth);
        expect(errors).toEqual([]);
      });
    }
  }
}
