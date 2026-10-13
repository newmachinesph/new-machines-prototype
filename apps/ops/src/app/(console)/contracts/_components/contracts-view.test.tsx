import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import type { DefinitionDetail } from "@/lib/api/gen/types.gen";
import { budgetText, ContractsView } from "./contracts-view";

const contract = (key: string, body: Record<string, unknown>): DefinitionDetail => ({
  summary: {
    kind: "contract",
    key,
    name: key,
    version: 3,
    digest: "d",
    source: "console",
    publishedBy: "ops@newmachin.es",
    publishedAt: "2026-10-13T09:00:00Z",
  },
  versions: [],
  yaml: "",
  files: {},
  body,
  refs: [],
  usedBy: [],
});

const state = vi.hoisted(() => ({ result: {} as Record<string, unknown> }));
vi.mock("@/lib/queries/definitions", () => ({ useDefinitionsOfKind: () => state.result }));
const ok = (data: unknown) => ({ isPending: false, isError: false, data });

describe("ContractsView", () => {
  beforeEach(() => {
    const recon = contract("order-payment-reconciliation", {
      capability: "reconciliation.order_payment",
      budget: { currency: "USD", maximum_minor: 2500, human_budget_minor: 2000 },
      limits: { max_attempts: 3, deadline_s: 172800 },
      authorization: { tool_capabilities: ["orders.read", "payments.read", "sheets.write"] },
    });
    const bare = contract("bare", {});
    state.result = { list: ok([recon.summary, bare.summary]), details: [ok(recon), ok(bare)] };
  });

  it("shows budget, limits, capabilities and version, linked to the editor", () => {
    render(<ContractsView />);
    const table = screen.getByRole("table", { name: "Work contracts" });
    const link = within(table).getByRole("link", { name: /order-payment-reconciliation/ });
    expect(link).toHaveAttribute("href", "/definitions/contract/order-payment-reconciliation");
    const row = link.closest("tr")!;
    expect(within(row).getByText("$25.00")).toBeInTheDocument();
    expect(row).toHaveTextContent("$20.00 for people");
    expect(within(row).getByText(/3 attempts/)).toBeInTheDocument();
    expect(within(row).getByText(/2 days/)).toBeInTheDocument();
    expect(within(row).getByText("orders.read, payments.read, sheets.write")).toBeInTheDocument();
    expect(within(row).getByText("v3")).toBeInTheDocument();
  });

  it("copes with a contract that leaves fields out", () => {
    render(<ContractsView />);
    const row = screen.getByRole("link", { name: /bare/ }).closest("tr")!;
    expect(within(row).getAllByText("Not set").length).toBeGreaterThan(0);
  });

  it("explains that contracts need the local runtime when it is off", () => {
    state.result = {
      list: { isPending: false, isError: true, error: new ApiError(503, "RUNTIME_UNAVAILABLE", "Off.") },
      details: [],
    };
    render(<ContractsView />);
    expect(screen.getByText("Work contracts need the local runtime (Postgres). See README.")).toBeInTheDocument();
  });
});

describe("budgetText", () => {
  it("uses the currency's own decimals", () => {
    expect(budgetText({ minor: 2500, currency: "USD" })).toBe("$25.00");
    expect(budgetText({ minor: 2500, currency: "JPY" })).toBe("¥2,500");
  });
});
