import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { ApiError } from "@/lib/api/errors";
import { MemoryView } from "./memory-view";

const SPACES = [
  { key: "retail-commerce", name: "Retail & Commerce", description: "Facts about selling.", itemCount: 2, version: 1 },
  { key: "suppliers", name: "Suppliers", description: "Who supplies what.", itemCount: 0, version: 2 },
];
const ITEMS = [
  {
    id: "mem_2",
    space: "retail-commerce",
    text: "Refunds appear as negative charges.",
    source: "console",
    createdBy: "ops@newmachin.es",
    createdAt: "2026-10-13T09:00:00Z",
  },
  {
    id: "mem_1",
    space: "retail-commerce",
    text: "Amounts within 1 cent are rounding.",
    source: "seed",
    createdBy: "definitions",
    createdAt: "2026-10-13T08:00:00Z",
  },
];

const state = vi.hoisted(() => ({
  canWrite: true,
  space: null as string | null,
  setSpace: vi.fn(),
  spaces: {} as Record<string, unknown>,
  items: {} as Record<string, unknown>,
  add: vi.fn(),
  remove: vi.fn(),
}));

vi.mock("nuqs", () => ({
  parseAsString: {},
  useQueryState: () => [state.space, state.setSpace],
}));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => state.canWrite }));
vi.mock("@/lib/queries/memory", () => ({
  useMemorySpaces: () => state.spaces,
  useMemoryItems: (space: string | null) => (space ? state.items : { isPending: true }),
  useAddMemoryItem: () => ({ mutateAsync: state.add }),
  useDeleteMemoryItem: () => ({ mutateAsync: state.remove }),
}));

const ok = (data: unknown) => ({ isPending: false, isError: false, data });

const renderView = () =>
  render(
    <UiProviders>
      <MemoryView />
    </UiProviders>,
  );

describe("MemoryView", () => {
  beforeEach(() => {
    state.canWrite = true;
    state.space = null;
    state.setSpace.mockClear();
    state.spaces = ok(SPACES);
    state.items = ok(ITEMS);
    state.add.mockReset().mockResolvedValue(ITEMS[0]);
    state.remove.mockReset().mockResolvedValue(undefined);
  });

  it("shows the first space's items, newest first, with the space's definition", () => {
    renderView();
    expect(screen.getByRole("heading", { name: "Retail & Commerce" })).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Items in Retail & Commerce" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Refunds appear as negative charges.");
    expect(rows[1]).toHaveTextContent("Amounts within 1 cent are rounding.");
    expect(screen.getByRole("link", { name: /v1/ })).toHaveAttribute(
      "href",
      "/definitions/memory_space/retail-commerce",
    );
  });

  it("adds an item only with text and a reason", async () => {
    const user = userEvent.setup();
    renderView();
    await user.click(screen.getByRole("button", { name: "Add item" }));
    const dialog = await screen.findByRole("alertdialog");
    const confirm = within(dialog).getByRole("button", { name: "Add item" });
    expect(confirm).toBeDisabled();

    await user.type(within(dialog).getByLabelText("Item"), "Orders ship within two days.");
    await user.click(confirm);
    expect(await within(dialog).findByText(/Give a reason/)).toBeInTheDocument();
    expect(state.add).not.toHaveBeenCalled();

    await user.type(within(dialog).getByLabelText("Reason"), "Shipping policy changed");
    await user.click(confirm);
    await waitFor(() =>
      expect(state.add).toHaveBeenCalledWith({
        path: { space: "retail-commerce" },
        body: { text: "Orders ship within two days.", reason: "Shipping policy changed" },
      }),
    );
  });

  it("deletes an item with a reason", async () => {
    const user = userEvent.setup();
    renderView();
    await user.click(screen.getByRole("button", { name: "Delete: Refunds appear as negative charges." }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Reason"), "Out of date");
    await user.click(within(dialog).getByRole("button", { name: "Delete item" }));
    await waitFor(() =>
      expect(state.remove).toHaveBeenCalledWith({ path: { item_id: "mem_2" }, body: { reason: "Out of date" } }),
    );
  });

  it("keeps support read-only: no adding or deleting", () => {
    state.canWrite = false;
    renderView();
    expect(screen.getByRole("button", { name: "Add item" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete: Refunds appear as negative charges." })).toBeDisabled();
  });

  it("explains that memory needs the local runtime when it is off", () => {
    state.spaces = { isPending: false, isError: true, error: new ApiError(503, "RUNTIME_UNAVAILABLE", "Off.") };
    renderView();
    expect(screen.getByText("Memory spaces need the local runtime (Postgres). See README.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add item" })).toBeNull();
  });

  it("clears a space in the URL that does not exist", () => {
    state.space = "nope";
    renderView();
    expect(state.setSpace).toHaveBeenCalledWith(null);
  });
});
