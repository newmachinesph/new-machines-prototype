import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { EarningsView } from "./earnings/earnings-view";
import WorkError from "./error";
import { WorkView } from "./work-view";

const ready = <T,>(data: T) => ({ isPending: false, isError: false, data });

const OPEN_TASKS = [
  {
    id: "ht_011",
    title: "Correct 3 order-to-payout exceptions",
    buyer: "A US home goods retailer",
    packName: "Order & Payment Reconciliation",
    skill: "Invoice review",
    mode: "CORRECTION",
    pay: { amountMinor: 750, currency: "USD" },
    estMinutes: 20,
    deadline: "2026-10-13T20:07:00Z",
    dataClass: "CONFIDENTIAL",
  },
];
const EARNINGS = [
  {
    taskId: "ht_009",
    title: "Quality audit, 5 reconciled orders",
    at: "2026-10-11T14:00:00Z",
    amount: { amountMinor: 750, currency: "USD" },
    status: "OWED",
    verdict: "APPROVED",
  },
];

const workspace = vi.hoisted(() => ({ demo: true }));
vi.mock("@/lib/queries/me", () => ({ useIsDemo: () => workspace.demo }));

const lists = vi.hoisted(() => ({ tasks: null as unknown[] | null, earnings: null as unknown[] | null }));
vi.mock("@/lib/queries/tasks", () => ({
  useEligibleTasks: () => ready(lists.tasks ?? OPEN_TASKS),
  useEarnings: () => ready(lists.earnings ?? EARNINGS),
}));

describe("reviewer portal views in Japanese", () => {
  it("translates the task list and keeps API text in English", () => {
    renderWithIntl(<WorkView />, { locale: "ja" });
    expect(screen.getByRole("heading", { name: "受けられるタスク" })).toBeInTheDocument();
    expect(screen.getByText("このデモの報酬は模擬です")).toBeInTheDocument();
    expect(screen.getByText("修正")).toBeInTheDocument();
    expect(screen.getByText("Correct 3 order-to-payout exceptions")).toBeInTheDocument();
    expect(screen.getByText(/Order & Payment Reconciliation。必要なスキル: Invoice review/)).toBeInTheDocument();
    expect(screen.getAllByText("$7.50").length).toBeGreaterThan(0);
    expect(screen.getByText(/マニラ時間/)).toBeInTheDocument();
  });

  it("translates the earnings page and keeps money in dollars", () => {
    renderWithIntl(<EarningsView />, { locale: "ja" });
    expect(screen.getByRole("heading", { name: "報酬" })).toBeInTheDocument();
    expect(screen.getByText("未払いの報酬")).toBeInTheDocument();
    expect(screen.getByText("支払い済み")).toBeInTheDocument();
    expect(screen.getByText("Quality audit, 5 reconciled orders")).toBeInTheDocument();
    expect(screen.getAllByText("$7.50").length).toBeGreaterThan(0);
  });

  it("translates the portal error page title and back link", () => {
    const qc = new QueryClient();
    renderWithIntl(
      <QueryClientProvider client={qc}>
        <WorkError error={new Error("boom")} reset={() => {}} />
      </QueryClientProvider>,
      { locale: "ja" },
    );
    expect(screen.getByRole("heading", { name: "このページを読み込めませんでした" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "受けられるタスクに戻る" })).toHaveAttribute("href", "/work");
  });
});

describe("reviewer portal with nothing yet", () => {
  it("says no tasks are open and links to earnings", () => {
    lists.tasks = [];
    renderWithIntl(<WorkView />);
    expect(screen.getByText(/No review tasks are open right now/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "See earnings" })[0]).toHaveAttribute("href", "/work/earnings");
    lists.tasks = null;
  });

  it("says no submissions are accepted yet and links to open tasks", () => {
    lists.earnings = [];
    renderWithIntl(<EarningsView />);
    expect(screen.getByText("No accepted submissions yet. Claim an open task to start earning.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See available tasks" })).toHaveAttribute("href", "/work");
    lists.earnings = null;
  });
});

describe("reviewer portal in a live workspace", () => {
  it("labels pay as simulated without calling the workspace a demo", () => {
    workspace.demo = false;
    renderWithIntl(<WorkView />);
    expect(screen.getByText("Pay is simulated")).toBeInTheDocument();
    expect(screen.queryByText(/demo/i)).not.toBeInTheDocument();
    workspace.demo = true;
  });
});
