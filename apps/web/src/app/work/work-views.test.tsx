import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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

vi.mock("@/components/base", async (orig) => ({ ...(await orig<object>()), useToast: () => vi.fn() }));
const workspace = vi.hoisted(() => ({ demo: true }));
vi.mock("@/lib/queries/me", () => ({ useIsDemo: () => workspace.demo, useIsLive: () => !workspace.demo }));

const lists = vi.hoisted(() => ({ tasks: null as unknown[] | null, earnings: null as unknown[] | null }));
const profile = vi.hoisted(() => ({ data: undefined as unknown }));
vi.mock("@/lib/queries/tasks", () => ({
  useEligibleTasks: () => ready(lists.tasks ?? OPEN_TASKS),
  useEarnings: () => ready(lists.earnings ?? EARNINGS),
  useReviewerProfile: () => ({ data: profile.data }),
  useUpdateReviewerProfile: () => ({ mutate: vi.fn() }),
}));

afterEach(() => {
  workspace.demo = true;
  lists.tasks = null;
  lists.earnings = null;
  profile.data = undefined;
});

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

describe("reviewer portal with team and network tasks", () => {
  it("marks a team task unpaid and a network task as network work", () => {
    workspace.demo = false;
    lists.tasks = [
      { ...OPEN_TASKS[0], id: "ht_team", via: "team", pay: { amountMinor: 0, currency: "USD" } },
      { ...OPEN_TASKS[0], id: "ht_net", via: "network", pay: { amountMinor: 150, currency: "USD" } },
    ];
    renderWithIntl(<WorkView />);
    expect(screen.getByText("Team review, unpaid")).toBeInTheDocument(); // once on the card, not twice
    expect(screen.getByText("Network")).toBeInTheDocument();
    expect(screen.getAllByText("$1.50").length).toBeGreaterThan(0);
    expect(screen.getByText("Simulated pay once your submission is accepted: no money moves")).toBeInTheDocument();
    expect(screen.queryByText("Paid once your submission is accepted")).toBeNull();
  });

  it("shows team reviews as unpaid on the earnings page and network reviews with simulated pay", () => {
    workspace.demo = false;
    lists.earnings = [
      {
        ...EARNINGS[0],
        taskId: "ht_team",
        title: "Team check",
        via: "team",
        status: "PAID_SIMULATED",
        amount: { amountMinor: 0, currency: "USD" },
      },
      {
        ...EARNINGS[0],
        taskId: "nt_abc",
        title: "Network check",
        via: "network",
        status: "PAID_SIMULATED",
        amount: { amountMinor: 150, currency: "USD" },
      },
    ];
    renderWithIntl(<EarningsView />);
    expect(screen.getByText(/Reviews for your own workspace's team are unpaid/)).toBeInTheDocument();
    expect(screen.getByText("Pay is simulated")).toBeInTheDocument();
    expect(screen.queryByText(/demo/i)).toBeNull();
    const team = screen.getByText("Team check").closest("li")!;
    expect(team).toHaveTextContent("Team review, unpaid");
    expect(team).not.toHaveTextContent("Paid (simulated)");
    expect(team).not.toHaveTextContent("$0.00");
    const network = screen.getByText("Network check").closest("li")!;
    expect(network).toHaveTextContent("Paid (simulated)");
    expect(network).toHaveTextContent("$1.50");
    lists.earnings = null;
  });

  it("says in Japanese that team reviews are unpaid on the live earnings page", () => {
    workspace.demo = false;
    lists.earnings = [
      { ...EARNINGS[0], via: "team", status: "PAID_SIMULATED", amount: { amountMinor: 0, currency: "USD" } },
    ];
    renderWithIntl(<EarningsView />, { locale: "ja" });
    expect(screen.getByText(/チームとして行ったレビューは無報酬です/)).toBeInTheDocument();
    expect(screen.getByText("報酬は模擬です")).toBeInTheDocument();
    expect(screen.getByText("チームのレビュー、無報酬")).toBeInTheDocument();
    lists.earnings = null;
  });

  it("keeps the demo earnings copy in the demo", () => {
    renderWithIntl(<EarningsView />);
    expect(screen.getByText(/You are paid for every accepted submission/)).toBeInTheDocument();
    expect(screen.getByText("No real payouts in this demo")).toBeInTheDocument();
  });

  it("offers review for the network in a live workspace only", () => {
    profile.data = { enabled: false, suspended: false, name: "Nina Park", languages: [], skills: [] };
    workspace.demo = false;
    const { unmount } = renderWithIntl(<WorkView />);
    expect(screen.getByRole("checkbox", { name: "Review for the network" })).toBeInTheDocument();
    unmount();
    workspace.demo = true;
    renderWithIntl(<WorkView />);
    expect(screen.queryByRole("checkbox", { name: "Review for the network" })).toBeNull();
  });
});
