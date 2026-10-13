import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Link from "next/link";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import { ApiError } from "@/lib/api/errors";
import { DefinitionEditor } from "./definition-editor";

const state = vi.hoisted(() => ({
  canWrite: true,
  validate: vi.fn(),
  publish: vi.fn(),
  push: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: state.push }) }));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => state.canWrite }));
vi.mock("@/lib/queries/definitions", () => ({
  useValidateDefinition: () => ({ mutateAsync: state.validate, isPending: false }),
  usePublishDefinition: () => ({ mutateAsync: state.publish }),
}));

const YAML = "kind: agent\nkey: finance-agent\nruntime:\n  model_profile: reasoning\n";
const FILES = { "instructions.md": "# Finance agent\n", "skills/match-orders.md": "Match them.\n" };
const ISSUE = { kind: "agent", key: "finance-agent", path: "runtime.max_turns", message: "0 is less than 1" };

type EditorProps = Parameters<typeof DefinitionEditor>[0];

const editorTree = (props: Partial<EditorProps> = {}) => (
  <UiProviders>
    <h1 tabIndex={-1}>Finance agent</h1>
    <Link href="/definitions">Definitions</Link>
    <DefinitionEditor
      kind="agent"
      defKey="finance-agent"
      name="Finance agent"
      initial={{ yaml: YAML, files: FILES }}
      nextVersion={3}
      {...props}
    />
  </UiProviders>
);

const renderEditor = (props: Partial<EditorProps> = {}) => render(editorTree(props));

const unload = () => {
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  return event.defaultPrevented;
};

