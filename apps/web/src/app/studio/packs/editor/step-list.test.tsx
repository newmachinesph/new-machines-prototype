import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReactFlowProvider } from "@xyflow/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createEditorStore, EditorStoreContext } from "@/lib/builder/store";
import { OVERDUE, PALETTE } from "@/lib/builder/test-fixtures";
import { renderWithIntl } from "@/test/intl";
import { StepList } from "./step-list";
import { StepIssuesContext } from "./step-node";

const toast = vi.hoisted(() => vi.fn());
vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => toast,
}));

function renderList({ locale = "en", disabled }: { locale?: "en" | "ja"; disabled?: boolean } = {}) {
  const store = createEditorStore({ draft: OVERDUE, palette: PALETTE });
  renderWithIntl(
    <EditorStoreContext.Provider value={store}>
      <StepIssuesContext.Provider value={new Map([["review", 1]])}>
        <ReactFlowProvider>
          <StepList disabled={disabled} />
        </ReactFlowProvider>
      </StepIssuesContext.Provider>
    </EditorStoreContext.Provider>,
    { locale },
  );
  return store;
}

describe("StepList", () => {
  beforeEach(() => toast.mockReset());

  it("says what each step does, in reading order", () => {
    renderList();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("The run starts with the pack's input.");
    expect(items[2]).toHaveTextContent("Reads from Stripe: List invoices.");
    expect(items[8]).toHaveTextContent("Changes data in Gmail: Create draft.");
    expect(items.at(-1)).toHaveTextContent("Ends the run as failed.");
    expect(items[5]).toHaveTextContent("1 problem");
  });

  it("asks for a title when a review or approval has none, and ends a titled one once", () => {
    const store = renderList();
    act(() => {
      store.getState().updateStep("review", { config: { title: "Is the plan right?" } });
      store.getState().updateStep("approve", { config: {} });
    });
    const items = screen.getAllByRole("listitem");
    expect(items[5]).toHaveTextContent("A person reviews: Is the plan right?");
    expect(items[5]).not.toHaveTextContent("right?.");
    expect(items[7]).toHaveTextContent("Your team approves the next step. Give it a title.");
  });

  it("selects a step when its row is chosen", async () => {
    const store = renderList();
    await userEvent.click(screen.getByRole("button", { name: /^invoices/ }));
    expect(store.getState().selectedId).toBe("invoices");
  });

  it("adds a step after another, wired into its place", async () => {
    const store = renderList();
    await userEvent.click(screen.getByRole("button", { name: "Add a step after review" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Approval" }));
    const edges = store.getState().edges;
    expect(edges.find((e) => e.id === "review:resolved")?.target).toBe("approve_2");
    expect(edges.find((e) => e.id === "approve_2:granted")?.target).toBe("draft");
    expect(toast).not.toHaveBeenCalled();
  });

  it("says when the step that followed could not be wired after the new one", async () => {
    const store = renderList();
    await userEvent.click(screen.getByRole("button", { name: "Add a step after approve" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Check" }));
    expect(store.getState().edges.find((e) => e.id === "approve:granted")?.target).toBe("verify_2");
    expect(store.getState().edges.some((e) => e.target === "send")).toBe(false);
    expect(toast).toHaveBeenCalledWith(
      "The step that followed is no longer connected",
      "A step that changes data in an app must follow an approval's “granted” outcome.",
      "blocked",
    );
  });

  it("says that a new decision needs its rules before the path goes on", async () => {
    const store = renderList();
    await userEvent.click(screen.getByRole("button", { name: "Add a step after review" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Decision" }));
    expect(store.getState().edges.find((e) => e.id === "review:resolved")?.target).toBe("check_2");
    expect(toast).toHaveBeenCalledWith(
      "The step that followed is no longer connected",
      "Add the decision's rules, then choose where each goes.",
      "blocked",
    );
  });

  it("lets a member choose a row but not add a step", async () => {
    const store = renderList({ disabled: true });
    expect(screen.queryByRole("button", { name: /^Add a step after/ })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /^invoices/ }));
    expect(store.getState().selectedId).toBe("invoices");
  });

  it("speaks Japanese", () => {
    renderList({ locale: "ja" });
    expect(screen.getAllByRole("listitem")[2]).toHaveTextContent("Stripe: List invoices から読み取ります。");
  });
});
