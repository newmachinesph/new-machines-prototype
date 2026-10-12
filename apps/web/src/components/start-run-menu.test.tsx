import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { StartRunMenu } from "./shell";

vi.mock("@/lib/auth/session", () => ({ useSession: () => ({ user: null, signOut: vi.fn() }) }));
vi.mock("@/lib/queries/catalog", () => ({
  usePackName: () => undefined,
  usePacks: () => ({
    data: [
      { slug: "order-payment-reconciliation", name: "Order & Payment Reconciliation", installed: true },
      { slug: "chargeback-evidence", name: "Chargeback Evidence", installed: true },
      { slug: "catalog-localization-en-ja", name: "Catalog Localization", installed: false },
    ],
  }),
}));

describe("StartRunMenu", () => {
  it("lists every hired pack from the API, and only hired packs", async () => {
    renderWithIntl(<StartRunMenu />);
    await userEvent.click(screen.getByRole("button", { name: "Start a run" }));
    expect(await screen.findByRole("menuitem", { name: "Chargeback Evidence" })).toHaveAttribute(
      "href",
      "/app/runs/new?pack=chargeback-evidence",
    );
    expect(screen.getByRole("menuitem", { name: "Order & Payment Reconciliation" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "Catalog Localization" })).not.toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Hire another pack" })).toHaveAttribute("href", "/app/marketplace");
  });

  it("keeps the menu's Japanese labels", async () => {
    renderWithIntl(<StartRunMenu />, { locale: "ja" });
    await userEvent.click(screen.getByRole("button", { name: "実行を開始" }));
    expect(await screen.findByText("採用済みのパックを選択")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "別のパックを採用" })).toBeInTheDocument();
  });
});
