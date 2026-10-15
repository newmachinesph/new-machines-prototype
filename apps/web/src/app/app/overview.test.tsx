import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { Overview } from "./overview";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });

const data = vi.hoisted(() => ({
  demo: false,
  packs: [] as unknown[],
  conns: [] as unknown[],
  runs: [] as unknown[],
  attention: [] as unknown[],
  usage: undefined as unknown,
}));

vi.mock("./ask-box", () => ({ AskBox: () => null }));
vi.mock("./invitation-notice", () => ({ InvitationNotices: () => null }));
vi.mock("@/lib/queries/me", () => ({ useIsDemo: () => data.demo }));
vi.mock("@/lib/queries/catalog", () => ({ usePacks: () => ok(data.packs) }));
vi.mock("@/lib/queries/runs", () => ({ useRuns: () => ok(data.runs) }));
vi.mock("@/lib/queries/workspace", () => ({ useUsage: () => ok(data.usage) }));
vi.mock("@/lib/queries/org", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/queries/org")>()),
  useConnections: () => ok(data.conns),
  useAttention: () => ok(data.attention),
}));

const org = (spent: number, plan = "Trial") => ({
  id: "org_new",
  name: "Ana's workspace",
  short: "Ana's workspace",
  plan,
  monthlyCap: usd(25000),
  monthSpent: usd(spent),
  region: "us-central1",
});
const RECON = {
  slug: "order-payment-reconciliation",
  name: "Order & Payment Reconciliation",
  version: "1.0.0",
  installed: false,
  connectors: [{ app: "Shopify" }, { app: "Stripe" }],
};
const RUN = {
  id: "run_2001",
  packSlug: RECON.slug,
  title: "Reconcile Oct 6-12",
  summary: "Running",
  status: "RUNNING",
  startedAt: "2026-10-12T16:00:00Z",
  stages: { executed: "pending", verified: "pending", accepted: "pending", settlement: "pending" },
  spent: { ai: usd(10), tools: usd(0), human: usd(0) },
  hasDetail: true,
};
const connection = (app: string, status: string) => ({ app, status, provider: "Mock", grants: [], oauthScopes: [] });

const checklist = () => screen.getByRole("heading", { name: "Get started" }).closest("section")!;

