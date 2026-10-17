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
vi.mock("./sign-in-form", () => ({ SignInForm: () => <form aria-label="sign-in" /> }));
vi.mock("./run-record", () => ({ RunRecord: () => <section /> }));
vi.mock("@/components/language-switch", () => ({ LanguageSwitch: () => <div /> }));

const page = async (next?: string) => renderWithIntl(await LandingPage({ searchParams: Promise.resolve({ next }) }));

describe("landing page", () => {
  it("titles the form for the demo workspace by default", async () => {
    await page();
    expect(screen.getByRole("heading", { level: 2, name: "Sign in to the demo workspace" })).toBeInTheDocument();
  });

  it.each([
    ["/work", "the reviewer portal"],
    ["/app/runs/run_1042", "the business workspace"],
    ["/studio", "the Studio"],
  ])("says where sign-in continues to when next is %s", async (next, where) => {
    await page(next);
    expect(screen.getByRole("heading", { level: 2, name: `Sign in to continue to ${where}` })).toBeInTheDocument();
  });

  it("ignores an unsafe next", async () => {
    await page("//evil.com");
    expect(screen.getByRole("heading", { level: 2, name: "Sign in to the demo workspace" })).toBeInTheDocument();
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
