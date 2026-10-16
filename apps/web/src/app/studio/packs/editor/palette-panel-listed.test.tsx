import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactFlowProvider } from "@xyflow/react";
import { describe, expect, it } from "vitest";
import type { Palette } from "@/lib/api/gen/types.gen";
import { createEditorStore, EditorStoreContext } from "@/lib/builder/store";
import { OVERDUE, PALETTE } from "@/lib/builder/test-fixtures";
import { renderWithIntl } from "@/test/intl";
import { PalettePanel } from "./palette-panel";

const LISTED: Palette = {
  ...PALETTE,
  agents: [
    ...PALETTE.agents,
    {
      key: "acme--dunning-agent",
      name: "Dunning agent",
      summary: "Writes polite payment nudges.",
      modelProfile: "fast",
      outputSchemaRef: "shared/agent-result",
      listing: {
        listingId: "lst_1",
        publisher: "Acme Labs",
        fee: { amountMinor: 25, currency: "USD" },
        feeUnit: "run",
        version: 2,
      },
    },
  ],
};

function renderPalette() {
  const store = createEditorStore({ draft: OVERDUE, palette: LISTED });
  renderWithIntl(
    <EditorStoreContext.Provider value={store}>
      <ReactFlowProvider>
        <PalettePanel />
      </ReactFlowProvider>
    </EditorStoreContext.Provider>,
  );
}

describe("PalettePanel listed agents", () => {
  it("groups a listed agent after platform and team agents with its publisher and fee", () => {
    renderPalette();
    const heading = screen.getByRole("heading", { name: "From other workspaces" });
    const section = heading.closest("section") as HTMLElement;
    const listed = within(section).getByRole("button", { name: /Dunning agent/ });
    expect(listed).toHaveTextContent("By Acme Labs · $0.25 per run");
    expect(screen.getByRole("button", { name: /Collections Agent/ }).closest("section")).not.toBe(section);
    expect(screen.getByRole("button", { name: /Invoice helper/ }).closest("section")).not.toBe(section);
    const agentsHeading = screen.getByRole("heading", { name: "Agents" });
    expect(agentsHeading.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("explains the fee to a keyboard user who focuses the agent", async () => {
    renderPalette();
    const listed = screen.getByRole("button", { name: /Dunning agent/ });
    await userEvent.tab();
    listed.focus();
    expect(listed).toHaveFocus();
    expect(listed).toHaveAccessibleDescription("Each call to this agent adds its fee to the run's cost.");
  });
});
