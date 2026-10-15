import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { createEditorStore, EditorStoreContext } from "@/lib/builder/store";
import { OVERDUE, PALETTE } from "@/lib/builder/test-fixtures";
import { renderWithIntl } from "@/test/intl";
import { YamlDialog } from "./yaml-dialog";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data, error: null });
const mocks = vi.hoisted(() => ({
  importer: { mutate: vi.fn(), isPending: false },
  toast: vi.fn(),
  workflow: { isPending: false, isError: false, data: undefined, error: null } as Record<string, unknown>,
}));
vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => mocks.toast,
}));
vi.mock("@/lib/queries/me", () => ({ useOrgId: () => "org_a1" }));
vi.mock("@/lib/queries/studio", () => ({
  useStudioPackWorkflow: () => mocks.workflow,
  useImportStudioWorkflow: () => mocks.importer,
}));

function renderDialog(packKey?: string, props: { readOnly?: boolean; onImported?: (issues: unknown[]) => void } = {}) {
  const store = createEditorStore({ draft: OVERDUE, palette: PALETTE });
  renderWithIntl(
    <EditorStoreContext.Provider value={store}>
      <YamlDialog packKey={packKey} dirty={false} {...props} />
    </EditorStoreContext.Provider>,
  );
  return store;
}

describe("YamlDialog", () => {
  beforeEach(() => {
    mocks.importer.mutate.mockReset();
    mocks.toast.mockReset();
    mocks.workflow = ok({ yaml: "version: 1\nentry_node_id: start\n" });
  });

  it("shows the saved version's workflow.yaml", async () => {
    renderDialog("org-a1--overdue");
    await userEvent.click(screen.getByRole("button", { name: "workflow.yaml" }));
    expect(await screen.findByLabelText("The saved workflow.yaml")).toHaveValue("version: 1\nentry_node_id: start\n");
  });

  it("shows a placeholder while the YAML loads", async () => {
    mocks.workflow = { isPending: true, isError: false, data: undefined, error: null };
    renderDialog("org-a1--overdue");
    await userEvent.click(screen.getByRole("button", { name: "workflow.yaml" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByLabelText("The saved workflow.yaml")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says inside the dialog when the YAML cannot be loaded, so the editor behind it is untouched", async () => {
    mocks.workflow = {
      isPending: false,
      isError: true,
      data: undefined,
      error: new ApiError(503, "UNAVAILABLE", "The registry is restarting."),
    };
    renderDialog("org-a1--overdue");
    await userEvent.click(screen.getByRole("button", { name: "workflow.yaml" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The workflow.yaml could not be loaded");
    expect(alert).toHaveTextContent("The registry is restarting.");
    // The other tab still works.
    await userEvent.click(screen.getByRole("button", { name: "Import" }));
    expect(screen.getByLabelText("Paste a workflow.yaml")).toBeInTheDocument();
  });

  it("imports a workflow.yaml onto the canvas, as a step that can be undone, and lists what it could not read", async () => {
    const onImported = vi.fn();
    const store = renderDialog(undefined, { onImported });
    await userEvent.click(screen.getByRole("button", { name: "workflow.yaml" }));
    fireEvent.change(await screen.findByLabelText("Paste a workflow.yaml"), {
      target: { value: "nodes: [{id: start}]" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Replace the canvas" }));
    const [vars, handlers] = mocks.importer.mutate.mock.calls[0];
    expect(vars).toEqual({ path: { org_id: "org_a1" }, body: { yaml: "nodes: [{id: start}]" } });
    const issues = [{ path: "nodes[2]", message: "Step 3 cannot be read as a step." }];
    act(() => handlers.onSuccess({ entryStep: "start", steps: OVERDUE.steps.slice(0, 2), issues }));
    expect(store.getState().nodes.map((n) => n.id)).toEqual(["start", "recall"]);
    expect(screen.getByText("Step 3 cannot be read as a step.")).toBeInTheDocument();
    expect(onImported).toHaveBeenCalledWith(issues);
    act(() => store.getState().undo());
    expect(store.getState().nodes).toHaveLength(OVERDUE.steps.length);
  });

  it("keeps the canvas when the import has no start step, and says so with the issues", async () => {
    const onImported = vi.fn();
    const store = renderDialog(undefined, { onImported });
    const before = store.getState().nodes;
    await userEvent.click(screen.getByRole("button", { name: "workflow.yaml" }));
    fireEvent.change(await screen.findByLabelText("Paste a workflow.yaml"), { target: { value: "nodes: [{}]" } });
    await userEvent.click(screen.getByRole("button", { name: "Replace the canvas" }));
    const issues = [{ path: "nodes[0]", message: "Step 1 cannot be read as a step." }];
    // The unreadable step was the start: what came back has no trigger.
    act(() =>
      mocks.importer.mutate.mock.calls[0][1].onSuccess({ entryStep: "", steps: OVERDUE.steps.slice(1, 3), issues }),
    );
    expect(store.getState().nodes).toBe(before);
    expect(store.getState().history.past).toHaveLength(0);
    expect(onImported).not.toHaveBeenCalled();
    expect(mocks.toast).not.toHaveBeenCalledWith("Steps imported", expect.anything());
    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent("The canvas was not changed");
    expect(notice).toHaveTextContent("The file has no start step, so nothing was imported.");
    expect(notice).toHaveTextContent("Step 1 cannot be read as a step.");
    // Nothing readable at all says the same.
    act(() => mocks.importer.mutate.mock.calls[0][1].onSuccess({ entryStep: "", steps: [], issues: [] }));
    expect(store.getState().nodes).toBe(before);
    expect(screen.getByRole("status")).toHaveTextContent("The file has no start step, so nothing was imported.");
    // The next attempt starts clean: a failure then is not shown beside the old notice.
    await userEvent.click(screen.getByRole("button", { name: "Replace the canvas" }));
    act(() => mocks.importer.mutate.mock.calls[1][1].onError(new Error("offline")));
    expect(screen.queryByText("The file has no start step, so nothing was imported.")).toBeNull();
  });

  it("says when it cannot copy, instead of doing nothing", async () => {
    const clipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
    try {
      renderDialog("org-a1--overdue");
      await userEvent.click(screen.getByRole("button", { name: "workflow.yaml" }));
      await userEvent.click(await screen.findByRole("button", { name: "Copy" }));
      expect(mocks.toast).toHaveBeenCalledWith(
        "Could not copy. Select the text and copy it instead.",
        undefined,
        "blocked",
      );
    } finally {
      if (clipboard) Object.defineProperty(navigator, "clipboard", clipboard);
      else delete (navigator as { clipboard?: unknown }).clipboard;
    }
  });

  it("only exports for a member, who cannot change the pack", async () => {
    renderDialog("org-a1--overdue", { readOnly: true });
    await userEvent.click(screen.getByRole("button", { name: "workflow.yaml" }));
    expect(await screen.findByLabelText("The saved workflow.yaml")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import" })).toBeNull();
    expect(screen.queryByLabelText("Paste a workflow.yaml")).toBeNull();
  });
});
