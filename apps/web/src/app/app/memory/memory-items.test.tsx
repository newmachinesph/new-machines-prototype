import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import en from "../../../../messages/en.json";
import ja from "../../../../messages/ja.json";
import { MemoryBoard } from "./memory-items";

const data = vi.hoisted(() => ({ rows: [] as unknown[] }));
const m = vi.hoisted(() => ({ retract: vi.fn(), review: vi.fn(), toast: vi.fn() }));

vi.mock("@/components/base", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/base")>()),
  useToast: () => m.toast,
}));
vi.mock("@/lib/queries/workspace", () => ({
  useMemory: () => ({ isPending: false, isError: false, data: data.rows }),
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
  for (const fn of Object.values(m)) fn.mockReset();
});

describe("MemoryBoard", () => {
  it("labels where a memory came from and what it applies to in plain words", () => {
    renderWithIntl(<MemoryBoard />);
    expect(screen.getByText("Set up with your workspace")).toBeInTheDocument();
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
    expect(screen.getByText("ワークスペースの初期設定")).toBeInTheDocument();
    expect(screen.getAllByText("適用先：Customer accounts policies")).toHaveLength(2);
  });

  // QA F-20: a new workspace starts with its packs' policies in use, which no person approved one by one.
  it("does not claim that every memory in use was approved by a person", () => {
    expect(en.memory.lede).not.toMatch(/Nothing becomes memory until a person approves it/);
    expect(en.memory.lede).toMatch(/policies your workspace started with/);
    expect(en.memory.lede).toMatch(/once a person approves it/);
    expect(ja.memory.lede).toMatch(/最初から/);
  });
});
