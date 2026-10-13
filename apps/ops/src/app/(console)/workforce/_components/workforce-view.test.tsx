import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UiProviders } from "@/components/base";
import type { Reviewer } from "@/lib/api/gen/types.gen";

const state = vi.hoisted(() => ({ workspace: "demo" as "demo" | "live", tab: "active" as string | null }));

vi.mock("nuqs", () => ({
  parseAsStringLiteral: () => ({}),
  useQueryState: () => [state.tab, vi.fn()],
}));
vi.mock("@/lib/queries/ops", () => ({ useCanWrite: () => true, useOpsWorkspace: () => state.workspace }));
vi.mock("@/lib/queries/workforce", () => ({
  useReviewers: () => ({ isPending: false, isError: false, data: [reviewer, applicant] }),
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
  "Human reviewers who take on tasks when a run needs a person. The live workspace shows them read-only.";

beforeEach(() => {
  state.workspace = "demo";
  state.tab = "active";
});

describe("WorkforceLede", () => {
  it("keeps the demo lede", () => {
    renderIt(<WorkforceLede />);
    expect(screen.getByText(DEMO_LEDE)).toBeInTheDocument();
  });

  it("invites no reviewer actions in the live workspace", () => {
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

  it.each(["active", "applicants"])("leaves out the Actions column in the live workspace (%s)", (tab) => {
    state.workspace = "live";
    state.tab = tab;
    renderIt(<WorkforceView />);
    expect(screen.getByRole("columnheader", { name: "Reviewer" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Actions" })).toBeNull();
  });
});
