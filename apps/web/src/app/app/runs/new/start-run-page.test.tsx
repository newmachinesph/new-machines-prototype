import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { StartRunPage } from "./start-run-page";

const url = vi.hoisted(() => ({ pack: null as string | null }));
vi.mock("nuqs", () => ({ useQueryState: () => [url.pack] }));

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
vi.mock("@/lib/queries/catalog", () => ({
  usePacks: () =>
    ok([
      { slug: "order-payment-reconciliation", name: "Order & Payment Reconciliation", installed: true, connectors: [] },
      { slug: "catalog-localization-en-ja", name: "Catalog Localization", installed: false, connectors: [] },
    ]),
}));
vi.mock("@/lib/queries/org", () => ({ useConnections: () => ok([]) }));
// The form itself is covered by start-run-form.test.tsx; here only what it is given matters.
vi.mock("./start-run-form", () => ({
  StartRunForm: ({ packs, defaultPack }: { packs: { slug: string }[]; defaultPack?: string }) => (
    <p>
      form with {packs.map((p) => p.slug).join(" ")}, preselecting {defaultPack ?? "nothing"}
    </p>
  ),
}));

describe("StartRunPage", () => {
  beforeEach(() => {
    url.pack = null;
  });

  it("preselects a hired pack from the link without a notice", () => {
    url.pack = "order-payment-reconciliation";
    renderWithIntl(<StartRunPage />);
    expect(screen.getByText(/preselecting order-payment-reconciliation/)).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("explains a pack that isn't hired and links to its marketplace page", () => {
    url.pack = "catalog-localization-en-ja";
    renderWithIntl(<StartRunPage />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Catalog Localization isn't hired yet, so it can't start a run.",
    );
    expect(screen.getByRole("link", { name: "Hire this pack" })).toHaveAttribute(
      "href",
      "/app/marketplace/catalog-localization-en-ja",
    );
    expect(screen.getByText(/form with order-payment-reconciliation, preselecting nothing/)).toBeInTheDocument();
  });

  it("explains an unknown pack and links to the marketplace", () => {
    url.pack = "no-such-pack";
    renderWithIntl(<StartRunPage />);
    expect(screen.getByRole("status")).toHaveTextContent("There is no pack called no-such-pack.");
    expect(screen.getByRole("link", { name: "See all packs" })).toHaveAttribute("href", "/app/marketplace");
  });

  it("shows the notice in Japanese", () => {
    url.pack = "catalog-localization-en-ja";
    renderWithIntl(<StartRunPage />, { locale: "ja" });
    expect(screen.getByRole("status")).toHaveTextContent("Catalog Localizationはまだ採用されていないため");
    expect(screen.getByRole("link", { name: "このパックを採用" })).toBeInTheDocument();
  });
});
