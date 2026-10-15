import { screen, within } from "@testing-library/react";
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

// The same runs are rendered twice: as cards for phones and as a table from md up. CSS hides one of them.
const table = () => within(screen.getByRole("table"));
const cards = () => within(screen.getByRole("list"));

describe("RunsBrowser", () => {
  it("labels a sandbox test run and only that run", () => {
    renderWithIntl(<RunsBrowser runs={[run("run_1", { sandboxTest: true }), run("run_2")]} linkable={["run_1"]} />);
    expect(table().getAllByText("Sandbox test")).toHaveLength(1);
    expect(table().getByRole("link", { name: "Invoice nudges: run_1" })).toBeInTheDocument();
  });

  it("explains the Outcome column only where the column is shown", () => {
    renderWithIntl(<RunsBrowser runs={[run("run_1")]} linkable={[]} />);
    expect(screen.getByText(/^Outcome shows the stage/)).toHaveClass("hidden", "md:inline");
    expect(screen.getByText(/Costs are simulated\./)).toBeInTheDocument();
  });

  it("renders each run as a card with its status, cost and time", () => {
    renderWithIntl(
      <RunsBrowser
        runs={[
          run("run_1", {
            status: "COMPLETED",
            endedAt: "2026-10-13T09:02:34Z",
            spent: { ai: { amountMinor: 318, currency: "USD" }, human: zero, tools: zero },
          }),
        ]}
        linkable={["run_1"]}
      />,
    );
    const card = cards().getAllByRole("listitem");
    expect(card).toHaveLength(1);
    expect(within(card[0]).getByRole("link", { name: "Invoice nudges: run_1" })).toHaveAttribute(
      "href",
      "/app/runs/run_1",
    );
    expect(within(card[0]).getByText("Completed")).toBeInTheDocument();
    expect(within(card[0]).getByText("$3.18")).toBeInTheDocument();
    expect(within(card[0]).getByText("2m 34s")).toBeInTheDocument();
  });

  it("names the pack once, and only when it differs from the title", () => {
    renderWithIntl(
      <RunsBrowser
        runs={[run("run_1", { title: "Invoice nudges" }), run("run_2", { title: "October chase" })]}
        linkable={[]}
      />,
    );
    expect(table().getAllByText("Invoice nudges")).toHaveLength(2); // run_1's title and run_2's pack line
    expect(table().getByText("run_1")).toBeInTheDocument();
  });

  it("sums the outcome up as the stage the run is at, leaving out stages it does not need", () => {
    renderWithIntl(
      <RunsBrowser
        runs={[
          run("run_1", {
            stages: {
              executed: "done",
              verified: "not_required",
              accepted: "not_required",
              settlement: "not_required",
            },
          }),
          run("run_2", {
            stages: { executed: "done", verified: "pending", accepted: "pending", settlement: "not_required" },
          }),
          run("run_3", {
            stages: { executed: "done", verified: "done", accepted: "not_required", settlement: "blocked" },
          }),
        ]}
        linkable={[]}
      />,
    );
    expect(table().getByText("Executed")).toBeInTheDocument();
    expect(table().getByText("Verified: Not yet")).toBeInTheDocument();
    expect(table().getByText("Settlement eligible: On hold")).toBeInTheDocument();
    expect(screen.queryByText(/Not required/)).not.toBeInTheDocument();
  });
});
