import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import en from "../../../../messages/en.json";
import ja from "../../../../messages/ja.json";
import { MemoryBoard } from "./memory-items";

const SPACES = [
  { id: "retail-commerce", name: "Retail & Commerce company knowledge" },
  { id: "customer-accounts", name: "Customer accounts policies" },
];
const loaded = { isPending: false, isError: false, data: SPACES };
const data = vi.hoisted(() => ({ rows: [] as unknown[], role: "owner", spaces: {} as object, adding: false }));
const m = vi.hoisted(() => ({ add: vi.fn(), retract: vi.fn(), review: vi.fn(), toast: vi.fn() }));

vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => m.toast,
}));
vi.mock("@/lib/queries/me", () => ({ useMe: () => ({ data: { role: data.role } }) }));
vi.mock("@/lib/queries/workspace", () => ({
  useMemory: () => ({ isPending: false, isError: false, data: data.rows }),
  useMemorySpaces: () => data.spaces,
  useAddMemory: () => ({ mutate: m.add, isPending: data.adding }),
  useRetractMemory: () => ({ mutate: m.retract, isPending: false }),
  useReviewMemory: () => ({ mutate: m.review, isPending: false }),
}));

const memory = (id: string, source: string, text = "Orders over $500 need a person to confirm.") => ({
  id,
  text,
  scope: "Organization",
  scopeName: "Customer accounts policies",
  state: "APPROVED",
  source,
  proposedBy: "seed",
  createdAt: "2026-10-13T14:56:00Z",
});

beforeEach(() => {
  data.rows = [memory("mem_1", "Definitions seed"), memory("mem_2", "Run run_2011", "Fees of 2.9% are expected.")];
  data.role = "owner";
  data.spaces = loaded;
  data.adding = false;
  for (const fn of Object.values(m)) fn.mockReset();
});

const openAddDialog = async () => {
  await userEvent.click(screen.getByRole("button", { name: "Add a memory" }));
  return screen.findByRole("dialog", { name: "Add a memory" });
};

