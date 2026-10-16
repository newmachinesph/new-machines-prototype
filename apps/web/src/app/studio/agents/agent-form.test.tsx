import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api/errors";
import type { StudioAgent } from "@/lib/api/gen/types.gen";
import { PALETTE } from "@/lib/builder/test-fixtures";
import { renderWithIntl } from "@/test/intl";
import { AgentEditor } from "./agent-form";
import { AgentsList } from "./agents-list";
import { NewAgentLink } from "./new-agent-link";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const AGENT: StudioAgent = {
  key: "org-a1--invoice-helper",
  version: 3,
  publishedAt: "2026-10-14T00:00:00Z",
  publishedBy: "u1",
  draft: {
    name: "Invoice helper",
    summary: "Finds open invoices.",
    instructions: "Read the open invoices.",
    modelProfile: "fast",
    skills: [{ title: "Find open invoices", text: "List the open ones." }],
    tools: ["stripe.list_invoices"],
    maxTurns: 6,
  },
};
const mocks = vi.hoisted(() => ({
  create: { mutate: vi.fn(), isPending: false },
  save: { mutate: vi.fn(), isPending: false },
  agent: { isPending: false, isError: false, data: undefined, error: undefined } as Record<string, unknown>,
  refetch: vi.fn(async () => ({})),
  replace: vi.fn(),
  toast: vi.fn(),
  role: "owner",
}));

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
  useStudioAgents: () => ok([]),
  useStudioPacks: () => ok([]),
  useStudioPalette: () => ok(PALETTE),
  useStudioAgent: () => mocks.agent,
  useCreateStudioAgent: () => mocks.create,
  useSaveStudioAgent: () => mocks.save,
}));

async function fillIn() {
  await userEvent.type(screen.getByLabelText("Name"), "Invoice helper");
  await userEvent.type(screen.getByLabelText("Summary"), "Finds open invoices.");
  await userEvent.type(screen.getByLabelText("Instructions"), "Read the open invoices.");
}

/** Opens the editor on a saved agent at version 3. */
function editing(agent: StudioAgent = AGENT) {
  mocks.agent = { ...ok(agent), refetch: mocks.refetch };
  return renderWithIntl(<AgentEditor agentKey={agent.key} />);
}

const save = () => userEvent.click(screen.getByRole("button", { name: "Save agent" }));
/** Unfolds an app in the tool picker (its tools are not on the page until it is opened). */
const openApp = (app: string) => userEvent.click(screen.getByRole("button", { name: new RegExp(`^${app} `) }));
const pickStripe = async () => {
  await openApp("Stripe");
  await userEvent.click(screen.getByRole("checkbox", { name: /Stripe: List invoices/ }));
};
const createHandlers = () => mocks.create.mutate.mock.calls[0][1];
const saveHandlers = () => mocks.save.mutate.mock.calls[0][1];

