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

const ENGLISH_QUERY = "Match last week's orders to Stripe payouts";

describe("AskBox suggestion chips", () => {
  beforeEach(() => {
    mutate.mockClear();
    suggestion.data = undefined;
  });

  it("offers all five starters as buttons, each a comfortable tap target", () => {
    renderWithIntl(<AskBox />);
    const chips = screen.getAllByRole("button");
    expect(chips).toHaveLength(5);
    for (const chip of chips) expect(chip).toHaveClass("min-h-9");
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
