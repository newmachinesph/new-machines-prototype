import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Profiler, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import type { Palette, PaletteTool } from "@/lib/api/gen/types.gen";
import { createEditorStore, EditorStoreContext, type EditorStore } from "@/lib/builder/store";
import { OVERDUE, PALETTE } from "@/lib/builder/test-fixtures";
import { renderWithIntl } from "@/test/intl";
import { StepSettings } from "./step-settings";

vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => vi.fn(),
}));

/** A made-up read tool with the argument shapes the connector definitions use: a nested object, a list, an enum. */
const CHARGES: PaletteTool = {
  ref: "stripe.list_charges",
  app: "Stripe",
  name: "List charges",
  description: "Stripe list_charges",
  actionClass: "read",
  capability: "charges.read",
  inputSchema: {
    type: "object",
    additionalProperties: false,
    required: ["created"],
    properties: {
      created: {
        type: "object",
        additionalProperties: false,
        description: "When the charge was made.",
        required: ["gte"],
        properties: { gte: { type: "integer", minimum: 0 }, lte: { type: "integer" } },
      },
      tags: { type: "array", items: { type: "string" } },
      status: { type: "string", enum: ["succeeded", "pending", "failed"] },
      limit: { type: "integer", minimum: 1, maximum: 100 },
    },
  },
};
/** A made-up read tool whose schema is open: it names one field and accepts any other. */
const OPEN: PaletteTool = {
  ref: "notion.search",
  app: "Notion",
  name: "Search",
  description: "Notion search",
  actionClass: "read",
  capability: "pages.read",
  inputSchema: { type: "object", properties: { query: { type: "string" } } },
};
/** An open schema that names nothing at all. */
const OPEN_EMPTY: PaletteTool = { ...OPEN, ref: "notion.me", name: "Me", inputSchema: { type: "object" } };
const WITH_TOOLS: Palette = { ...PALETTE, tools: [...PALETTE.tools, CHARGES, OPEN, OPEN_EMPTY] };

function renderSettings(
  select: string | null,
  prepare?: (store: EditorStore) => void,
  palette = PALETTE,
  wrap: (ui: ReactNode) => ReactNode = (ui) => ui,
) {
  const store = createEditorStore({ draft: OVERDUE, palette });
  prepare?.(store);
  store.getState().select(select);
  renderWithIntl(<EditorStoreContext.Provider value={store}>{wrap(<StepSettings />)}</EditorStoreContext.Provider>);
  return store;
}
const configOf = (store: EditorStore, id: string) => store.getState().nodes.find((n) => n.id === id)?.data.config;
const rulesOf = (store: EditorStore, id: string) => store.getState().nodes.find((n) => n.id === id)?.data.rules;
const edgeTarget = (store: EditorStore, id: string) => store.getState().edges.find((e) => e.id === id)?.target;
const useTool = (id: string, tool: string, args: Record<string, unknown>) => (store: EditorStore) =>
  store.getState().updateStep(id, { config: { tool, args } });

