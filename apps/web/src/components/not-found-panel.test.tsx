import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { mergeMessages } from "@/i18n/locales";
import { renderWithIntl } from "@/test/intl";
import en from "../../messages/en.json";
import ja from "../../messages/ja.json";
import BusinessNotFound from "@/app/app/not-found";
import StudioNotFound from "@/app/studio/not-found";
import WorkNotFound from "@/app/work/not-found";

// The pages are async server components; give them the translator the server would, in the locale under test.
const locale = vi.hoisted(() => ({ current: "en" as "en" | "ja" }));
vi.mock("next-intl/server", async () => {
  const { createTranslator } = await import("next-intl");
  return {
    getTranslations: async (namespace: string) =>
      createTranslator({
        locale: locale.current,
        messages: mergeMessages(en, locale.current === "ja" ? ja : en),
        namespace: namespace as never,
      }),
  };
});

// Each area's missing page keeps the area's shell (it renders inside the area layout) and leads on within it.
describe("area not-found pages", () => {
  it("sends a business-workspace visitor to the overview or the runs", async () => {
    renderWithIntl(await BusinessNotFound());
    expect(screen.getByRole("heading", { name: "There is nothing at this address" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to overview" })).toHaveAttribute("href", "/app");
    expect(screen.getByRole("link", { name: "See all runs" })).toHaveAttribute("href", "/app/runs");
    expect(document.title).toBe("There is nothing at this address | New Machines");
  });

  it("sends a reviewer back to the available tasks, not the business workspace", async () => {
    renderWithIntl(await WorkNotFound());
    expect(screen.getByRole("link", { name: "Back to available tasks" })).toHaveAttribute("href", "/work");
    expect(screen.queryByRole("link", { name: "Go to overview" })).toBeNull();
  });

  it("sends a builder back to the Studio, in Japanese too", async () => {
    locale.current = "ja";
    renderWithIntl(await StudioNotFound(), { locale: "ja" });
    expect(screen.getByRole("link", { name: "スタジオに戻る" })).toHaveAttribute("href", "/studio");
  });
});