describe("Overview in a new workspace", () => {
  beforeEach(() => {
    data.demo = false;
    data.packs = [RECON];
    data.conns = [];
    data.runs = [];
    data.attention = [];
    data.usage = { org: org(0), ledger: [] };
  });

  it("shows the getting-started steps, none ticked, each linking to its page", () => {
    renderWithIntl(<Overview />);
    const steps = within(within(checklist()).getByRole("list")).getAllByRole("link");
    expect(steps.map((s) => s.getAttribute("href"))).toEqual(["/app/marketplace", "/app/connections", "/app/runs/new"]);
    expect(within(checklist()).queryByLabelText("Done")).not.toBeInTheDocument();
  });

  it("offers the reviewer portal beside the steps, for someone who came to review tasks", () => {
    renderWithIntl(<Overview />);
    expect(within(checklist()).getByRole("link", { name: "Go to reviewer portal" })).toHaveAttribute("href", "/work");
  });

  it("ticks adding once a pack is added, and connecting once its apps are connected", () => {
    data.packs = [{ ...RECON, installed: true }];
    data.conns = [connection("Shopify", "sandbox"), connection("Stripe", "not_connected")];
    const { unmount } = renderWithIntl(<Overview />);
    expect(within(checklist()).getAllByLabelText("Done")).toHaveLength(1);
    expect(within(checklist()).getByRole("link", { name: /Start a run/ })).toHaveAttribute(
      "href",
      "/app/runs/new?pack=order-payment-reconciliation",
    );
    unmount();
    data.conns = [connection("Shopify", "sandbox"), connection("Stripe", "sandbox")];
    renderWithIntl(<Overview />);
    expect(within(checklist()).getAllByLabelText("Done")).toHaveLength(2);
  });

  it("hides the steps once a pack is added and a run exists", () => {
    data.packs = [{ ...RECON, installed: true }];
    data.runs = [RUN];
    renderWithIntl(<Overview />);
    expect(screen.queryByRole("heading", { name: "Get started" })).not.toBeInTheDocument();
  });

  it("points each empty card at the next thing to do", () => {
    renderWithIntl(<Overview />);
    expect(
      screen.getByText("Nothing needs you right now. Approvals and review tasks show up here."),
    ).toBeInTheDocument();
    // Nothing waiting is one quiet line: no count of zero beside the heading.
    expect(screen.getByRole("heading", { name: "Needs you" }).closest("section")).not.toHaveTextContent("0");
    expect(screen.getByText("No packs added yet. Add a pack to put agents to work.")).toBeInTheDocument();
    expect(screen.getByText("No runs yet. Add a pack first, then start a run.")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Browse the marketplace" })[0]).toHaveAttribute(
      "href",
      "/app/marketplace",
    );
  });

  it("counts what needs you beside the heading once there is something", () => {
    data.attention = [
      { href: "/app/approvals", title: "Approve the email", detail: "One email", actor: "buyer", when: RUN.startedAt },
    ];
    renderWithIntl(<Overview />);
    expect(screen.getByRole("heading", { name: "Needs you" }).closest("div")).toHaveTextContent("Needs you1");
  });

  it("dates an added pack by its last run on this page, never by its version", () => {
    data.packs = [{ ...RECON, installed: true }];
    data.runs = [RUN, { ...RUN, id: "run_2000", startedAt: "2026-10-10T16:00:00Z" }];
    const { unmount } = renderWithIntl(<Overview />);
    const packs = () => screen.getByRole("heading", { name: "Your packs" }).closest("section")!;
    expect(within(packs()).getByText("Last run 40 min ago")).toBeInTheDocument(); // the newest run, not the oldest
    expect(within(packs()).queryByText(/1\.0\.0/)).not.toBeInTheDocument();
    unmount();
    data.runs = [];
    renderWithIntl(<Overview />);
    expect(within(packs()).getByText("No runs yet")).toBeInTheDocument();
  });

  it("names the pack once per run row, and keeps status and cost on every row", () => {
    data.packs = [{ ...RECON, installed: true }];
    data.runs = [
      { ...RUN, summary: "Checking 12 orders" },
      { ...RUN, id: "run_2002", title: RECON.name, status: "COMPLETED" },
    ];
    renderWithIntl(<Overview />);
    const titled = screen.getByRole("link", { name: /Reconcile Oct 6-12/ });
    expect(within(titled).getByText(RECON.name)).toBeInTheDocument(); // the pack, under a run called something else
    const sameName = screen.getByRole("link", { name: /Completed/ });
    expect(within(sameName).getAllByText(RECON.name)).toHaveLength(1);
    expect(within(sameName).queryByText(/run_2002/)).not.toBeInTheDocument();
    // Status and cost are in the row at every width (the pill twice: one for narrow screens, one for the column).
    expect(within(titled).getAllByText("Running")).toHaveLength(2);
    expect(within(titled).getByText("$0.10")).toBeInTheDocument();
  });

  it("reads the budget from the org and its ledger, with no plan fee on a trial", () => {
    data.usage = {
      org: org(450),
      ledger: [
        {
          id: "run_2001",
          at: "2026-10-11T10:00:00Z",
          kind: "run",
          description: "Run",
          amount: usd(450),
          status: "POSTED",
          lines: [],
          spent: { ai: usd(120), tools: usd(30), human: usd(300) },
        },
      ],
    };
    renderWithIntl(<Overview />);
    const budget = screen.getByRole("heading", { name: "Budget" }).closest("section")!;
    expect(within(budget).getByText("Trial plan").closest("div")).toHaveTextContent("$0.00");
    expect(within(budget).getByText("Agents, models and tools").closest("div")).toHaveTextContent("$1.50");
    expect(within(budget).getByText("Reviewer pay").closest("div")).toHaveTextContent("$3.00");
    expect(within(budget).getByText(/days? left in/)).toBeInTheDocument();
  });
});

describe("Overview in the demo workspace", () => {
  it("keeps the demo's figures: 19 days left in October and the Pro plan split", () => {
    data.demo = true;
    data.packs = [{ ...RECON, installed: true }];
    data.runs = [RUN];
    data.usage = {
      org: org(6194, "Pro"),
      ledger: [
        {
          id: "txn_5497",
          at: "2026-10-11T10:00:00Z",
          kind: "human_pay",
          description: "Reviewer pay",
          amount: usd(750),
          status: "ELIGIBLE",
          lines: [{ account: "Buyer charges", debit: 750 }],
        },
        {
          id: "txn_5400",
          at: "2026-10-01T00:00:00Z",
          kind: "plan",
          description: "Pro plan, October",
          amount: usd(4900),
          status: "POSTED",
          lines: [{ account: "Buyer charges", debit: 4900 }],
        },
      ],
    };
    renderWithIntl(<Overview />);
    expect(screen.getByText("19 days left in October")).toBeInTheDocument();
    expect(screen.getByText("Pro plan").closest("div")).toHaveTextContent("$49.00");
    expect(screen.getByText("Agents, models and tools").closest("div")).toHaveTextContent("$5.44");
    expect(screen.getByText("Reviewer pay").closest("div")).toHaveTextContent("$7.50");
  });

  it("shows the month in Japanese", () => {
    data.demo = true;
    renderWithIntl(<Overview />, { locale: "ja" });
    expect(screen.getByText("10月は残り19日")).toBeInTheDocument();
  });
});