describe("DefinitionEditor", () => {
  beforeEach(() => {
    state.canWrite = true;
    state.validate.mockReset();
    state.push.mockReset();
    state.publish.mockReset().mockImplementation(async ({ body }: { body: { yaml: string; files: object } }) => ({
      summary: { version: 3 },
      yaml: body.yaml,
      files: body.files,
    }));
  });

  it("shows the main file in a monospace text area with its line count, and a tab per Markdown file", async () => {
    const user = userEvent.setup();
    renderEditor();
    const main = screen.getByRole("textbox", { name: "agent.yaml" });
    expect(main).toHaveValue(YAML);
    expect(main).toHaveClass("font-mono");
    expect(screen.getByText("5 lines")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "skills/match-orders.md" }));
    expect(screen.getByRole("textbox", { name: "skills/match-orders.md" })).toHaveValue("Match them.\n");
  });

  it("lists every validation problem with its path and message", async () => {
    const user = userEvent.setup();
    state.validate.mockResolvedValue({ ok: false, errors: [ISSUE] });
    renderEditor();
    await user.click(screen.getByRole("button", { name: "Validate" }));
    const list = await screen.findByRole("list", { name: "Problems" });
    expect(within(list).getByText("runtime.max_turns")).toBeInTheDocument();
    expect(within(list).getByText("0 is less than 1")).toBeInTheDocument();
    expect(state.validate).toHaveBeenCalledWith({
      path: { kind: "agent", key: "finance-agent" },
      body: { yaml: YAML, files: FILES },
    });
  });

  it("says so when the edit is valid", async () => {
    const user = userEvent.setup();
    state.validate.mockResolvedValue({ ok: true, errors: [] });
    renderEditor();
    await user.click(screen.getByRole("button", { name: "Validate" }));
    expect(await screen.findByText(/No problems found/)).toBeInTheDocument();
  });

  it("asks for a reason before publishing, then publishes the edited files", async () => {
    const user = userEvent.setup();
    const onPublished = vi.fn();
    renderEditor({ onPublished });
    const main = screen.getByRole("textbox", { name: "agent.yaml" });
    await user.type(main, "# edited\n");

    await user.click(screen.getByRole("button", { name: "Publish" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Publish Finance agent as v3?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Publish v3" }));
    expect(await within(dialog).findByText(/Give a reason/)).toBeInTheDocument();
    expect(state.publish).not.toHaveBeenCalled();

    await user.type(within(dialog).getByLabelText("Reason"), "Allow one more turn");
    await user.click(within(dialog).getByRole("button", { name: "Publish v3" }));
    await waitFor(() =>
      expect(state.publish).toHaveBeenCalledWith({
        path: { kind: "agent", key: "finance-agent" },
        body: { yaml: `${YAML}# edited\n`, files: FILES, reason: "Allow one more turn", baseVersion: 2 },
      }),
    );
    await waitFor(() => expect(onPublished).toHaveBeenCalled());
  });

  // Publishing writes the result to the cache before the mutation resolves (usePublishDefinition's onSuccess),
  // so the editor re-renders with the new latest version while its own publish is still in flight.
  const publishWithCacheWrite = async (view: ReturnType<typeof renderEditor>) => {
    const published = { yaml: "kind: agent\nkey: finance-agent\n# as stored\n", files: FILES };
    const seen = { callout: false };
    let finish: () => void = () => {};
    state.publish.mockImplementation(async () => {
      view.rerender(editorTree({ initial: published, nextVersion: 4 }));
      seen.callout = screen.queryByText(/was published since you started/) !== null;
      await new Promise<void>((resolve) => (finish = resolve));
      return { summary: { version: 3 }, ...published };
    });
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: "agent.yaml" }), "# edited\n");
    await user.click(screen.getByRole("button", { name: "Publish" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Reason"), "Allow one more turn");
    await user.click(within(dialog).getByRole("button", { name: "Publish v3" }));
    await waitFor(() => expect(state.publish).toHaveBeenCalled());
    return { published, seen, finish: () => finish() };
  };

  it("does not warn about its own publish while it is in flight", async () => {
    const view = renderEditor();
    const { seen, finish } = await publishWithCacheWrite(view);
    expect(seen.callout).toBe(false);
    expect(screen.queryByText(/was published since you started/)).toBeNull();
    finish();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(screen.queryByText(/was published since you started/)).toBeNull();
  });

  it("makes the published text, as the API stored it, the new starting point", async () => {
    const view = renderEditor();
    const { published, finish } = await publishWithCacheWrite(view);
    finish();
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(screen.getByRole("textbox", { name: "agent.yaml" })).toHaveValue(published.yaml);
    // Nothing is left to discard or guard, and a later newer version still loads on its own.
    expect(screen.queryByRole("button", { name: "Discard changes" })).toBeNull();
    expect(unload()).toBe(false);
    view.rerender(editorTree({ initial: { yaml: "kind: agent\n# v4\n", files: FILES }, nextVersion: 5 }));
    expect(screen.getByRole("textbox", { name: "agent.yaml" })).toHaveValue("kind: agent\n# v4\n");
  });

  it("sends base version 0 when creating a definition", async () => {
    const user = userEvent.setup();
    renderEditor({ isNew: true, nextVersion: 1, defKey: "billing-agent", name: "billing-agent" });
    await user.click(screen.getByRole("button", { name: "Create v1" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Reason"), "New agent");
    await user.click(within(dialog).getByRole("button", { name: "Create v1" }));
    await waitFor(() => expect(state.publish).toHaveBeenCalled());
    expect(state.publish.mock.calls[0][0].body.baseVersion).toBe(0);
  });

  it("shows the API's conflict when someone published since the edit started", async () => {
    const user = userEvent.setup();
    state.publish.mockRejectedValue(
      new ApiError(409, "VERSION_CONFLICT", "v3 of agent/finance-agent was published since this edit started from v2."),
    );
    renderEditor();
    await user.type(screen.getByRole("textbox", { name: "agent.yaml" }), "# edited\n");
    await user.click(screen.getByRole("button", { name: "Publish" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Reason"), "Try it");
    await user.click(within(dialog).getByRole("button", { name: "Publish v3" }));
    expect(await within(dialog).findByText(/was published since this edit started/)).toBeInTheDocument();
  });

  it("keeps unpublished edits when a newer version arrives, and says so", async () => {
    const user = userEvent.setup();
    const view = renderEditor();
    const main = screen.getByRole("textbox", { name: "agent.yaml" });
    await user.type(main, "# mine\n");

    view.rerender(editorTree({ initial: { yaml: "kind: agent\n# v3\n", files: FILES }, nextVersion: 4 }));
    expect(main).toHaveValue(`${YAML}# mine\n`);
    expect(screen.getByText("v3 was published since you started")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Load v3" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Discard and load v3" }));
    expect(screen.getByRole("textbox", { name: "agent.yaml" })).toHaveValue("kind: agent\n# v3\n");
    expect(screen.queryByText(/was published since you started/)).toBeNull();
  });

  it("loads a newer version straight away when nothing is edited", () => {
    const view = renderEditor();
    view.rerender(editorTree({ initial: { yaml: "kind: agent\n# v3\n", files: FILES }, nextVersion: 4 }));
    expect(screen.getByRole("textbox", { name: "agent.yaml" })).toHaveValue("kind: agent\n# v3\n");
    expect(screen.queryByText(/was published since you started/)).toBeNull();
  });

  it("asks before leaving with unpublished edits, by link or by closing the tab", async () => {
    const user = userEvent.setup();
    renderEditor();
    expect(unload()).toBe(false);
    await user.type(screen.getByRole("textbox", { name: "agent.yaml" }), "# mine\n");
    expect(unload()).toBe(true);

    await user.click(screen.getByRole("link", { name: "Definitions" }));
    let dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Leave without publishing?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Keep editing" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(state.push).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "agent.yaml" })).toHaveValue(`${YAML}# mine\n`);

    await user.click(screen.getByRole("link", { name: "Definitions" }));
    dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Discard and leave" }));
    expect(state.push).toHaveBeenCalledWith("/definitions");
  });

  it("confirms before discarding changes", async () => {
    const user = userEvent.setup();
    renderEditor();
    const main = screen.getByRole("textbox", { name: "agent.yaml" });
    await user.type(main, "# mine\n");
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    let dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Keep editing" }));
    expect(main).toHaveValue(`${YAML}# mine\n`);

    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Discard changes" }));
    expect(screen.getByRole("textbox", { name: "agent.yaml" })).toHaveValue(YAML);
  });

  it("drops a validation answer for text that has changed since", async () => {
    const user = userEvent.setup();
    let answer: (v: unknown) => void = () => {};
    state.validate.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    renderEditor();
    await user.click(screen.getByRole("button", { name: "Validate" }));
    await user.type(screen.getByRole("textbox", { name: "agent.yaml" }), "x");
    answer({ ok: true, errors: [] });
    await waitFor(() => expect(state.validate).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText(/No problems found/)).toBeNull();
  });

  it("drops a validation answer for text replaced by a newer version", async () => {
    const user = userEvent.setup();
    let answer: (v: unknown) => void = () => {};
    state.validate.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const view = renderEditor();
    await user.click(screen.getByRole("button", { name: "Validate" }));
    view.rerender(editorTree({ initial: { yaml: "kind: agent\n# v3\n", files: FILES }, nextVersion: 4 }));
    expect(screen.getByRole("textbox", { name: "agent.yaml" })).toHaveValue("kind: agent\n# v3\n");
    answer({ ok: true, errors: [] });
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText(/No problems found/)).toBeNull();
  });

  it("announces a failed check once, through the live region", async () => {
    const user = userEvent.setup();
    state.validate.mockRejectedValue(new ApiError(503, "RUNTIME_UNAVAILABLE", "The runtime is off."));
    renderEditor();
    await user.click(screen.getByRole("button", { name: "Validate" }));
    const message = await screen.findByText("The runtime is off.");
    expect(message).not.toHaveAttribute("role");
    expect(message.closest("[aria-live]")).not.toBeNull();
  });

  it("shows the problems a refused publish reports", async () => {
    const user = userEvent.setup();
    state.publish.mockRejectedValue(new ApiError(422, "INVALID_DEFINITION", "1 problem(s)", [ISSUE]));
    renderEditor();
    await user.click(screen.getByRole("button", { name: "Publish" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByLabelText("Reason"), "Try it");
    await user.click(within(dialog).getByRole("button", { name: "Publish v3" }));
    expect(await within(dialog).findByText("1 problem(s)")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Problems" });
    expect(within(list).getByText("0 is less than 1")).toBeInTheDocument();
  });

  it("creates a new definition as version 1", async () => {
    const user = userEvent.setup();
    renderEditor({ isNew: true, nextVersion: 1, defKey: "billing-agent", name: "billing-agent" });
    await user.click(screen.getByRole("button", { name: "Create v1" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("Create agent billing-agent?")).toBeInTheDocument();
  });

  it("adds a skill file as a new tab, refusing paths outside skills/", async () => {
    const user = userEvent.setup();
    renderEditor();
    await user.click(screen.getByRole("button", { name: "Add file" }));
    const path = screen.getByLabelText("New file path");
    await user.type(path, "notes.md");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByRole("alert")).toHaveTextContent("skills/<name>.md");

    await user.clear(path);
    await user.type(path, "skills/refunds.md");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(screen.getByRole("tab", { name: "skills/refunds.md" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("textbox", { name: "skills/refunds.md" })).toHaveValue("");
  });

  it("lets support validate but not publish or add files", () => {
    state.canWrite = false;
    renderEditor();
    expect(screen.getByRole("button", { name: "Validate" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add file" })).toBeDisabled();
  });

  it("offers no file tabs or Add file for kinds without Markdown", () => {
    renderEditor({ kind: "connector", defKey: "stripe", initial: { yaml: "kind: connector\n", files: {} } });
    expect(screen.getByRole("textbox", { name: "stripe.yaml" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add file" })).toBeNull();
  });
});
