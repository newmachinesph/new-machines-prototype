import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import en from "../../messages/en.json";
import LandingPage from "./page";

// The landing page is an async server component; give it the same translators the server would.
vi.mock("next-intl/server", async () => {
  const { createTranslator } = await import("next-intl");
  return {
    getLocale: async () => "en",
    getTranslations: async (namespace: string) =>
      createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  };
});
// The form heads itself from `area`; what it shows is its own test's business.
vi.mock("./sign-in-form", () => ({
  SignInForm: ({ area }: { area: string | null }) => <form aria-label="sign-in" data-area={area ?? "none"} />,
}));
vi.mock("./run-record", () => ({ RunRecord: () => <section /> }));
vi.mock("@/components/language-switch", () => ({ LanguageSwitch: () => <div /> }));

const page = async (next?: string) => renderWithIntl(await LandingPage({ searchParams: Promise.resolve({ next }) }));

describe("landing page", () => {
  it("gives the form no area by default", async () => {
    await page();
    expect(screen.getByRole("form", { name: "sign-in" })).toHaveAttribute("data-area", "none");
  });

  it.each([
    ["/work", "work"],
    ["/app/runs/run_1042", "app"],
    ["/studio", "studio"],
  ])("tells the form where sign-in continues to when next is %s", async (next, area) => {
    await page(next);
    expect(screen.getByRole("form", { name: "sign-in" })).toHaveAttribute("data-area", area);
  });

  it("ignores an unsafe next", async () => {
    await page("//evil.com");
    expect(screen.getByRole("form", { name: "sign-in" })).toHaveAttribute("data-area", "none");
  });

  it("keeps the footer to a neutral line", async () => {
    await page();
    expect(screen.queryByText(/Builder Cup|Not indexed/)).not.toBeInTheDocument();
    expect(screen.getByText(/no money moves/)).toBeInTheDocument();
  });

  it("carries no private-demo label in the header", async () => {
    await page();
    expect(screen.queryByText(/Private demo/)).not.toBeInTheDocument();
    expect(screen.getByRole("banner")).not.toHaveTextContent(/synthetic/);
  });
});