describe("AgentEditor", () => {
  beforeEach(() => {
    mocks.create.mutate.mockReset();
    mocks.save.mutate.mockReset();
    mocks.refetch.mockClear();
    mocks.replace.mockReset();
    mocks.toast.mockReset();
    mocks.agent = { isPending: false, isError: false, data: undefined, error: undefined };
    mocks.role = "owner";
  });

  it("locks the form while a new agent is being created, so nothing typed then is lost when it opens", () => {
    mocks.create.isPending = true;
    try {
      renderWithIntl(<AgentEditor />);
      expect(screen.getByLabelText("Name")).toBeDisabled();
    } finally {
      mocks.create.isPending = false;
    }
  });

  it("offers only tools that read, and saves a new agent", async () => {
    renderWithIntl(<AgentEditor />);
    await fillIn();
    expect(screen.queryByRole("checkbox", { name: /Gmail: Create draft/ })).toBeNull();
    expect(screen.getByText(/Agents only read/)).toBeInTheDocument();
    await pickStripe();
    await save();
    const [vars, handlers] = mocks.create.mutate.mock.calls[0];
    expect(vars).toEqual({
      path: { org_id: "org_a1" },
      body: expect.objectContaining({
        name: "Invoice helper",
        modelProfile: "reasoning",
        tools: ["stripe.list_invoices"],
        maxTurns: 6,
      }),
    });
    act(() => handlers.onSuccess({ key: "org-a1--invoice-helper", version: 1 }));
    expect(mocks.replace).toHaveBeenCalledWith("/studio/agents/org-a1--invoice-helper");
  });

  it("adds a skill and switches to the fast model", async () => {
    renderWithIntl(<AgentEditor />);
    await fillIn();
    await userEvent.click(screen.getByRole("button", { name: "Fast model" }));
    await userEvent.click(screen.getByRole("button", { name: "Add a skill" }));
    await userEvent.type(screen.getByLabelText("Skill 1 title"), "Find open invoices");
    await userEvent.type(screen.getByLabelText("Skill 1 text"), "List the open ones.");
    await save();
    expect(mocks.create.mutate.mock.calls[0][0].body).toMatchObject({
      modelProfile: "fast",
      skills: [{ title: "Find open invoices", text: "List the open ones." }],
    });
  });

  it("moves focus to a new skill's title, and to the heading when one is removed", async () => {
    editing();
    await userEvent.click(screen.getByRole("button", { name: "Add a skill" }));
    expect(screen.getByLabelText("Skill 2 title")).toHaveFocus();
    await userEvent.type(screen.getByLabelText("Skill 2 title"), "Second");
    await userEvent.click(screen.getByRole("button", { name: "Remove skill 1" }));
    expect(screen.getByRole("heading", { name: "Skills" })).toHaveFocus();
    // The remaining row keeps its own values, not the removed row's.
    expect(screen.getByLabelText("Skill 1 title")).toHaveValue("Second");
    expect(screen.queryByLabelText("Skill 2 title")).toBeNull();
  });

  it("keeps the turns field editable and settles it to a whole number from 1 to 20", async () => {
    renderWithIntl(<AgentEditor />);
    await fillIn();
    const turns = screen.getByLabelText("Most tool calls per step");
    // The range and the usual setting are read with the field.
    expect(turns).toHaveAccessibleDescription(/from 1 to 20\. The usual setting is 6\./);
    await userEvent.clear(turns);
    expect(turns).toHaveValue(null);
    await userEvent.type(turns, "2.6");
    await userEvent.tab();
    expect(turns).toHaveValue(3);
    await userEvent.clear(turns);
    await userEvent.type(turns, "99");
    await save();
    expect(mocks.create.mutate.mock.calls[0][0].body).toMatchObject({ maxTurns: 20 });
  });

  it("saves an existing agent against the version it opened, and stays on the page", async () => {
    editing();
    expect(screen.getByText("Version 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fast model" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.type(screen.getByLabelText("Name"), " v2");
    await save();
    expect(mocks.save.mutate.mock.calls[0][0]).toEqual({
      path: { org_id: "org_a1", key: "org-a1--invoice-helper" },
      body: {
        draft: expect.objectContaining({ name: "Invoice helper v2", tools: ["stripe.list_invoices"] }),
        baseVersion: 3,
      },
    });
    act(() => saveHandlers().onSuccess({ ...AGENT, version: 4 }));
    expect(screen.getByText("Version 4")).toBeInTheDocument();
    expect(mocks.replace).not.toHaveBeenCalled();
    expect(mocks.toast).toHaveBeenCalledWith("Agent saved", "Version 4 is saved.");
  });

  it("lists each problem the API reports, and marks the field it names", async () => {
    renderWithIntl(<AgentEditor />);
    await fillIn();
    await pickStripe();
    await save();
    const issues = [
      { kind: "studio", key: "", path: "tools[0]", message: "An agent may only read." },
      { kind: "studio", key: "", path: "name", message: "Another agent is called that." },
    ];
    act(() => createHandlers().onError(new ApiError(422, "INVALID_DEFINITION", "2 problems", issues)));
    expect(screen.getByRole("alert")).toHaveTextContent("2 problems to fix");
    // Once in the summary, once under the field.
    expect(screen.getAllByText("An agent may only read.")).toHaveLength(2);
    expect(screen.getByRole("checkbox", { name: /Stripe: List invoices/ })).toHaveAttribute("aria-invalid", "true");
    const name = screen.getByLabelText("Name");
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription("Another agent is called that.");
    expect(screen.getByLabelText("Summary")).not.toHaveAttribute("aria-invalid");
  });

  it("names a pack the change would break once, with each of its messages as sent", async () => {
    editing();
    await save();
    const issues = [
      { kind: "pack", key: "Overdue invoice follow-up", path: "nodes[3]", message: "Step plan: schema mismatch." },
      { kind: "pack", key: "Overdue invoice follow-up", path: "nodes[6]", message: "Step draft: no such input." },
    ];
    act(() => saveHandlers().onError(new ApiError(422, "INVALID_DEFINITION", "2 problems", issues)));
    expect(screen.getByRole("alert")).toHaveTextContent("2 problems to fix");
    expect(screen.getAllByText("Overdue invoice follow-up would not work with this agent")).toHaveLength(1);
    expect(screen.getByText("Step plan: schema mismatch.")).toBeInTheDocument();
    expect(screen.getByText("Step draft: no such input.")).toBeInTheDocument();
    // A pack's key is its name, never a field: nothing in the form is marked invalid.
    expect(screen.getByLabelText("Name")).not.toHaveAttribute("aria-invalid");
  });

  it("keeps a version conflict on the page until the latest version is loaded", async () => {
    editing();
    await save();
    const detail = "Version 4 was saved since you opened version 3. Copy your changes, reload, and apply them again.";
    act(() => saveHandlers().onError(new ApiError(409, "VERSION_CONFLICT", detail)));
    // Our words first, so a Japanese reader is not left with the API's English alone; its detail beneath.
    expect(screen.getByText(/Someone saved a newer version since you opened this one/)).toBeInTheDocument();
    expect(screen.getByText(detail)).toBeInTheDocument();
    expect(screen.getByText("A newer version was saved")).toBeInTheDocument();
    expect(mocks.toast).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Load the latest version" }));
    expect(mocks.refetch).toHaveBeenCalledTimes(1);
  });

  it("explains a version conflict in Japanese", async () => {
    mocks.agent = { ...ok(AGENT), refetch: mocks.refetch };
    renderWithIntl(<AgentEditor agentKey={AGENT.key} />, { locale: "ja" });
    await userEvent.click(screen.getByRole("button", { name: "エージェントを保存" }));
    act(() => saveHandlers().onError(new ApiError(409, "VERSION_CONFLICT", "Version 4 was saved since.")));
    expect(screen.getByText(/別の人が新しいバージョンを保存しました/)).toBeInTheDocument();
    expect(screen.getByText("Version 4 was saved since.")).toBeInTheDocument();
  });

  it("marks unsaved changes, asks before an in-app link is followed, and clears both once saved", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    mocks.agent = { ...ok(AGENT), refetch: mocks.refetch };
    renderWithIntl(
      <>
        <a href="/elsewhere" onClick={(e) => e.preventDefault()}>
          Agents
        </a>
        <AgentEditor agentKey={AGENT.key} />
      </>,
    );
    expect(screen.queryByText("Unsaved changes")).toBeNull();
    await userEvent.click(screen.getByRole("link", { name: "Agents" }));
    expect(confirm).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Name"), " v2");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Agents" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    await save();
    act(() => saveHandlers().onSuccess({ ...AGENT, version: 4 }));
    expect(screen.queryByText("Unsaved changes")).toBeNull();
    await userEvent.click(screen.getByRole("link", { name: "Agents" }));
    expect(confirm).toHaveBeenCalledTimes(1);
    confirm.mockRestore();
  });

  it("keeps unsaved edits through a background refetch, and loads the latest version only when asked", async () => {
    const { rerender } = editing();
    await userEvent.type(screen.getByLabelText("Name"), " v2");
    // Someone else saved: the cache moves to version 5 while this form is being edited.
    const newer = { ...AGENT, version: 5, draft: { ...AGENT.draft, name: "Renamed elsewhere" } };
    mocks.agent = { ...ok(newer), refetch: mocks.refetch };
    rerender(<AgentEditor agentKey={AGENT.key} />);
    expect(screen.getByLabelText("Name")).toHaveValue("Invoice helper v2");
    expect(screen.getByText("Version 3")).toBeInTheDocument();
    expect(screen.getByText("A newer version was saved")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Load the latest version" }));
    expect(mocks.refetch).toHaveBeenCalledTimes(1);
    expect(await screen.findByDisplayValue("Renamed elsewhere")).toBeInTheDocument();
    expect(screen.getByText("Version 5")).toBeInTheDocument();
    expect(screen.queryByText("A newer version was saved")).toBeNull();
  });

  it("keeps the edits and says so when loading the latest version fails", async () => {
    mocks.refetch.mockResolvedValueOnce({ isError: true, error: new Error("offline") });
    const { rerender } = editing();
    await userEvent.type(screen.getByLabelText("Name"), " v2");
    const newer = { ...AGENT, version: 5, draft: { ...AGENT.draft, name: "Renamed elsewhere" } };
    mocks.agent = { ...ok(newer), refetch: mocks.refetch };
    rerender(<AgentEditor agentKey={AGENT.key} />);
    await userEvent.click(screen.getByRole("button", { name: "Load the latest version" }));
    expect(mocks.refetch).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith(
        "The latest version could not be loaded",
        "Something went wrong.",
        "blocked",
      ),
    );
    expect(screen.getByLabelText("Name")).toHaveValue("Invoice helper v2");
    expect(screen.getByText("Version 3")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Renamed elsewhere")).toBeNull();
  });

  it("keeps a tool's error with the tool when an earlier one is unticked", async () => {
    editing({ ...AGENT, draft: { ...AGENT.draft, tools: ["hubspot.list_deals", "stripe.list_invoices"] } });
    await save();
    const issue = { kind: "studio", key: "", path: "tools[1]", message: "Stripe is not connected." };
    act(() => saveHandlers().onError(new ApiError(422, "INVALID_DEFINITION", "1 problem", [issue])));
    const stripe = () => screen.getByRole("checkbox", { name: /Stripe: List invoices/ });
    expect(stripe()).toHaveAttribute("aria-invalid", "true");
    await userEvent.click(screen.getByRole("checkbox", { name: /hubspot\.list_deals/ }));
    expect(stripe()).toHaveAttribute("aria-invalid", "true");
    expect(stripe()).toHaveAccessibleDescription("Stripe is not connected.");
  });

  it("says plainly that only an owner or admin may save", async () => {
    renderWithIntl(<AgentEditor />);
    await fillIn();
    await save();
    act(() => createHandlers().onError(new ApiError(403, "FORBIDDEN", "require_builder: role member")));
    expect(mocks.toast).toHaveBeenCalledWith(
      "The agent was not saved",
      "Only an owner or admin can build agents. Ask one of them to save it.",
      "blocked",
    );
  });

  it("keeps a chosen tool the registry no longer offers, so it can be removed", async () => {
    editing({ ...AGENT, draft: { ...AGENT.draft, tools: ["stripe.list_invoices", "hubspot.list_deals"] } });
    const gone = screen.getByRole("checkbox", { name: /hubspot\.list_deals/ });
    expect(gone).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText(/No longer available/)).toBeInTheDocument();
    await userEvent.click(gone);
    await save();
    expect(mocks.save.mutate.mock.calls[0][0].body.draft.tools).toEqual(["stripe.list_invoices"]);
  });

  it("stops at twelve tools", async () => {
    const twelve = Array.from({ length: 12 }, (_, i) => `app.tool_${i}`);
    editing({ ...AGENT, draft: { ...AGENT.draft, tools: twelve } });
    expect(screen.getByText(/Up to 12 tools\./)).toBeInTheDocument();
    await openApp("Stripe");
    const stripe = screen.getByRole("checkbox", { name: /Stripe: List invoices/ });
    await userEvent.click(stripe);
    expect(stripe).toHaveAttribute("aria-checked", "false");
  });

  it("says when an agent key is not one of the org's", () => {
    mocks.agent = {
      isPending: false,
      isError: true,
      error: new ApiError(404, "NOT_FOUND", "No such agent"),
      data: undefined,
    };
    renderWithIntl(<AgentEditor agentKey="org-zz--secret" />);
    expect(screen.getByText(/^There is no agent of yours at this address/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to agents" })).toHaveAttribute("href", "/studio/agents");
    expect(screen.queryByLabelText("Name")).toBeNull();
  });

  it("lets a member read an agent but not change or save it", async () => {
    mocks.role = "member";
    editing();
    expect(screen.getByLabelText("Name")).toHaveValue("Invoice helper");
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Fast model" })).toBeDisabled();
    // A member can still open an app to see its tools. The checkbox is a span, outside the fieldset's reach: a
    // click must change nothing.
    await openApp("Stripe");
    const box = screen.getByRole("checkbox", { name: /Stripe: List invoices/ });
    await userEvent.click(box);
    expect(box).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByRole("button", { name: "Save agent" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Add a skill" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Remove skill/ })).toBeNull();
    expect(screen.getByText("Only owners and admins can build agents and packs.")).toBeInTheDocument();
  });

  it("shows a member a notice instead of the new agent form", () => {
    mocks.role = "member";
    renderWithIntl(<AgentEditor />);
    expect(screen.getByText("Only owners and admins can build agents and packs.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to agents" })).toHaveAttribute("href", "/studio/agents");
    expect(screen.queryByLabelText("Name")).toBeNull();
  });

  it("offers New agent on the list to owners and admins only", () => {
    mocks.role = "member";
    const { unmount } = renderWithIntl(
      <>
        <NewAgentLink />
        <AgentsList />
      </>,
    );
    expect(screen.queryByRole("link", { name: "New agent" })).toBeNull();
    expect(screen.getByText("No agents yet. An owner or admin can build one.")).toBeInTheDocument();
    unmount();
    mocks.role = "admin";
    renderWithIntl(
      <>
        <NewAgentLink />
        <AgentsList />
      </>,
    );
    expect(screen.getAllByRole("link", { name: "New agent" })).toHaveLength(2);
    expect(screen.getByText("No agents yet.")).toBeInTheDocument();
  });

  it("does not save the agent when Enter is pressed in the tool search", async () => {
    editing();
    const search = screen.getByLabelText("Search tools");
    await userEvent.type(search, "invoices{Enter}");
    expect(mocks.save.mutate).not.toHaveBeenCalled();
    // Each app's toggle names the list it expands.
    const stripe = screen.getByRole("button", { name: /^Stripe / });
    const controls = stripe.getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    expect(document.getElementById(controls!)).toContainElement(
      screen.getByRole("checkbox", { name: /Stripe: List invoices/ }),
    );
  });

  it("folds the tools by app, finds one by search, and summarises what is chosen", async () => {
    editing();
    // What is chosen comes first, each with its own remove button; the apps stay folded until opened.
    expect(screen.getByRole("list", { name: "Chosen tools" })).toHaveTextContent("Stripe: List invoices");
    expect(screen.getByText("1 of 12 chosen")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /Stripe: List invoices/ })).toBeNull();
    const stripe = screen.getByRole("button", { name: /^Stripe / });
    expect(stripe).toHaveAttribute("aria-expanded", "false");
    expect(stripe).toHaveTextContent("1 tool · 1 chosen");
    await userEvent.click(stripe);
    expect(screen.getByRole("checkbox", { name: /Stripe: List invoices/ })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(stripe);
    expect(screen.queryByRole("checkbox", { name: /Stripe: List invoices/ })).toBeNull();
    // A search opens every app it matches and leaves out the rest.
    const search = screen.getByLabelText("Search tools");
    await userEvent.type(search, "invoices");
    expect(screen.getByRole("checkbox", { name: /Stripe: List invoices/ })).toBeInTheDocument();
    await userEvent.clear(search);
    await userEvent.type(search, "nothing here");
    expect(screen.getByText("No tools match “nothing here”.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Stripe / })).toBeNull();
    // Removing a tool from the summary unticks it.
    await userEvent.click(screen.getByRole("button", { name: "Remove Stripe: List invoices" }));
    expect(screen.getByText("0 of 12 chosen")).toBeInTheDocument();
    expect(screen.getByText(/No tools chosen yet/)).toBeInTheDocument();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("speaks Japanese", () => {
    renderWithIntl(<AgentEditor />, { locale: "ja" });
    expect(screen.getByRole("button", { name: "推論モデル" })).toBeInTheDocument();
  });
});
