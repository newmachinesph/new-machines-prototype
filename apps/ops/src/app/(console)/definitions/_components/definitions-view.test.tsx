import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { ApiError } from "@/lib/api/errors";
import type { DefinitionSummary } from "@/lib/api/gen/types.gen";
import { DefinitionsView } from "./definitions-view";

const row = (kind: DefinitionSummary["kind"], key: string, name = key): DefinitionSummary => ({
  kind,
  key,
  name,
  version: 2,
  digest: "abc",
  source: "console",
  publishedBy: "ops@newmachin.es",
  publishedAt: "2026-10-13T09:00:00Z",
});

const ROWS = [
  row("agent", "finance-agent", "Finance agent"),
  row("agent", "ops-agent", "Ops agent"),
  row("connector", "stripe", "Stripe"),
  row("schema", "order-payment-reconciliation/input"),
];

const state = vi.hoisted(() => ({
  canWrite: true,
  kind: null as string | null,
  action: null as string | null,
  setKind: vi.fn(),
  setAction: vi.fn(),
  push: vi.fn(),
  query: {} as Record<string, unknown>,
}));

vi.mock("nuqs", () => ({
  parseAsStringLiteral: () => ({}),
  useQueryState: (key: string) => (key === "kind" ? [state.kind, state.setKind] : [state.action, state.setAction]),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: state.push }) }));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => state.canWrite, useMe: () => ({ isSuccess: true }) }));
vi.mock("@/lib/queries/definitions", () => ({ useDefinitions: () => state.query }));

const renderView = () =>
  render(
    <UiProviders>
      <DefinitionsView />
    </UiProviders>,
  );

describe("DefinitionsView", () => {
  beforeEach(() => {
    state.canWrite = true;
    state.kind = null;
    state.action = null;
    state.setAction.mockClear();
    state.push.mockClear();
    state.query = { isPending: false, isError: false, data: ROWS };
  });

  it("lists every definition with its version, linked to its editor", () => {
    renderView();
    const table = screen.getByRole("table", { name: "Definitions" });
    expect(within(table).getByRole("link", { name: /Finance agent/ })).toHaveAttribute(
      "href",
      "/definitions/agent/finance-agent",
    );
    expect(within(table).getByRole("link", { name: /order-payment-reconciliation\/input/ })).toHaveAttribute(
      "href",
      "/definitions/schema/order-payment-reconciliation/input",
    );
    expect(within(table).getAllByText("v2")).toHaveLength(4);
  });

  it("filters by kind", () => {
    state.kind = "agent";
    renderView();
    const table = screen.getByRole("table", { name: "Agent definitions" });
    expect(within(table).queryByText("Stripe")).toBeNull();
    expect(within(table).getByText("Ops agent")).toBeInTheDocument();
  });

  it("explains that definitions need the local runtime when it is off", () => {
    state.query = {
      isPending: false,
      isError: true,
      error: new ApiError(503, "RUNTIME_UNAVAILABLE", "The runtime is off."),
    };
    renderView();
    expect(screen.getByText("Definitions need the local runtime (Postgres). See README.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("disables New definition for support and clears a ?action=new link", () => {
    state.canWrite = false;
    state.action = "new";
    renderView();
    expect(screen.getByRole("button", { name: "New definition" })).toBeDisabled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(state.setAction).toHaveBeenCalledWith(null);
  });

  it("opens the editor for a new key, copied from an existing definition of the same kind", async () => {
    const user = userEvent.setup();
    state.action = "new";
    renderView();
    const dialog = await screen.findByRole("dialog");
    // Agent is the first creatable kind with definitions, so it is chosen with its first key to copy.
    await user.type(within(dialog).getByLabelText("Key"), "billing-agent");
    await user.click(within(dialog).getByRole("button", { name: "Open editor" }));
    await waitFor(() => expect(state.push).toHaveBeenCalledWith("/definitions/agent/billing-agent?from=finance-agent"));
  });

  it("preselects the kind the list is filtered to, as the agents page's New agent link asks", async () => {
    const user = userEvent.setup();
    state.query = { isPending: false, isError: false, data: [row("pack", "month-end-close"), ...ROWS] };
    state.kind = "agent";
    state.action = "new";
    renderView();
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Key"), "billing-agent");
    await user.click(within(dialog).getByRole("button", { name: "Open editor" }));
    await waitFor(() => expect(state.push).toHaveBeenCalledWith("/definitions/agent/billing-agent?from=finance-agent"));
  });

  it("starts from the first creatable kind without a filter", async () => {
    const user = userEvent.setup();
    state.query = { isPending: false, isError: false, data: [row("pack", "month-end-close"), ...ROWS] };
    state.action = "new";
    renderView();
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Key"), "new-pack");
    await user.click(within(dialog).getByRole("button", { name: "Open editor" }));
    await waitFor(() => expect(state.push).toHaveBeenCalledWith("/definitions/pack/new-pack?from=month-end-close"));
  });

  it("refuses a key that already exists or breaks the key rule", async () => {
    const user = userEvent.setup();
    state.action = "new";
    renderView();
    const dialog = await screen.findByRole("dialog");
    const key = within(dialog).getByLabelText("Key");
    await user.type(key, "ops-agent");
    await user.click(within(dialog).getByRole("button", { name: "Open editor" }));
    expect(await within(dialog).findByText(/already exists/)).toBeInTheDocument();
    await user.clear(key);
    await user.type(key, "Ops Agent");
    await user.click(within(dialog).getByRole("button", { name: "Open editor" }));
    expect(await within(dialog).findByText(/lowercase letters/)).toBeInTheDocument();
    expect(state.push).not.toHaveBeenCalled();
  });
});
