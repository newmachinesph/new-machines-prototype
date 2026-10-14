import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import type { Reviewer } from "@/lib/api/gen/types.gen";

const state = vi.hoisted(() => ({ workspace: "demo" as "demo" | "live", tab: "active" as string | null }));
const data = vi.hoisted(() => ({ reviewers: null as Reviewer[] | null }));

vi.mock("nuqs", () => ({
  parseAsStringLiteral: () => ({}),
  useQueryState: () => [state.tab, vi.fn()],
}));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => true, useOpsWorkspace: () => state.workspace }));
vi.mock("@/lib/queries/workforce", () => ({
  useReviewers: () => ({ isPending: false, isError: false, data: data.reviewers ?? [reviewer, applicant] }),
  useApproveReviewer: () => ({ mutateAsync: vi.fn() }),
  useSuspendReviewer: () => ({ mutateAsync: vi.fn() }),
  useReinstateReviewer: () => ({ mutateAsync: vi.fn() }),
  useSetReviewerLevel: () => ({ mutateAsync: vi.fn() }),
}));

import { WorkforceLede, WorkforceView } from "./workforce-view";

const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });
const reviewer = {
  id: "rev_1",
  name: "Maria Santos",
  email: "maria@example.com",
  country: "PH",
  status: "active",
  level: "qualified",
  languages: ["en"],
  skills: ["Reconciliation"],
  joinedAt: "2026-03-02T17:20:00Z",
  tasksDone30d: 12,
  accuracy: 0.97,
  medianMinutes: 6,
  earnings30d: usd(4200),
  queue: 1,
} as unknown as Reviewer;
const applicant = { ...reviewer, id: "rev_2", name: "Ken Ito", status: "applicant" } as Reviewer;

const renderIt = (ui: React.ReactElement) => render(<UiProviders>{ui}</UiProviders>);

const DEMO_LEDE =
  "Human reviewers who take on tasks when a run needs a person. Approve applicants, set levels, and pause anyone who should stop receiving work.";
const LIVE_LEDE =
  "Network reviewers who chose to review for New Machines from the reviewer portal. Suspend anyone who should stop receiving network tasks.";

const LIVE_EMPTY =
  "No network reviewers yet. People join when they turn on Review for the network in the reviewer portal.";

beforeEach(() => {
  state.workspace = "demo";
  state.tab = "active";
  data.reviewers = null;
});

describe("WorkforceLede", () => {
  it("keeps the demo lede", () => {
    renderIt(<WorkforceLede />);
    expect(screen.getByText(DEMO_LEDE)).toBeInTheDocument();
  });

  it("describes the reviewer network in the live workspace", () => {
    state.workspace = "live";
    renderIt(<WorkforceLede />);
    expect(screen.getByText(LIVE_LEDE)).toBeInTheDocument();
    expect(screen.queryByText(/Approve applicants/)).toBeNull();
  });
});

describe("WorkforceView", () => {
  it("keeps the Actions column in the demo", () => {
    renderIt(<WorkforceView />);
    expect(screen.getByRole("columnheader", { name: "Actions" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suspend Maria Santos" })).toBeInTheDocument();
  });

  it("shows the live network's columns with its suspend action", () => {
    state.workspace = "live";
    renderIt(<WorkforceView />);
    expect(screen.getByRole("columnheader", { name: "Simulated earnings (30d)" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Level" })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Accuracy" })).toBeNull();
    expect(screen.getByRole("button", { name: "Suspend Maria Santos" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Set level for Maria Santos" })).toBeNull();
  });

  it("shows the reviewer's email alone when there is no country", () => {
    state.workspace = "live";
    data.reviewers = [{ ...reviewer, country: "" } as Reviewer];
    renderIt(<WorkforceView />);
    expect(screen.getByText("maria@example.com")).toBeInTheDocument();
  });

  it("has no Applicants tab in the live workspace, even when the URL asks for it", () => {
    state.workspace = "live";
    state.tab = "applicants";
    renderIt(<WorkforceView />);
    expect(screen.queryByRole("button", { name: /^Applicants/ })).toBeNull();
    expect(screen.queryByText(/applicant/i)).toBeNull();
    expect(screen.getByRole("button", { name: "Suspend Maria Santos" })).toBeInTheDocument();
  });

  it("says how the live network fills up when nobody is active", () => {
    state.workspace = "live";
    data.reviewers = [];
    renderIt(<WorkforceView />);
    expect(screen.getByText(LIVE_EMPTY)).toBeInTheDocument();
    expect(screen.queryByText(/applicant/i)).toBeNull();
  });

  it("keeps the Applicants tab in the demo", () => {
    renderIt(<WorkforceView />);
    expect(screen.getByRole("button", { name: /^Applicants/ })).toBeInTheDocument();
  });
});