describe("MemoryBoard", () => {
  it("labels where a memory came from and what it applies to in plain words", () => {
    renderWithIntl(<MemoryBoard />);
    expect(screen.getByText("Comes with a pack you added")).toBeInTheDocument();
    expect(screen.getByText("From run 2011")).toBeInTheDocument();
    expect(screen.getAllByText("Applies to Customer accounts policies")).toHaveLength(2);
    expect(screen.queryByText(/Definitions seed|Organization:/)).toBeNull();
  });

  // Two dialog interactions: slow under a parallel full run, so it gets more than the default 5s.
  it("retracts a memory from a real button, after confirming", { timeout: 20_000 }, async () => {
    renderWithIntl(<MemoryBoard />);
    const [retract] = screen.getAllByRole("button", { name: "Retract" });
    expect(retract.tagName).toBe("BUTTON");
    expect(retract).toHaveClass("text-blocked");
    await userEvent.click(retract);
    const dialog = await screen.findByRole("alertdialog", { name: "Retract this memory?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Retract memory" }));
    expect(m.retract).toHaveBeenCalledWith({ path: { memory_id: "mem_1" } }, expect.anything());
  });

  it("is translated", () => {
    renderWithIntl(<MemoryBoard />, { locale: "ja" });
    expect(screen.getByText("追加したパックに付属")).toBeInTheDocument();
    expect(screen.getAllByText("適用先：顧客アカウントのポリシー")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "メモリを追加" })).toBeInTheDocument();
  });

  it("reads a seed that comes with one of our packs in Japanese, and every other memory as stored", () => {
    const rule = "Orders over $500 need a person to confirm before they are reported as matched.";
    data.rows = [
      { ...memory("mem_1", "Definitions seed", rule), scopeName: "Retail & Commerce company knowledge" },
      { ...memory("mem_3", "Your team", rule), scopeName: "Retail & Commerce company knowledge" },
      memory("mem_2", "Run run_2011", "Fees of 2.9% are expected."),
    ];
    renderWithIntl(<MemoryBoard />, { locale: "ja" });
    expect(screen.getByText("$500を超える注文は、一致として報告する前に担当者の確認が必要です。")).toBeInTheDocument();
    expect(screen.getByText(rule)).toBeInTheDocument();
    expect(screen.getByText("Fees of 2.9% are expected.")).toBeInTheDocument();
  });

  it("labels a memory the team added", () => {
    data.rows = [memory("mem_3", "Your team", "Never refund an opened item.")];
    renderWithIntl(<MemoryBoard />);
    expect(screen.getByText("Added by your team")).toBeInTheDocument();
  });

  it("lets an owner add a memory to the first space, with the text trimmed", { timeout: 20_000 }, async () => {
    m.add.mockImplementation((_vars, opts) => opts?.onSuccess?.(memory("mem_9", "Your team")));
    renderWithIntl(<MemoryBoard />);
    const dialog = await openAddDialog();
    await userEvent.type(within(dialog).getByLabelText("Memory"), "  Never refund an opened item.  ");
    expect(within(dialog).getByText("32 of 2000 characters")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Save memory" }));
    expect(m.add).toHaveBeenCalledWith(
      { body: { space: "retail-commerce", text: "Never refund an opened item." } },
      expect.anything(),
    );
    expect(m.toast).toHaveBeenCalledWith("Memory added", "Your agents use it from their next run.");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("starts afresh after Cancel", { timeout: 20_000 }, async () => {
    renderWithIntl(<MemoryBoard />);
    let dialog = await openAddDialog();
    await userEvent.type(within(dialog).getByLabelText("Memory"), "Half a rule");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    dialog = await openAddDialog();
    expect(within(dialog).getByLabelText("Memory")).toHaveValue("");
    expect(within(dialog).getByText("0 of 2000 characters")).toBeInTheDocument();
  });

  it("returns focus to the trigger after Cancel and after a saved memory", { timeout: 20_000 }, async () => {
    m.add.mockImplementation((_vars, opts) => opts?.onSuccess?.(memory("mem_9", "Your team")));
    renderWithIntl(<MemoryBoard />);
    const trigger = screen.getByRole("button", { name: "Add a memory" });
    let dialog = await openAddDialog();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());

    dialog = await openAddDialog();
    await userEvent.type(within(dialog).getByLabelText("Memory"), "One rule.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save memory" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("says so the moment the text reaches the limit", { timeout: 20_000 }, async () => {
    renderWithIntl(<MemoryBoard />);
    const dialog = await openAddDialog();
    const limit = "That is the limit. Keep it to one rule.";
    const field = within(dialog).getByLabelText("Memory");
    await userEvent.click(field);
    await userEvent.paste("x".repeat(1999));
    expect(within(dialog).getByText("1999 of 2000 characters")).toBeInTheDocument();
    expect(within(dialog).queryByText(limit)).toBeNull();

    await userEvent.type(field, "x");
    expect(within(dialog).getByText("2000 of 2000 characters")).toBeInTheDocument();
    expect(within(dialog).getByText(limit)).toHaveAttribute("aria-live", "polite");
    expect(within(dialog).getByRole("button", { name: "Save memory" })).toBeEnabled();
  });

  it(
    "says it is saving, and keeps the draft when closed meanwhile so a failed save can be retried",
    { timeout: 20_000 },
    async () => {
      let fail = () => {};
      m.add.mockImplementation((_vars, opts) => {
        data.adding = true;
        fail = () =>
          opts?.onError?.({ title: "Service unavailable", status: 503, code: "UNAVAILABLE", detail: "Try again." });
      });
      const { rerender } = renderWithIntl(<MemoryBoard />);
      let dialog = await openAddDialog();
      await userEvent.type(within(dialog).getByLabelText("Memory"), "One rule.");
      await userEvent.click(within(dialog).getByRole("button", { name: "Save memory" }));
      rerender(<MemoryBoard />);
      const saving = within(dialog).getByRole("button", { name: "Saving…" });
      expect(saving).toBeDisabled();
      expect(saving.closest("form")).toHaveAttribute("aria-busy", "true");

      // The X still closes it (so does Escape); the text is not thrown away.
      await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      fail();
      data.adding = false;
      rerender(<MemoryBoard />);
      expect(m.toast).toHaveBeenCalledWith("Could not add memory", "Try again.", "blocked");

      dialog = await openAddDialog();
      expect(within(dialog).getByLabelText("Memory")).toHaveValue("One rule."); // back for another try
      expect(within(dialog).getByRole("button", { name: "Save memory" })).toBeEnabled();
      await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      dialog = await openAddDialog();
      expect(within(dialog).getByLabelText("Memory")).toHaveValue(""); // Cancel, not saving: afresh
    },
  );

  it("says when the text list of places cannot be loaded", { timeout: 20_000 }, async () => {
    data.spaces = { isPending: false, isError: true, data: undefined, error: new Error("down") };
    renderWithIntl(<MemoryBoard />);
    const dialog = await openAddDialog();
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "Could not load where a memory can apply. Close this and try again.",
    );
    expect(within(dialog).getByRole("button", { name: "Save memory" })).toBeDisabled();
  });

  it("says while the places load and when there are none", { timeout: 20_000 }, async () => {
    data.spaces = { isPending: true, isError: false, data: undefined };
    renderWithIntl(<MemoryBoard />);
    const dialog = await openAddDialog();
    expect(within(dialog).getByRole("status")).toHaveTextContent("Loading where a memory can apply…");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    data.spaces = { isPending: false, isError: false, data: [] };
    const again = await openAddDialog();
    expect(within(again).getByRole("status")).toHaveTextContent("Add a pack first. Memories apply to the work your packs do.");
  });

  it("does not save an empty memory", { timeout: 20_000 }, async () => {
    renderWithIntl(<MemoryBoard />);
    const dialog = await openAddDialog();
    const save = within(dialog).getByRole("button", { name: "Save memory" });
    expect(save).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText("Memory"), "   ");
    expect(save).toBeDisabled();
    await userEvent.click(save);
    expect(m.add).not.toHaveBeenCalled();
    await userEvent.type(within(dialog).getByLabelText("Memory"), "One rule.");
    expect(save).toBeEnabled();
  });

  it("says what failed when the memory is not added", { timeout: 20_000 }, async () => {
    const detail = "Your workspace has 100 memories added by your team. Retract one before adding another.";
    m.add.mockImplementation((_vars, opts) =>
      opts?.onError?.({ title: "Conflict", status: 409, code: "CONFLICT", detail }),
    );
    renderWithIntl(<MemoryBoard />);
    const dialog = await openAddDialog();
    const field = within(dialog).getByLabelText("Memory");
    await userEvent.type(field, "One rule.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save memory" }));
    expect(m.toast).toHaveBeenCalledWith("Could not add memory", detail, "blocked");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    // The text is kept for another try, and focus goes back to it.
    expect(field).toHaveValue("One rule.");
    await waitFor(() => expect(field).toHaveFocus());
  });

  it("does not offer a member the add action, with or without memories", () => {
    data.role = "member";
    const { unmount } = renderWithIntl(<MemoryBoard />);
    expect(screen.queryByRole("button", { name: "Add a memory" })).toBeNull();
    unmount();
    data.rows = [];
    renderWithIntl(<MemoryBoard />);
    expect(screen.getByText(/No memories yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a memory" })).toBeNull();
  });

  it("lets only owners and admins retract what the team added", () => {
    data.rows = [memory("mem_1", "Definitions seed"), memory("mem_3", "Your team", "Never refund an opened item.")];
    const { unmount } = renderWithIntl(<MemoryBoard />);
    expect(screen.getAllByRole("button", { name: "Retract" })).toHaveLength(2);
    unmount();
    data.role = "member";
    renderWithIntl(<MemoryBoard />);
    const [retract] = screen.getAllByRole("button", { name: "Retract" });
    expect(retract.closest("li")).toHaveTextContent("Comes with a pack you added");
    expect(screen.getByText("Never refund an opened item.").closest("li")).not.toContainElement(retract);
    expect(screen.getAllByRole("button", { name: "Retract" })).toHaveLength(1);
  });

  // QA F-20: the policies in use come with the packs a workspace added; no person approved them one by one.
  it("does not claim that every memory in use was approved by a person", () => {
    expect(en.memory.lede).not.toMatch(/Nothing becomes memory until a person approves it/);
    expect(en.memory.lede).toMatch(/policies that come with the packs you added/);
    expect(en.memory.lede).toMatch(/once a person approves it/);
    expect(ja.memory.lede).toMatch(/追加したパック/);
  });
});
