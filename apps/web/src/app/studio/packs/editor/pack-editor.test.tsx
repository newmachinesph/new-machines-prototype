import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import { OVERDUE, PALETTE } from "@/lib/builder/test-fixtures";
import { layoutGraph } from "@/lib/graph-layout";
import { renderWithIntl } from "@/test/intl";
import { PackEditor } from "./pack-editor";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const mocks = vi.hoisted(() => ({
  pack: { isPending: false, isError: false, data: undefined, error: undefined } as Record<string, unknown>,
  create: { mutate: vi.fn(), isPending: false },
  save: { mutate: vi.fn(), isPending: false },
  validate: { mutate: vi.fn(), isPending: false },
  importer: { mutate: vi.fn(), isPending: false },
  refetch: vi.fn(async () => ({})),
  replace: vi.fn(),
  toast: vi.fn(),
  role: "owner",
}));
const SAVED = { key: "org-a1--overdue", version: 3, publishedAt: "", publishedBy: "u1", draft: OVERDUE, added: false };

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: mocks.replace, push: vi.fn() }) }));
vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => mocks.toast,
}));
vi.mock("@/lib/queries/me", () => ({
  useOrgId: () => "org_a1",
  useMe: () => ok({ orgId: "org_a1", role: mocks.role }),
}));
vi.mock("@/lib/queries/studio", () => ({
  useStudioPalette: () => ok(PALETTE),
  useStudioPack: () => mocks.pack,
  useCreateStudioPack: () => mocks.create,
  useSaveStudioPack: () => mocks.save,
  useValidateStudioPack: () => mocks.validate,
  useStudioPackWorkflow: () => ok({ yaml: "version: 1\n" }),
  useImportStudioWorkflow: () => mocks.importer,
  useTestStudioPack: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/lib/graph-layout", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/graph-layout")>()),
  layoutGraph: vi.fn(async () => ({ positions: {}, routes: {} })),
}));
// React Flow measures its container and nodes; jsdom has neither API.
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);
vi.stubGlobal(
  "DOMMatrixReadOnly",
  class {
    m22 = 1;
  },
);

const saveButton = () => screen.getByRole("button", { name: "Save pack" });
const validateButton = () => screen.getByRole("button", { name: "Check for problems" });
/** Opens the editor on the saved Overdue pack at version 3. */
function editing() {
  mocks.pack = { ...ok(SAVED), refetch: mocks.refetch };
  return renderWithIntl(<PackEditor packKey={SAVED.key} />);
}
const budgetField = () => screen.getByLabelText("Most a run may spend on agents (USD)");

