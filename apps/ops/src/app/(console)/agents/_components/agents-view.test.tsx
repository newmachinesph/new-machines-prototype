import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { ApiError } from "@/lib/api/errors";
import type { DefinitionDetail, DefinitionRef } from "@/lib/api/gen/types.gen";
import { AgentsView } from "./agents-view";

const agent = (
  key: string,
  runtime: Record<string, unknown>,
  version = 1,
  usedBy: DefinitionRef[] = [],
): DefinitionDetail => ({
  summary: {
    kind: "agent",
    key,
    name: key,
    version,
    digest: "d",
    source: "file",
    publishedBy: "definitions",
    publishedAt: "2026-10-13T09:00:00Z",
  },
  versions: [],
  yaml: "",
  files: {},
  body: { capabilities: ["finance.reconcile"], runtime },
  refs: [],
  usedBy,
});

const state = vi.hoisted(() => ({ result: {} as Record<string, unknown>, canWrite: true }));
vi.mock("@/lib/queries/definitions", () => ({ useDefinitionsOfKind: () => state.result }));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => state.canWrite }));

const renderView = () =>
  render(
    <UiProviders>
      <AgentsView />
    </UiProviders>,
  );

const ok = (data: unknown) => ({ isPending: false, isError: false, data });

describe("AgentsView", () => {
  beforeEach(() => {
    const finance = agent(
      "finance-agent",
      {
        model_profile: "reasoning",
        skills: ["skills/match-orders.md", "skills/explain-mismatch.md"],
        tools: [],
        max_turns: 6,
      },
      2,
      [
        { kind: "workflow", key: "order-payment-reconciliation" },
        { kind: "pack", key: "order-payment-reconciliation" },
        { kind: "pack", key: "month-end-close" },
      ],
    );
    const retail = agent("retail-agent", { model_profile: "fast", tools: ["shopify.list_orders"], skills: [] });
    state.result = { list: ok([finance.summary, retail.summary]), details: [ok(finance), ok(retail)] };
    state.canWrite = true;
  });

  it("shows each agent's model profile, tools, skills and version, linked to its editor", () => {
    renderView();
    const table = screen.getByRole("table", { name: "Agents" });
    const finance = within(table)
      .getByRole("link", { name: /finance-agent/ })
      .closest("tr")!;
    expect(within(finance).getByText("reasoning")).toBeInTheDocument();
    expect(within(finance).getByText("match-orders, explain-mismatch")).toBeInTheDocument();
    expect(within(finance).getByText("None")).toBeInTheDocument();
    expect(within(finance).getByText("v2")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: /finance-agent/ })).toHaveAttribute(
      "href",
      "/definitions/agent/finance-agent",
    );
    const retail = within(table)
      .getByRole("link", { name: /retail-agent/ })
      .closest("tr")!;
    expect(within(retail).getByText("shopify.list_orders")).toBeInTheDocument();
  });

  it("shows the packs that use each agent, linked to their pack definitions", () => {
    renderView();
    const table = screen.getByRole("table", { name: "Agents" });
    const finance = within(table)
      .getByRole("link", { name: /finance-agent/ })
      .closest("tr")!;
    expect(within(finance).getByRole("link", { name: "order-payment-reconciliation" })).toHaveAttribute(
      "href",
      "/definitions/pack/order-payment-reconciliation",
    );
    expect(within(finance).getByRole("link", { name: "month-end-close" })).toHaveAttribute(
      "href",
      "/definitions/pack/month-end-close",
    );
    const retail = within(table)
      .getByRole("link", { name: /retail-agent/ })
      .closest("tr")!;
    expect(within(retail).getByText("No pack")).toBeInTheDocument();
  });

  it("opens the new-definition flow preselected to an agent", () => {
    renderView();
    expect(screen.getByRole("link", { name: "New agent" })).toHaveAttribute(
      "href",
      "/definitions?kind=agent&action=new",
    );
  });

  it("does not offer New agent to support", () => {
    state.canWrite = false;
    renderView();
    expect(screen.queryByRole("link", { name: "New agent" })).toBeNull();
    expect(screen.getByRole("button", { name: "New agent" })).toBeDisabled();
  });

  it("never names the model vendor, only the profile", () => {
    renderView();
    expect(document.body.textContent).not.toMatch(/claude|anthropic/i);
  });

  it("explains that agents need the local runtime when it is off", () => {
    state.result = {
      list: { isPending: false, isError: true, error: new ApiError(503, "RUNTIME_UNAVAILABLE", "Off.") },
      details: [],
    };
    renderView();
    expect(screen.getByText("Agents need the local runtime (Postgres). See README.")).toBeInTheDocument();
  });
});
