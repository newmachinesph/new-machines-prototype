import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ListingVersion, StudioListingDetail } from "@/lib/api/gen/types.gen";
import { ApiError } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/intl";
import { ListingView } from "./listing-view";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const usd = (amountMinor: number) => ({ amountMinor, currency: "USD" as const });
const version = (n: number, over: Partial<ListingVersion>): ListingVersion => ({
  id: `v${n}`,
  definitionVersion: n,
  status: "approved",
  price: usd(25),
  checks: [],
  submittedAt: `2026-10-0${n}T09:00:00Z`,
  submittedBy: "ana@acme.test",
  ...over,
});
const state = vi.hoisted(() => ({
  detail: undefined as unknown,
  error: undefined as unknown,
  runStatus: "RUNNING",
}));
vi.mock("@/lib/queries/runs", () => ({ useRun: () => ({ data: { status: state.runStatus } }) }));

vi.mock("@/lib/queries/publishing", () => ({
  useStudioListing: () =>
    state.error ? { isPending: false, isError: true, error: state.error, data: undefined } : ok(state.detail),
}));

const detail = (versions: ListingVersion[]): StudioListingDetail => ({
  id: "l1",
  kind: "pack",
  key: "org-a1--refund-check",
  name: "Refund check",
  status: "listed",
  price: usd(25),
  latest: versions[versions.length - 1],
  approvedVersion: 1,
  installs: 12,
  runs30d: 340,
  earningsMonth: usd(4200),
  simulated: true,
  versions,
});

describe("ListingView", () => {
  beforeEach(() => {
    state.error = undefined;
    state.detail = detail([
      version(1, { note: "Looks good." }),
      version(2, {
        status: "changes_requested",
        note: "Name the refund limit in the summary.",
        checks: [
          { name: "definition", state: "passed", detail: "Valid." },
          { name: "sandbox", state: "failed", detail: "Step 2 timed out.", runId: "run_77" },
        ],
      }),
    ]);
  });

  it("shows the listing's numbers and the versions newest first", () => {
    renderWithIntl(<ListingView listingId="l1" />);
    expect(screen.getByRole("heading", { level: 1, name: "Refund check" })).toBeInTheDocument();
    expect(screen.getByText("340")).toBeInTheDocument();
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["Version 2", "Version 1"]);
    expect(screen.getAllByText(/ana@acme.test/).length).toBe(2);
  });

  it("shows a changes-requested note in a warning callout", () => {
    renderWithIntl(<ListingView listingId="l1" />);
    const note = screen.getByText("Name the refund limit in the summary.");
    expect(note.closest("div[class*='border-human']")).not.toBeNull();
  });

  it("shows a failed sandbox check with its detail and a link to the run", () => {
    renderWithIntl(<ListingView listingId="l1" />);
    expect(screen.getByText("Step 2 timed out.")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Open the sandbox run" });
    expect(link).toHaveAttribute("href", "/app/runs/run_77");
    const checks = screen.getByText("Step 2 timed out.").closest("li") as HTMLElement;
    expect(within(checks).getByText("Failed")).toBeInTheDocument();
  });

  it("explains a checking version whose check run waits for a reviewer", () => {
    state.runStatus = "WAITING_FOR_HUMAN";
    state.detail = detail([
      version(1, {
        status: "checking",
        checks: [{ name: "sandbox", state: "running", detail: "Running.", runId: "run_9" }],
      }),
    ]);
    renderWithIntl(<ListingView listingId="l1" />);
    expect(screen.getByText("The check is waiting for a reviewer in your workspace.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the run to review it" })).toHaveAttribute("href", "/app/runs/run_9");
  });

  it("does not explain a wait on a version that is not checking", () => {
    state.runStatus = "WAITING_FOR_HUMAN";
    renderWithIntl(<ListingView listingId="l1" />);
    expect(screen.queryByText(/waiting for a reviewer/)).not.toBeInTheDocument();
  });

  it("shows a rejected note as a danger callout and an approved note as neutral", () => {
    state.detail = detail([
      version(1, { note: "Fine.", status: "approved" }),
      version(2, { status: "rejected", note: "Not suitable." }),
    ]);
    renderWithIntl(<ListingView listingId="l1" />);
    expect(screen.getByText("Not suitable.").closest("div[class*='border-blocked']")).not.toBeNull();
    expect(screen.getByText("Fine.").closest("div[class*='border-machine']")).not.toBeNull();
  });

  it("shows the price in review before the first approval, never No fee", () => {
    state.detail = {
      ...detail([version(1, { status: "in_review", price: usd(250) })]),
      status: "pending",
      price: usd(0),
      approvedVersion: undefined,
    };
    renderWithIntl(<ListingView listingId="l1" />);
    expect(screen.getAllByText("$2.50 per run").length).toBe(2);
    expect(screen.queryByText("No fee")).toBeNull();
  });

  it("labels the listed price and the price in review when a new version changes it", () => {
    state.detail = detail([version(1, {}), version(2, { status: "in_review", price: usd(40) })]);
    renderWithIntl(<ListingView listingId="l1" />);
    expect(screen.getByText("Listed price")).toBeInTheDocument();
    expect(screen.getByText("Price in review")).toBeInTheDocument();
    expect(screen.queryByText("Price")).toBeNull();
  });

  it("words the fixed check details in the interface language and keeps a failure's own detail", () => {
    state.detail = detail([
      version(1, {
        status: "checks_failed",
        checks: [
          { name: "definition", state: "passed", detail: "The definition checks found no problems." },
          { name: "sandbox", state: "failed", detail: "The sandbox run ended failed.", runId: "run_77" },
        ],
      }),
    ]);
    renderWithIntl(<ListingView listingId="l1" />, { locale: "ja" });
    expect(screen.getByText("定義のチェックで問題は見つかりませんでした。")).toBeInTheDocument();
    expect(screen.getByText("The sandbox run ended failed.")).toBeInTheDocument();
  });

  it("says a listing that is not there is not found, with the way back", () => {
    state.error = new ApiError(404, "NOT_FOUND", "No listing l9.");
    renderWithIntl(<ListingView listingId="l9" />);
    expect(screen.getByRole("heading", { name: "There is no such listing" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Publisher" })).toHaveAttribute("href", "/studio/publisher");
  });
});
