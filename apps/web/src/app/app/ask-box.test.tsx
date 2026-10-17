import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { AskBox } from "./ask-box";

const mutate = vi.fn();
const suggestion = vi.hoisted(() => ({ data: undefined as unknown }));
vi.mock("@/lib/queries/catalog", () => ({
  useSuggestPack: () => ({ mutate, reset: vi.fn(), isPending: false, data: suggestion.data }),
}));
vi.mock("@/components/base", () => ({ useToast: () => vi.fn() }));
const workspace = vi.hoisted(() => ({ kind: "demo" as "demo" | "live" | undefined }));
vi.mock("@/lib/queries/me", () => ({
  useMe: () => ({ data: workspace.kind ? { workspace: workspace.kind } : undefined }),
}));

const ENGLISH_QUERY = "Match last week's orders to Stripe payouts";

describe("AskBox suggestion chips", () => {
  beforeEach(() => {
    mutate.mockClear();
    suggestion.data = undefined;
    workspace.kind = "demo";
  });

  it("offers all five starters as buttons, each a comfortable tap target", () => {
    renderWithIntl(<AskBox />);
    const chips = screen.getAllByRole("button");
    expect(chips).toHaveLength(5);
    for (const chip of chips) expect(chip).toHaveClass("min-h-9");
  });

  it("offers the live marketplace's packs in a live workspace, not the demo's", () => {
    workspace.kind = "live";
    renderWithIntl(<AskBox />);
    const names = screen.getAllByRole("button").map((b) => b.textContent);
    expect(names).toContain("Sort last week's expenses and flag anything unusual");
    expect(names).toContain("Draft follow-ups for yesterday's meetings");
    expect(names).not.toContain("Tell me what to reorder every Monday");
    expect(names).not.toContain("Translate our catalog for a Japanese store");
  });

  it("shows only the shared starters until /me says which workspace this is", () => {
    workspace.kind = undefined;
    renderWithIntl(<AskBox />);
    expect(screen.getAllByRole("button")).toHaveLength(3);
  });

  it("keeps the placeholder short on a phone, where the full one with its example is cut off", () => {
    // jsdom has no matchMedia, which reads as wide; here the window is narrower than sm.
    window.matchMedia = vi.fn((query: string) => ({
      matches: !query.includes("min-width"),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })) as never;
    try {
      renderWithIntl(<AskBox />);
      expect(screen.getByRole("textbox")).toHaveAttribute("placeholder", "Describe the outcome you want");
    } finally {
      // @ts-expect-error jsdom defines none; back to that.
      delete window.matchMedia;
    }
  });

  it("gives the full placeholder, with its example, from sm up", () => {
    renderWithIntl(<AskBox />);
    expect(screen.getByRole("textbox")).toHaveAttribute("placeholder", expect.stringContaining("for example"));
  });

  it("sends the same English query from a chip and from the button, in Japanese", async () => {
    renderWithIntl(<AskBox />, { locale: "ja" });
    await userEvent.click(screen.getByRole("button", { name: "先週の注文をStripeの入金と突き合わせる" }));
    expect(mutate.mock.calls[0][0]).toEqual({ body: { text: ENGLISH_QUERY } });

    await userEvent.click(screen.getByRole("button", { name: "パックを提案" }));
    expect(mutate.mock.calls[1][0]).toEqual({ body: { text: ENGLISH_QUERY } });
  });

  it("sends what the person typed once they edit a chip's text", async () => {
    renderWithIntl(<AskBox />, { locale: "ja" });
    await userEvent.click(screen.getByRole("button", { name: "先週の注文をStripeの入金と突き合わせる" }));
    await userEvent.type(screen.getByRole("textbox"), "です");
    await userEvent.click(screen.getByRole("button", { name: "パックを提案" }));
    expect(mutate.mock.calls[1][0].body.text).toBe("先週の注文をStripeの入金と突き合わせるです");
  });
});

describe("AskBox suggested pack", () => {
  const suggest = (slug: string, installed: boolean) => {
    suggestion.data = { pack: { slug, name: "Some pack", installed }, steps: ["Step one"], simulated: true };
  };
  beforeEach(() => {
    suggestion.data = undefined;
  });

  it("starts a run of an added pack", () => {
    suggest("order-payment-reconciliation", true);
    renderWithIntl(<AskBox />);
    expect(screen.getByRole("link", { name: "Start this run" })).toHaveAttribute(
      "href",
      "/app/runs/new?pack=order-payment-reconciliation",
    );
    expect(screen.queryByRole("link", { name: "Add this pack" })).not.toBeInTheDocument();
  });

  it("sends a pack that isn't added to its marketplace page instead", () => {
    suggest("catalog-localization-en-ja", false);
    renderWithIntl(<AskBox />);
    expect(screen.getByRole("link", { name: "Add this pack" })).toHaveAttribute(
      "href",
      "/app/marketplace/catalog-localization-en-ja",
    );
    expect(screen.queryByRole("link", { name: "Start this run" })).not.toBeInTheDocument();
  });

  it("labels the add link in Japanese", () => {
    suggest("catalog-localization-en-ja", false);
    renderWithIntl(<AskBox />, { locale: "ja" });
    expect(screen.getByRole("link", { name: "このパックを追加" })).toBeInTheDocument();
  });
});