describe("PackEditor", () => {
  beforeEach(() => {
    mocks.pack = { isPending: false, isError: false, data: undefined, error: undefined };
    mocks.role = "owner";
    mocks.create.isPending = false;
    mocks.refetch.mockClear();
    for (const m of [
      mocks.create.mutate,
      mocks.save.mutate,
      mocks.validate.mutate,
      mocks.importer.mutate,
      mocks.replace,
      mocks.toast,
    ])
      m.mockReset();
    vi.mocked(layoutGraph).mockClear();
  });

  it("starts a new pack from a starter with no problems, and creates it on save", async () => {
    renderWithIntl(<PackEditor />);
    expect(screen.getByText("No problems found.")).toBeInTheDocument();
    await userEvent.click(saveButton());
    const [vars, handlers] = mocks.create.mutate.mock.calls[0];
    expect(vars.path).toEqual({ org_id: "org_a1" });
    expect(vars.body.name).toBe("New workflow pack");
    expect(vars.body.steps.map((s: { id: string }) => s.id)).toEqual(["start", "review", "done", "failed"]);
    act(() => handlers.onSuccess({ key: "org-a1--new-workflow-pack", version: 1 }));
    expect(mocks.replace).toHaveBeenCalledWith("/studio/packs/org-a1--new-workflow-pack");
  });

  it("lists the API's problems by step and opens the step", async () => {
    renderWithIntl(<PackEditor />);
    await userEvent.click(validateButton());
    expect(mocks.validate.mutate.mock.calls[0][0].query).toBeUndefined();
    const issue = { path: "nodes[1].config.title", message: "The review needs a clearer title.", step: "review" };
    act(() => mocks.validate.mutate.mock.calls[0][1].onSuccess({ ok: false, issues: [issue] }));
    expect(screen.getByText("Checked by the server")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /The review needs a clearer title/ }));
    expect(screen.getByLabelText("Step name")).toHaveValue("review");
  });

  it("saves an existing pack against the version it was opened at, and says when someone saved first", async () => {
    editing();
    expect(saveButton()).toBeDisabled();
    // Why it is greyed is read with the button, not only seen beside it; it goes once there is something to save.
    expect(saveButton()).toHaveAccessibleDescription("No changes to save.");
    await userEvent.type(screen.getByLabelText("Name"), " v2");
    expect(saveButton()).not.toHaveAttribute("aria-describedby");
    expect(screen.queryByText("No changes to save.")).toBeNull();
    await userEvent.click(saveButton());
    const [vars, handlers] = mocks.save.mutate.mock.calls[0];
    expect(vars.path).toEqual({ org_id: "org_a1", key: "org-a1--overdue" });
    expect(vars.body.baseVersion).toBe(3);
    expect(vars.body.draft.name).toBe("Overdue invoice follow-up v2");
    act(() => handlers.onError(new ApiError(409, "VERSION_CONFLICT", "Saved since.")));
    // A notice that stays, in our words with the API's beneath, and a way out; not a toast that fades.
    expect(mocks.toast).not.toHaveBeenCalled();
    const notice = screen.getByText("A newer version was saved").closest('[role="status"]');
    expect(notice).toHaveTextContent(/Someone saved a newer version since you opened this one/);
    expect(notice).toHaveTextContent("Saved since.");
    await userEvent.click(screen.getByRole("button", { name: "Load the latest version" }));
    expect(mocks.refetch).toHaveBeenCalledTimes(1);
  });

  it("keeps unsaved edits through a background refetch, and loads the latest version only when asked", async () => {
    const { rerender } = editing();
    await userEvent.type(screen.getByLabelText("Name"), " v2");
    // Someone else saved (an agent save rebuilds its packs): the cache moves to version 5 under the open editor.
    const newer = { ...SAVED, version: 5, draft: { ...OVERDUE, name: "Renamed elsewhere" } };
    mocks.pack = { ...ok(newer), refetch: mocks.refetch };
    rerender(<PackEditor packKey={SAVED.key} />);
    expect(screen.getByLabelText("Name")).toHaveValue("Overdue invoice follow-up v2");
    expect(screen.getByText(/Version 3/)).toBeInTheDocument();
    expect(screen.getByText("A newer version was saved")).toBeInTheDocument();
    expect(screen.getByText(/Version 5 is now the latest/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load the latest version" }));
    expect(mocks.refetch).toHaveBeenCalledTimes(1);
    expect(await screen.findByDisplayValue("Renamed elsewhere")).toBeInTheDocument();
    expect(screen.getByText(/Version 5/)).toBeInTheDocument();
    expect(screen.queryByText("A newer version was saved")).toBeNull();
  });

  it("keeps the edits and says so when loading the latest version fails", async () => {
    mocks.refetch.mockResolvedValueOnce({ isError: true, error: new Error("offline") });
    const { rerender } = editing();
    await userEvent.type(screen.getByLabelText("Name"), " v2");
    mocks.pack = { ...ok({ ...SAVED, version: 5 }), refetch: mocks.refetch };
    rerender(<PackEditor packKey={SAVED.key} />);
    await userEvent.click(screen.getByRole("button", { name: "Load the latest version" }));
    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith(
        "The latest version could not be loaded",
        "Something went wrong.",
        "blocked",
      ),
    );
    expect(screen.getByLabelText("Name")).toHaveValue("Overdue invoice follow-up v2");
  });

  it("asks before an in-app link is followed while there are unsaved changes", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const followed = vi.fn();
    const stop = (e: React.MouseEvent) => {
      e.preventDefault();
      followed();
    };
    mocks.pack = { ...ok(SAVED), refetch: mocks.refetch };
    renderWithIntl(
      <>
        <a href="/elsewhere" onClick={stop}>
          Packs
        </a>
        <PackEditor packKey={SAVED.key} />
      </>,
    );
    await userEvent.click(screen.getByRole("link", { name: "Packs" }));
    expect(confirm).not.toHaveBeenCalled();
    expect(followed).toHaveBeenCalledTimes(1);
    await userEvent.type(screen.getByLabelText("Name"), " v2");
    await userEvent.click(screen.getByRole("link", { name: "Packs" }));
    expect(confirm).toHaveBeenCalledWith("You have unsaved changes. Leave this page without saving them?");
    expect(followed).toHaveBeenCalledTimes(1);
    confirm.mockRestore();
  });

  it("lets a new pack nobody has touched be left without asking", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    renderWithIntl(
      <>
        <a href="/elsewhere" onClick={(e) => e.preventDefault()}>
          Packs
        </a>
        <PackEditor />
      </>,
    );
    await userEvent.click(screen.getByRole("link", { name: "Packs" }));
    expect(confirm).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Name"), " v2");
    await userEvent.click(screen.getByRole("link", { name: "Packs" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    confirm.mockRestore();
  });

  it("keeps the open editor when a background refetch answers 404", () => {
    mocks.pack = {
      isPending: false,
      isError: true,
      error: new ApiError(404, "NOT_FOUND", "No such pack"),
      data: SAVED,
      refetch: mocks.refetch,
    };
    renderWithIntl(<PackEditor packKey={SAVED.key} />);
    expect(screen.getByLabelText("Name")).toHaveValue("Overdue invoice follow-up");
    expect(screen.queryByText("This pack is not one of yours.")).toBeNull();
  });

  it("locks the editor while a new pack is being created, so nothing typed then is lost when it opens", () => {
    mocks.create.isPending = true;
    renderWithIntl(<PackEditor />);
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Type of field 1" })).toBeDisabled();
    expect(saveButton()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
  });

  it("moves focus to the panel heading after Remove and after the Pack details button", async () => {
    renderWithIntl(<PackEditor />);
    await userEvent.click(screen.getByRole("button", { name: /^Human review/ }));
    await userEvent.click(screen.getByRole("button", { name: "Pack details" }));
    expect(screen.getByRole("heading", { name: "Pack details" })).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: /^Human review/ }));
    await userEvent.click(screen.getByRole("button", { name: "Remove step" }));
    expect(screen.queryByLabelText("Step name")).toBeNull();
    expect(screen.getByRole("heading", { name: "Pack details" })).toHaveFocus();
  });

  it("forgets a focus request once a step is selected, so returning to the details does not jump into an old field", async () => {
    renderWithIntl(<PackEditor />);
    await userEvent.clear(budgetField());
    await userEvent.click(screen.getByRole("button", { name: /^Human review/ }));
    await userEvent.click(screen.getByRole("button", { name: /^Most a run may spend on agents \(USD\): enter/ }));
    expect(budgetField()).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: /^Human review/ }));
    await userEvent.click(screen.getByRole("button", { name: "Pack details" }));
    expect(budgetField()).not.toHaveFocus();
    expect(screen.getByRole("heading", { name: "Pack details" })).toHaveFocus();
  });

  it("lists the problems the API finds on save", async () => {
    renderWithIntl(<PackEditor />);
    await userEvent.click(saveButton());
    const issue = { kind: "studio", key: "review", path: "steps[1]", message: "A reviewer pool is needed." };
    act(() =>
      mocks.create.mutate.mock.calls[0][1].onError(new ApiError(422, "INVALID_DEFINITION", "1 problem", [issue])),
    );
    expect(screen.getByText("A reviewer pool is needed.")).toBeInTheDocument();
    expect(screen.getByText("From the server")).toBeInTheDocument();
    expect(mocks.toast).toHaveBeenCalledWith("The pack was not saved", "See the problems below the steps.", "blocked");
  });

  it("checks a saved pack against its own key, so its name is not counted against it", async () => {
    editing();
    await userEvent.click(validateButton());
    expect(mocks.validate.mutate.mock.calls[0][0].query).toEqual({ key: "org-a1--overdue" });
    act(() => mocks.validate.mutate.mock.calls[0][1].onSuccess({ ok: true, issues: [] }));
    expect(mocks.toast).toHaveBeenCalledWith("No problems found", "The server accepts this pack as it is.");
  });

  it("shows a name another pack already uses on the name field", async () => {
    renderWithIntl(<PackEditor />);
    await userEvent.click(validateButton());
    const issue = { path: "name", message: "Another pack is called that." };
    act(() => mocks.validate.mutate.mock.calls[0][1].onSuccess({ ok: false, issues: [issue] }));
    const name = screen.getByLabelText("Name");
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription("Another pack is called that.");
  });

  it("says plainly when a rename meets runs in progress", async () => {
    editing();
    await userEvent.type(screen.getByLabelText("Name"), " v2");
    await userEvent.click(saveButton());
    const detail = "3 runs are in progress. Wait for them to finish before renaming the pack.";
    act(() => mocks.save.mutate.mock.calls[0][1].onError(new ApiError(409, "RUNS_IN_PROGRESS", detail)));
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The pack cannot be renamed yet");
    expect(alert).toHaveTextContent(/Runs of this pack are in progress/);
    expect(alert).toHaveTextContent(detail);
    // Changing the name again is what the notice asked for, so it goes.
    await userEvent.type(screen.getByLabelText("Name"), "x");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps an unfinished draft on the page instead of sending it, and lists what is missing", async () => {
    renderWithIntl(<PackEditor />);
    await userEvent.clear(screen.getByLabelText("Name"));
    // Once under the canvas, once under the field, which is marked.
    expect(screen.getAllByText("Fill in Name.")).toHaveLength(2);
    expect(screen.getByLabelText("Name")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription("Fill in Name.");
    await userEvent.click(saveButton());
    expect(mocks.create.mutate).not.toHaveBeenCalled();
    expect(mocks.toast).toHaveBeenCalledWith("The pack was not saved", expect.stringMatching(/^Fix/), "blocked");
    await userEvent.click(validateButton());
    expect(mocks.validate.mutate).not.toHaveBeenCalled();
    expect(mocks.toast).toHaveBeenCalledWith("The pack was not checked", expect.stringMatching(/^Fix/), "blocked");
  });

  it("starts a new start-form field with a label, and flags a bad field name or an empty label", async () => {
    renderWithIntl(<PackEditor />);
    await userEvent.click(screen.getByRole("button", { name: "Add a field" }));
    expect(screen.getByLabelText("Name of field 2")).toHaveValue("field_2");
    expect(screen.getByLabelText("Label of field 2")).toHaveValue("Field 2");
    expect(screen.getByText("No problems found.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Name of field 2"), "-x");
    expect(screen.getAllByText(/^Field 2: names use lowercase letters/)).toHaveLength(2);
    expect(screen.getByLabelText("Name of field 2")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Label of field 2")).not.toHaveAttribute("aria-invalid");
    await userEvent.clear(screen.getByLabelText("Label of field 2"));
    expect(screen.getAllByText("Field 2 needs a label.")).toHaveLength(2);
    expect(screen.getByLabelText("Label of field 2")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("2 problems")).toBeInTheDocument();
  });

  it("flags a budget below the API's minimum, and a picked problem puts the cursor in its field", async () => {
    renderWithIntl(<PackEditor />);
    await userEvent.clear(screen.getByLabelText("Most a run may spend on agents (USD)"));
    const message = /^Most a run may spend on agents \(USD\): enter an amount from/;
    // Once under the input, once in the list of problems.
    expect(screen.getAllByText(message)).toHaveLength(2);
    expect(screen.getByLabelText("Most a run may spend on agents (USD)")).toHaveAttribute("aria-invalid", "true");
    // Look at a step first, so the pick has to bring the details back.
    await userEvent.click(screen.getByRole("button", { name: /^Human review/ }));
    expect(screen.getByLabelText("Step name")).toHaveValue("review");
    await userEvent.click(screen.getByRole("button", { name: message }));
    expect(screen.getByLabelText("Most a run may spend on agents (USD)")).toHaveFocus();
  });

  it("opens the details for a problem the server reports without a step", async () => {
    renderWithIntl(<PackEditor />);
    await userEvent.click(screen.getByRole("button", { name: /^Human review/ }));
    await userEvent.click(validateButton());
    const issue = { path: "name", message: "Another pack is called that." };
    act(() => mocks.validate.mutate.mock.calls[0][1].onSuccess({ ok: false, issues: [issue] }));
    expect(screen.queryByLabelText("Name")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Another pack is called that/ }));
    expect(screen.getByLabelText("Name")).toHaveAccessibleDescription("Another pack is called that.");
  });

  it("lets a member read a pack but not change or save it", async () => {
    mocks.role = "member";
    editing();
    expect(screen.getByLabelText("Name")).toHaveValue("Overdue invoice follow-up");
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Type of field 1" })).toBeDisabled();
    // Base UI's checkbox is a span: it says it is disabled rather than being a disabled control.
    expect(screen.getByRole("checkbox", { name: "Required" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("button", { name: "Save pack" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Check for problems" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Auto-arrange" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Add a step after/ })).toBeNull();
    expect(screen.getByText("Only owners and admins can build agents and packs.")).toBeInTheDocument();
    // The saved workflow.yaml can be read and copied; importing one or testing the pack cannot.
    expect(screen.queryByRole("button", { name: "Test in sandbox" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "workflow.yaml" }));
    expect(await screen.findByLabelText("The saved workflow.yaml")).toHaveValue("version: 1\n");
    expect(screen.queryByRole("button", { name: "Import and replace" })).toBeNull();
    await userEvent.keyboard("{Escape}");
    // A step can be looked at, but its settings, choices and field pickers are off, and Delete removes nothing.
    await userEvent.click(screen.getByRole("button", { name: /^Human review/ }));
    expect(screen.getByLabelText("Step name")).toHaveValue("review");
    expect(screen.getByLabelText("Step name")).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "resolved goes to" })).toBeDisabled();
    const pickers = screen.getAllByRole("button", { name: /^Fields to insert into/ });
    expect(pickers.length).toBeGreaterThan(0);
    for (const picker of pickers) expect(picker).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove step" })).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("group", { name: "Workflow canvas" }), { key: "Delete" });
    expect(screen.getByLabelText("Step name")).toHaveValue("review");
  });

  it("offers a sandbox test once the pack is saved as it is, and lists what an import could not read", async () => {
    editing();
    expect(screen.getByRole("button", { name: "Test in sandbox" })).toBeEnabled();
    await userEvent.type(screen.getByLabelText("Name"), " v2");
    expect(screen.getByRole("button", { name: "Test in sandbox" })).toBeDisabled();
    expect(screen.getByText("Save your changes to test them.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "workflow.yaml" }));
    await userEvent.click(screen.getByRole("button", { name: "Import and replace" }));
    fireEvent.change(screen.getByLabelText("Paste a workflow.yaml"), { target: { value: "nodes: []" } });
    await userEvent.click(screen.getByRole("button", { name: "Replace the draft with this file" }));
    // An unreadable step has no step name to attach to: the API locates it by its path only.
    const issue = { path: "nodes[2]", message: "Step 3 cannot be read as a step." };
    act(() =>
      mocks.importer.mutate.mock.calls[0][1].onSuccess({
        entryStep: "start",
        steps: OVERDUE.steps.slice(0, 2),
        issues: [issue],
      }),
    );
    expect(mocks.toast).toHaveBeenCalledWith("Steps imported", "2 steps are in the editor.");
    await userEvent.keyboard("{Escape}");
    // Under the canvas, and not passed off as a full check of the draft.
    expect(screen.getByText("From the server")).toBeInTheDocument();
    expect(screen.queryByText("Checked by the server")).toBeNull();
    // Like any problem the server reports without a step, it opens the pack details.
    await userEvent.click(screen.getAllByRole("button", { name: /^Memory/ })[0]);
    expect(screen.getByLabelText("Step name")).toHaveValue("recall");
    await userEvent.click(screen.getByRole("button", { name: /Step 3 cannot be read as a step/ }));
    expect(screen.queryByLabelText("Step name")).toBeNull();
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
    // The import is one undoable step.
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(screen.queryByText("Step 3 cannot be read as a step.")).toBeNull();
  });

  it("leaves the canvas out on a phone, says so, and brings the settings into view when a step is chosen", async () => {
    // Nothing matches: a viewport narrower than md, where the panels stack and the canvas is left out.
    const hadMatchMedia = Object.getOwnPropertyDescriptor(window, "matchMedia");
    window.matchMedia = vi.fn((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })) as unknown as typeof window.matchMedia;
    // jsdom does not scroll: what asked to be brought into view is recorded instead.
    const scrolled: Element[] = [];
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
    try {
      renderWithIntl(<PackEditor />);
      expect(screen.queryByRole("group", { name: "Workflow canvas" })).toBeNull();
      expect(screen.getByText(/^Easier on a larger screen/)).toBeInTheDocument();
      expect(scrolled).toHaveLength(0);
      await userEvent.click(screen.getByRole("button", { name: /^Human review/ }));
      expect(screen.getByLabelText("Step name")).toHaveValue("review");
      expect(scrolled).toEqual([screen.getByRole("heading", { name: "Step settings" })]);
    } finally {
      if (hadMatchMedia) Object.defineProperty(window, "matchMedia", hadMatchMedia);
      else delete (window as { matchMedia?: unknown }).matchMedia;
      delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });

  it("does not scroll the canvas away when a step is chosen while the canvas is shown", async () => {
    // Stacked panels with a canvas (768 to 1279px): only the md query matches.
    const hadMatchMedia = Object.getOwnPropertyDescriptor(window, "matchMedia");
    window.matchMedia = vi.fn((query: string) => ({
      matches: query === "(min-width: 48rem)",
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })) as unknown as typeof window.matchMedia;
    const scrolled: Element[] = [];
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
    try {
      renderWithIntl(<PackEditor />);
      expect(screen.getByRole("group", { name: "Workflow canvas" })).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: /^Human review/ }));
      expect(screen.getByLabelText("Step name")).toHaveValue("review");
      expect(scrolled).toHaveLength(0);
    } finally {
      if (hadMatchMedia) Object.defineProperty(window, "matchMedia", hadMatchMedia);
      else delete (window as { matchMedia?: unknown }).matchMedia;
      delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
    }
  });

  it("shows a member a notice instead of the new pack editor", () => {
    mocks.role = "member";
    renderWithIntl(<PackEditor />);
    expect(screen.getByText("Only owners and admins can build agents and packs.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to packs" })).toHaveAttribute("href", "/studio/packs");
    expect(screen.queryByLabelText("Name")).toBeNull();
  });

  it("says when a pack key is not one of the org's", () => {
    mocks.pack = {
      isPending: false,
      isError: true,
      error: new ApiError(404, "NOT_FOUND", "No such pack"),
      data: undefined,
    };
    renderWithIntl(<PackEditor packKey="org-zz--secret" />);
    expect(screen.getByText("This pack is not one of yours.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to packs" })).toHaveAttribute("href", "/studio/packs");
  });

  it("speaks Japanese", () => {
    renderWithIntl(<PackEditor />, { locale: "ja" });
    expect(screen.getByRole("button", { name: "パックを保存" })).toBeInTheDocument();
    expect(screen.getByText("問題は見つかりませんでした。")).toBeInTheDocument();
  });
});
