import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import type { Agent } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { AgentPage } from "./agent-page";

const nav = vi.hoisted(() => ({
  notFound: vi.fn(() => Object.assign(new Error("NEXT_NOT_FOUND"), { notFound: true })),
}));
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw nav.notFound();
  },
}));

const state = vi.hoisted(() => ({ result: {} as Record<string, unknown> }));
vi.mock("@/lib/queries/catalog", () => ({ useAgent: () => state.result }));
const ok = (data: unknown) => ({ isPending: false, isError: false, data });

const finance: Agent = {
  id: "finance-agent",
  version: "1.0.0",
  name: "Finance Agent",
  publisher: "New Machines Labs",
  summary: "Matches each order to the payment that settled it.",
  capabilities: ["finance.reconcile"],
  regions: ["asia-south1"],
  certified: true,
  skills: [
    { key: "match-orders", title: "Match orders" },
    { key: "explain-mismatch", title: "Explain mismatch" },
  ],
  tools: ["shopify.list_orders"],
  modelProfile: "reasoning",
  usedBy: [{ slug: "order-payment-reconciliation", name: "Order & Payment Reconciliation" }],
  source: "definition",
};

describe("AgentPage", () => {
  beforeEach(() => {
    state.result = ok(finance);
    nav.notFound.mockClear();
  });

  it("shows the summary, capabilities, skills, tools, model profile and regions", () => {
    renderWithIntl(<AgentPage id="finance-agent" />);
    expect(screen.getByRole("heading", { level: 1, name: "Finance Agent" })).toBeInTheDocument();
    expect(screen.getByText("Matches each order to the payment that settled it.")).toBeInTheDocument();
    expect(screen.getByText("New Machines Labs, version 1.0.0")).toBeInTheDocument();
    expect(screen.getByText("Payment reconciliation")).toBeInTheDocument();
    expect(screen.getByText("Match orders")).toBeInTheDocument();
    expect(screen.getByText("Explain mismatch")).toBeInTheDocument();
    expect(screen.getByText("shopify.list_orders")).toBeInTheDocument();
    expect(screen.getByText("Reasoning model")).toBeInTheDocument();
    // The region reads as Settings shows it, place first.
    expect(screen.getByText("Mumbai (asia-south1)")).toBeInTheDocument();
    expect(screen.queryByText("Sample")).not.toBeInTheDocument();
  });

  it("keeps the capability ids behind a Technical details disclosure", () => {
    renderWithIntl(<AgentPage id="finance-agent" />);
    const details = screen.getByText("Technical details").closest("details")!;
    expect(details).not.toHaveAttribute("open");
    expect(within(details).getByText("finance.reconcile")).toBeInTheDocument();
    const capabilities = screen.getByRole("heading", { name: "Capabilities" }).closest("section")!;
    expect(within(capabilities).getByText("Payment reconciliation").closest("details")).toBeNull();
  });

  it("links each pack that uses it to the marketplace", () => {
    renderWithIntl(<AgentPage id="finance-agent" />);
    const usedIn = screen.getByRole("heading", { name: "Used in" }).closest("section")!;
    expect(within(usedIn).getByRole("link", { name: /Order & Payment Reconciliation/ })).toHaveAttribute(
      "href",
      "/app/marketplace/order-payment-reconciliation",
    );
  });

  it("says when no pack uses it, it has no tools and the profile is unknown, and tags a sample", () => {
    state.result = ok({ ...finance, tools: [], usedBy: [], skills: [], modelProfile: undefined, source: "sample" });
    renderWithIntl(<AgentPage id="agent_finance" />);
    expect(screen.getByText("No Workflow Pack uses this agent yet.")).toBeInTheDocument();
    expect(screen.getByText("None. It works only from the data the pack gives it.")).toBeInTheDocument();
    expect(screen.getByText("No skills listed.")).toBeInTheDocument();
    expect(screen.getByText("Not stated")).toBeInTheDocument();
    expect(screen.getByText("Sample")).toBeInTheDocument();
  });

  it("never names a model vendor", () => {
    renderWithIntl(<AgentPage id="finance-agent" />);
    expect(document.body.textContent).not.toMatch(/openai|gemini|vertex/i);
  });

  it("shows a skeleton while loading", () => {
    state.result = { isPending: true, isError: false, data: undefined };
    renderWithIntl(<AgentPage id="finance-agent" />);
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
  });

  it("is a 404 for an unknown agent", () => {
    state.result = { isPending: false, isError: true, data: undefined, error: new ApiError(404, "NOT_FOUND", "No.") };
    expect(() => renderWithIntl(<AgentPage id="nope" />)).toThrow("NEXT_NOT_FOUND");
    expect(nav.notFound).toHaveBeenCalled();
  });

  it("labels the fast profile in Japanese", () => {
    state.result = ok({ ...finance, modelProfile: "fast" });
    renderWithIntl(<AgentPage id="finance-agent" />, { locale: "ja" });
    expect(screen.getByText("高速モデル")).toBeInTheDocument();
  });

  it("names our agent's skills and capabilities in Japanese, keeping the ids behind the disclosure", () => {
    renderWithIntl(<AgentPage id="finance-agent" />, { locale: "ja" });
    const skills = screen.getByRole("heading", { name: "スキル" }).closest("section")!;
    expect(within(skills).getByText("注文の突き合わせ")).toBeInTheDocument();
    expect(within(skills).getByText("不一致の説明")).toBeInTheDocument();
    expect(screen.queryByText("Match orders")).toBeNull();
    expect(screen.getByText("入金の照合")).toBeInTheDocument();
    expect(screen.getByText("finance.reconcile").closest("details")).not.toBeNull();
  });

  it("keeps a team agent's skill titles as it wrote them", () => {
    state.result = ok({ ...finance, id: "org-5c81-helper", certified: false, publisher: "Acme Labs" });
    renderWithIntl(<AgentPage id="org-5c81-helper" />, { locale: "ja" });
    expect(screen.getByText("Match orders")).toBeInTheDocument();
  });

  it("names a listed agent's publisher once, with its fee", () => {
    state.result = ok({
      ...finance,
      publisher: "Harbor Cafe",
      version: "2",
      certified: false,
      listing: {
        listingId: "lst_1",
        publisher: "Harbor Cafe",
        fee: { amountMinor: 30, currency: "USD" },
        feeUnit: "call",
        version: 2,
      },
    });
    renderWithIntl(<AgentPage id="finance-agent" />);
    expect(screen.getByText("Version 2")).toBeInTheDocument();
    expect(screen.getAllByText(/Harbor Cafe/)).toHaveLength(1);
  });
});
