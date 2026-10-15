import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactFlowProvider } from "@xyflow/react";
import { describe, expect, it, vi } from "vitest";
import { createEditorStore, EditorStoreContext } from "@/lib/builder/store";
import { OVERDUE, PALETTE } from "@/lib/builder/test-fixtures";
import { renderWithIntl } from "@/test/intl";
import { STEP_MIME } from "./editor-canvas";
import { PalettePanel } from "./palette-panel";

function renderPalette(disabled?: boolean) {
  const store = createEditorStore({ draft: OVERDUE, palette: PALETTE });
  renderWithIntl(
    <EditorStoreContext.Provider value={store}>
      <ReactFlowProvider>
        <PalettePanel disabled={disabled} />
      </ReactFlowProvider>
    </EditorStoreContext.Provider>,
  );
  return store;
}

describe("PalettePanel", () => {
  it("labels steps that change data and steps built by the team, and disables tools a pack may not use", () => {
    renderPalette();
    expect(screen.getByRole("button", { name: /Gmail: Create draft.*Changes data/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Invoice helper.*Built by your team/ })).toBeEnabled();
    const refund = screen.getByRole("button", { name: /Stripe: Refund charge/ });
    expect(refund).toBeDisabled();
    expect(refund).toHaveAccessibleDescription("Packs cannot use tools that delete records or move money.");
    expect(screen.getByText("Packs cannot use tools that delete records or move money.")).not.toBe(refund);
  });

  it("finds entries by name", async () => {
    renderPalette();
    await userEvent.type(screen.getByLabelText("Find a step"), "invoice");
    expect(screen.getByRole("button", { name: /Stripe: List invoices/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Invoice helper/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Gmail: Create draft/ })).toBeNull();
  });

  it("adds a step on click, and carries it when dragged", async () => {
    const store = renderPalette();
    await userEvent.click(screen.getByRole("button", { name: /^Approval/ }));
    expect(store.getState().nodes.some((n) => n.id === "approve_2")).toBe(true);
    const setData = vi.fn();
    fireEvent.dragStart(screen.getByRole("button", { name: /Gmail: Create draft/ }), {
      dataTransfer: { setData, effectAllowed: "" },
    });
    expect(setData).toHaveBeenCalledWith(
      STEP_MIME,
      JSON.stringify({ type: "connector", config: { tool: "gmail.create_draft", args: {} } }),
    );
  });

  it("neither adds nor carries a step when disabled", async () => {
    const store = renderPalette(true);
    const approval = screen.getByRole("button", { name: /^Approval/ });
    expect(approval).toBeDisabled();
    expect(approval).not.toHaveAttribute("draggable", "true");
    await userEvent.click(approval);
    expect(store.getState().nodes.some((n) => n.id === "approve_2")).toBe(false);
    const setData = vi.fn();
    fireEvent.dragStart(approval, { dataTransfer: { setData, effectAllowed: "" } });
    expect(setData).not.toHaveBeenCalled();
  });
});