describe("StepSettings", () => {
  it("asks to choose a step when none is selected", () => {
    renderSettings(null);
    expect(screen.getByText(/Choose a step/)).toBeInTheDocument();
  });

  it("records typing in a field as one undo step", async () => {
    const store = renderSettings("review");
    const title = screen.getByLabelText("Title (required)");
    await userEvent.clear(title);
    await userEvent.type(title, "Check the plan");
    await userEvent.tab();
    expect(configOf(store, "review")?.title).toBe("Check the plan");
    expect(store.getState().history.past).toHaveLength(1);
  });

  it("offers the earlier steps' fields for an expression", async () => {
    const store = renderSettings("review");
    await userEvent.click(screen.getByRole("button", { name: /into What the reviewer sees/ }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /plan · Messages/ }));
    expect(configOf(store, "review")?.show).toBe("=nodes.plan.output.messages");
  });

  it("draws a tool's arguments from its input schema and keeps numbers as numbers", () => {
    const store = renderSettings("invoices");
    fireEvent.change(screen.getByLabelText("limit"), { target: { value: "50" } });
    expect(configOf(store, "invoices")?.args).toEqual({ status: "open", limit: 50 });
  });

  it("marks required arguments, and lists a setting a closed schema does not have with a way to remove it", async () => {
    const store = renderSettings("send", (store) =>
      store.getState().updateStep("send", {
        config: { ...configOf(store, "send"), args: { recipient_email: "=item.to", extra: { a: 1 } } },
      }),
    );
    expect(screen.getByLabelText("recipient_email (required)")).toHaveValue("=item.to");
    expect(screen.getByLabelText("subject (required)")).toHaveValue("");
    const unknown = screen.getByLabelText("extra (unknown setting)");
    expect(unknown).toHaveValue('{"a":1}');
    expect(unknown).toHaveAccessibleDescription(/does not have this setting/);
    await userEvent.click(screen.getByRole("button", { name: "Remove extra" }));
    expect(configOf(store, "send")?.args).toEqual({ recipient_email: "=item.to" });
  });

  it("lets an open schema's extra settings be edited and added, and says when a tool really takes none", async () => {
    const store = renderSettings(
      "invoices",
      useTool("invoices", "notion.search", { query: "x", icon: "y" }),
      WITH_TOOLS,
    );
    expect(screen.queryByText(/unknown setting/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("query")).toHaveValue("x");
    expect(screen.getByLabelText("Name of setting 1")).toHaveValue("icon");
    expect(screen.getByLabelText("Setting 1")).toHaveValue("y");
    await userEvent.click(screen.getByRole("button", { name: "Add a setting" }));
    expect(configOf(store, "invoices")?.args).toEqual({ query: "x", icon: "y", setting_1: "" });

    act(() => useTool("invoices", "notion.me", {})(store));
    expect(screen.queryByText(/takes no settings/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a setting" })).toBeInTheDocument();

    act(() => useTool("invoices", "stripe.refund_charge", {})(store));
    expect(screen.getByText(/takes no settings/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a setting" })).not.toBeInTheDocument();
  });

  it("says that a tool's settings given as one expression cannot be saved", () => {
    const store = renderSettings("send", (store) =>
      store.getState().updateStep("send", { config: { tool: "gmail.create_draft", args: "=input.args" } }),
    );
    expect(screen.getByLabelText("Tool settings")).toHaveValue("=input.args");
    expect(screen.getByLabelText("Tool settings")).toHaveAccessibleDescription(/cannot be saved/);
    expect(configOf(store, "send")?.args).toBe("=input.args");
  });

  it("draws an object argument as nested fields, with a number's range, and reads a list as JSON when left", async () => {
    const store = renderSettings("invoices", useTool("invoices", "stripe.list_charges", {}), WITH_TOOLS);
    expect(screen.getByRole("group", { name: "created (required)" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("gte (required)"), { target: { value: "5" } });
    expect(configOf(store, "invoices")?.args).toEqual({ created: { gte: 5 } });
    expect(screen.getByLabelText("limit")).toHaveAccessibleDescription(/Between 1 and 100/);

    const tags = screen.getByLabelText("tags");
    fireEvent.change(tags, { target: { value: '["a", "b"]' } });
    expect(configOf(store, "invoices")?.args).toEqual({ created: { gte: 5 } });
    fireEvent.blur(tags);
    expect(configOf(store, "invoices")?.args).toEqual({ created: { gte: 5 }, tags: ["a", "b"] });
    expect(screen.getByLabelText("tags")).toHaveValue('["a","b"]');

    fireEvent.change(screen.getByLabelText("tags"), { target: { value: "nope" } });
    fireEvent.blur(screen.getByLabelText("tags"));
    expect(screen.getByRole("alert")).toHaveTextContent(/JSON list/);
    expect(configOf(store, "invoices")?.args).toEqual({ created: { gte: 5 }, tags: ["a", "b"] });

    fireEvent.change(screen.getByLabelText("tags"), { target: { value: "=nodes.plan.output.rows" } });
    fireEvent.blur(screen.getByLabelText("tags"));
    expect(configOf(store, "invoices")?.args).toEqual({ created: { gte: 5 }, tags: "=nodes.plan.output.rows" });
  });

  it("draws an enum argument as a choice that can also be left unset", async () => {
    const store = renderSettings(
      "invoices",
      useTool("invoices", "stripe.list_charges", { status: "pending" }),
      WITH_TOOLS,
    );
    const status = screen.getByRole("combobox", { name: "status" });
    expect(status).toHaveTextContent("pending");
    await userEvent.click(status);
    await userEvent.click(await screen.findByRole("option", { name: "Not set" }));
    expect(configOf(store, "invoices")?.args).toEqual({});
    expect(screen.getByRole("combobox", { name: "status" })).toHaveTextContent("Not set");
  });

  it("renames an agent's input when the field is left, keeping its value and refusing a name in use", async () => {
    const store = renderSettings("plan");
    const name = screen.getByLabelText("Name of value 1");
    expect(name).toHaveValue("invoices");
    fireEvent.change(name, { target: { value: "rules" } });
    expect(Object.keys(configOf(store, "plan")?.inputs as object)).toEqual(["invoices", "as_of", "rules"]);
    fireEvent.blur(name);
    expect(screen.getByRole("alert")).toHaveTextContent(/Another value/);
    expect(Object.keys(configOf(store, "plan")?.inputs as object)).toEqual(["invoices", "as_of", "rules"]);
    fireEvent.change(name, { target: { value: "bills" } });
    fireEvent.keyDown(name, { key: "Enter" });
    expect(configOf(store, "plan")?.inputs).toEqual({
      bills: "=nodes.invoices.output",
      as_of: "=input.as_of",
      rules: "=memory",
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renames a step, refusing a name that is not a step id", async () => {
    const store = renderSettings("plan");
    const name = screen.getByLabelText("Step name");
    await userEvent.clear(name);
    await userEvent.type(name, "Plan");
    await userEvent.tab();
    expect(screen.getByRole("alert")).toHaveTextContent(/lowercase letters/);
    await userEvent.clear(screen.getByLabelText("Step name"));
    await userEvent.type(screen.getByLabelText("Step name"), "plan_b{Enter}");
    expect(store.getState().selectedId).toBe("plan_b");
    expect(screen.getByLabelText("Step name")).toHaveValue("plan_b");
  });

  it("keeps keyboard focus in the panel when a renamed step is left with Tab or committed with Enter", async () => {
    const store = renderSettings("plan");
    const name = screen.getByLabelText("Step name");
    await userEvent.clear(name);
    await userEvent.type(name, "plan_b");
    await userEvent.tab();
    expect(store.getState().selectedId).toBe("plan_b");
    // Tab went on to the next field of the panel, and the rename did not take it away.
    expect(document.body).not.toHaveFocus();
    expect(screen.getByLabelText("Step name")).not.toHaveFocus();
    expect(screen.getByLabelText("Step name")).toHaveValue("plan_b");
    await userEvent.clear(screen.getByLabelText("Step name"));
    await userEvent.type(screen.getByLabelText("Step name"), "plan_c{Enter}");
    expect(store.getState().selectedId).toBe("plan_c");
    expect(screen.getByLabelText("Step name")).toHaveFocus();
    // Choosing another step still starts the panel afresh.
    act(() => store.getState().select("review"));
    expect(screen.getByLabelText("Step name")).toHaveValue("review");
  });

  it("offers no Remove for the only start step", () => {
    const store = renderSettings("start");
    expect(screen.queryByRole("button", { name: "Remove step" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Duplicate step" })).toBeNull();
    act(() => {
      store.getState().addStep({ type: "trigger", config: {} });
      store.getState().select("start");
    });
    expect(screen.getByRole("button", { name: "Remove step" })).toBeInTheDocument();
  });

  it("edits a decision's rules and keeps a renamed route's edge", () => {
    const store = renderSettings("check");
    expect(screen.getByDisplayValue("Are there overdue invoices to follow up?")).toBeInTheDocument();
    const route = screen.getByLabelText("Route name for rule 1");
    expect(route).toHaveAccessibleDescription(/An outcome on the canvas/);
    fireEvent.change(route, { target: { value: "none_due" } });
    fireEvent.blur(route);
    expect(edgeTarget(store, "check:none_due")).toBe("nothing");
  });

  it("commits a route rename when the field is left, so a name passed through on the way does not drop an edge", async () => {
    const store = renderSettings("check");
    const route = screen.getByLabelText("Route name for rule 1");
    await userEvent.clear(route);
    // On the way to "human_review_2" the text equals the default route's name.
    await userEvent.type(route, "human_review_2");
    expect(edgeTarget(store, "check:nothing")).toBe("nothing");
    await userEvent.tab();
    expect(edgeTarget(store, "check:human_review_2")).toBe("nothing");
    expect(edgeTarget(store, "check:human_review")).toBe("review");
    expect(store.getState().edges.filter((e) => e.source === "check")).toHaveLength(2);
  });

  it("lets two rules share a route, and says so without blocking", () => {
    const store = renderSettings("check");
    const route = screen.getByLabelText("Route name for rule 1");
    fireEvent.change(route, { target: { value: "human_review" } });
    fireEvent.blur(route);
    expect(rulesOf(store, "check")?.rules?.[0].route).toBe("human_review");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(route).toHaveAccessibleDescription(/leads to this route too/);
  });

  it("keeps a rule's half-typed route with its rule when an earlier rule is removed", async () => {
    const store = renderSettings("check", (store) => {
      const rules = rulesOf(store, "check")!;
      store.getState().updateStep("check", {
        rules: {
          ...rules,
          rules: [...rules.rules!, { when: "true", route: "route_1", verdict: "APPROVED", explanation: "x" }],
        },
      });
    });
    expect(screen.getByLabelText("Route name for rule 2")).toHaveValue("route_1");
    fireEvent.change(screen.getByLabelText("Route name for rule 2"), { target: { value: "pending_x" } });
    fireEvent.click(screen.getByRole("button", { name: "Remove rule 1" }));
    expect(rulesOf(store, "check")?.rules).toHaveLength(1);
    expect(screen.getByLabelText("Route name for rule 1")).toHaveValue("pending_x");
  });

  it("gives a new rule the first free route name", async () => {
    const store = renderSettings("check", (store) => {
      const rules = rulesOf(store, "check")!;
      // One rule already named like the second rule would be: the new one must not take the same name.
      store.getState().updateStep("check", { rules: { ...rules, rules: [{ ...rules.rules![0], route: "route_2" }] } });
    });
    await userEvent.click(screen.getByRole("button", { name: "Add a rule" }));
    expect(rulesOf(store, "check")?.rules?.map((r) => r.route)).toEqual(["route_2", "route_1"]);
  });

  it("starts a new decision from an example", async () => {
    const store = renderSettings(null);
    act(() => {
      store.getState().addStep({ type: "decision", config: {} });
    });
    await userEvent.click(screen.getByRole("button", { name: "Start from an example" }));
    expect(store.getState().nodes.find((n) => n.id === "check_2")?.data.rules?.question).toBe(
      "Does this need a person to look at it?",
    );
  });

  it("shows where each outcome goes, and duplicates and removes the step", async () => {
    const store = renderSettings("approve");
    // Targets read as the step list names them: number, kind of step, then the id.
    expect(screen.getByRole("combobox", { name: "granted goes to" })).toHaveTextContent(
      /^Step \d+: App step \(send\)$/,
    );
    act(() => {
      store.getState().select("draft");
      store.getState().copy();
      store.getState().select("approve");
    });
    const clipboard = store.getState().clipboard;
    await userEvent.click(screen.getByRole("button", { name: "Duplicate step" }));
    expect(store.getState().nodes.some((n) => n.id === "approve_2")).toBe(true);
    expect(store.getState().clipboard).toBe(clipboard);
    // The copy is selected and its name is ready to be changed.
    expect(screen.getByLabelText("Step name")).toHaveValue("approve_2");
    expect(screen.getByLabelText("Step name")).toHaveFocus();
    act(() => store.getState().select("approve"));
    await userEvent.click(screen.getByRole("button", { name: "Remove step" }));
    expect(store.getState().nodes.some((n) => n.id === "approve")).toBe(false);
  });

  it("is disabled as a whole inside a disabled fieldset, choices included", () => {
    renderSettings("approve", undefined, PALETTE, (ui) => <fieldset disabled>{ui}</fieldset>);
    expect(screen.getByLabelText("Title (required)")).toBeDisabled();
    const choice = screen.getByRole("combobox", { name: "granted goes to" });
    expect(choice).toBeDisabled();
    expect(choice).toHaveClass("disabled:opacity-60");
  });

  it("does not redraw while a step is dragged", () => {
    const onRender = vi.fn();
    const store = renderSettings("review", undefined, PALETTE, (ui) => (
      <Profiler id="settings" onRender={onRender}>
        {ui}
      </Profiler>
    ));
    const before = onRender.mock.calls.length;
    act(() => {
      store.getState().onNodesChange([{ type: "position", id: "review", position: { x: 10, y: 10 }, dragging: true }]);
      store.getState().onNodesChange([{ type: "position", id: "plan", position: { x: 20, y: 10 }, dragging: true }]);
    });
    expect(onRender.mock.calls.length).toBe(before);
    // A change to what the step can read does redraw it.
    act(() => store.getState().updateStep("plan", { config: { ...configOf(store, "plan"), task: "x" } }));
    expect(onRender.mock.calls.length).toBeGreaterThan(before);
  });

  it("offers the loop's item only to the tool's settings of a repeating app step", async () => {
    renderSettings("send");
    await userEvent.click(screen.getByRole("button", { name: /into subject \(required\)/ }));
    expect(await screen.findByRole("menuitem", { name: /item\.subject/ })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    // The list being walked cannot read its own item.
    await userEvent.click(screen.getByRole("button", { name: /into Repeat for each item in/ }));
    await screen.findByRole("menuitem", { name: /draft · Drafts/ });
    expect(screen.queryByRole("menuitem", { name: /item\./ })).not.toBeInTheDocument();
  });
});
