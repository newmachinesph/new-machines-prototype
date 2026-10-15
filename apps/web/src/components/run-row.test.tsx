import { screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { RunSummary } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { RunsBrowser } from "./run-row";

vi.mock("nuqs", () => ({
  parseAsString: { withDefault: (d: string) => ({ d }) },
  useQueryState: (_key: string, parser: { d: string }) => {
    const [v, set] = useState<string | null>(null);
    return [v ?? parser.d, set];
  },
}));
vi.mock("@/lib/queries/catalog", () => ({
  usePacks: () => ({ isPending: false, isError: false, data: [{ slug: "org-a1--nudges", name: "Invoice nudges" }] }),
}));

const zero = { amountMinor: 0, currency: "USD" as const };
const run = (id: string, over: Partial<RunSummary> = {}): RunSummary => ({
  id,
  packSlug: "org-a1--nudges",
  title: `Invoice nudges: ${id}`,
  status: "RUNNING",
  startedAt: "2026-10-13T09:00:00Z",
  startedBy: "Ana Reyes",
  spent: { ai: zero, human: zero, tools: zero },
  stages: { executed: "pending", verified: "pending", accepted: "pending", settlement: "pending" },
  summary: "Started.",
  hasDetail: true,
  ...over,
});

describe("RunsBrowser", () => {
  it("labels a sandbox test run and only that run", () => {
    renderWithIntl(<RunsBrowser runs={[run("run_1", { sandboxTest: true }), run("run_2")]} linkable={["run_1"]} />);
    expect(screen.getAllByText("Sandbox test")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Invoice nudges: run_1" })).toBeInTheDocument();
  });
});
