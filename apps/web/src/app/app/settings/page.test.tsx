import { screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import en from "../../../../messages/en.json";
import ja from "../../../../messages/ja.json";
import SettingsPage from "./page";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const locale = vi.hoisted(() => ({ current: "en" as "en" | "ja" }));

// The page is a server component: its own text comes from getTranslations, here read from the same files.
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: locale.current, messages: locale.current === "ja" ? ja : en, namespace } as never),
}));
vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => vi.fn(),
}));
vi.mock("@/lib/queries/me", () => ({ useIsDemo: () => false, useOrgId: () => "org_new" }));
vi.mock("./publisher", () => ({ PublisherSection: () => null }));
vi.mock("@/lib/queries/org", () => ({
  useOrg: () =>
    ok({
      id: "org_new",
      name: "Ana's workspace",
      short: "Ana's workspace",
      plan: "Trial",
      monthlyCap: { amountMinor: 25000, currency: "USD" },
      monthSpent: { amountMinor: 0, currency: "USD" },
      region: "us-central1",
    }),
}));
vi.mock("@/lib/queries/workspace", () => ({
  usePolicies: () => ok([]),
  useMembers: () => ok([]),
  useInvite: () => ({ mutate: vi.fn(), isPending: false }),
  useTokens: () => ok([]),
  useCreateToken: () => ({ mutate: vi.fn(), isPending: false }),
  useRevokeToken: () => ({ mutate: vi.fn() }),
}));

// Product copy never names a model vendor or its tools.
const VENDORS = /Gemini|Antigravity|model|provider|OpenAI|ChatGPT|GPT|Codex|Copilot/;

/** Every string in a message tree. */
const strings = (node: unknown): string[] =>
  typeof node === "string" ? [node] : node && typeof node === "object" ? Object.values(node).flatMap(strings) : [];

describe("the settings page", () => {
  it.each(["en", "ja"] as const)("names no model vendor anywhere on the page (%s)", async (lang) => {
    locale.current = lang;
    renderWithIntl(await SettingsPage(), { locale: lang });
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(VENDORS);
  });

  it("links to each section from the top of the page", async () => {
    locale.current = "en";
    renderWithIntl(await SettingsPage());
    const nav = screen.getByRole("navigation", { name: "On this page" });
    const hrefs = within(nav)
      .getAllByRole("link")
      .map((a) => [a.textContent, a.getAttribute("href")]);
    expect(hrefs).toEqual([
      ["Policies", "#policies"],
      ["Members", "#members"],
      ["Access for AI tools", "#ai-tools"],
      ["Workspace", "#workspace"],
    ]);
    for (const [, href] of hrefs) expect(document.querySelector(href!)).not.toBeNull();
  });

  it("keeps every settings message vendor-neutral, including dialogs not on screen", () => {
    for (const messages of [en, ja]) {
      const offenders = strings(messages.settings).filter((s) => VENDORS.test(s));
      expect(offenders).toEqual([]);
    }
  });
});
