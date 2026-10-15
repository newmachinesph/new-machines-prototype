import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RUN_1042 } from "@/data/runs-recon";
import type { Run } from "@/lib/types";
import { renderWithIntl } from "@/test/intl";
import { RunView } from "./run-view";

const me = vi.hoisted(() => ({ userId: "pwGlMEou0WQsM6aQvlgggXtXa5C3" }));
vi.mock("@/lib/queries/me", () => ({ useMe: () => ({ data: me }) }));
vi.mock("@/lib/queries/tasks", () => ({ useTask: () => ({ data: undefined, isPending: false }) }));
vi.mock("@/lib/queries/runs", () => ({ useReceipt: () => ({}) }));
// The canvas has its own tests and needs a measured container; the page around it is what this tests.
vi.mock("./run-canvas", () => ({ RunCanvas: () => <div data-testid="canvas" /> }));

/** A finished run as the live API projects it: codes in the timeline, the approver as an account id. */
const live: Run = {
  ...RUN_1042,
  id: "run_2011",
  workflowRef: "order-payment-reconciliation@2",
  contractRef: "order-payment-reconciliation@1",
  timeline: [
    ...RUN_1042.timeline.slice(0, 3),
    {
      at: "2026-10-15T02:31:10Z",
      actor: "machine",
      who: "Do the orders and payments match?",
      title: "HUMAN_REVIEW: MISMATCHES_FOUND",
      nodeId: "decide",
    },
    {
      at: "2026-10-15T02:31:10Z",
      actor: "machine",
      who: "Decision step",
      title: "Some orders and payments do not match, so a person needs to resolve them.",
      detail: "Reason code: MISMATCHES_FOUND",
      nodeId: "decide",
    },
    {
      at: "2026-10-15T02:33:26Z",
      actor: "buyer",
      who: me.userId,
      title: "Approved",
      ref: "apr_run_2011_approve_write_1",
      nodeId: "report",
    },
    { at: "2026-10-15T02:33:27Z", actor: "system", who: "Workflow engine", title: "Completed the run" },
  ],
};

describe("RunView", () => {
  it("writes timeline codes as sentences and names the viewer, keeping refs behind a toggle", () => {
    renderWithIntl(<RunView run={live} />);
    expect(screen.getByText("Needs a person: Some orders and payments do not match")).toBeInTheDocument();
    expect(screen.getByText("Reason: Some orders and payments do not match")).toBeInTheDocument();
    expect(screen.queryByText(me.userId)).not.toBeInTheDocument();
    expect(screen.getAllByText("You").length).toBeGreaterThan(0);
    expect(screen.queryByText("apr_run_2011_approve_write_1")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Show technical details" }));
    expect(screen.getByText("apr_run_2011_approve_write_1")).toBeInTheDocument();
  });

  it("can hide the system steps of the timeline", () => {
    renderWithIntl(<RunView run={live} />);
    expect(screen.getByText("Completed the run")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Hide system steps" }));
    expect(screen.queryByText("Completed the run")).not.toBeInTheDocument();
    expect(screen.getByText("Started the run")).toBeInTheDocument();
  });

  it("scrolls the inspector into view when a phone taps a step or a timeline entry", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    window.matchMedia = ((query: string) => ({ matches: true, media: query })) as unknown as typeof window.matchMedia;
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => (cb(0), 0));
    renderWithIntl(<RunView run={live} />);
    fireEvent.click(
      within(screen.getByRole("list", { name: "Steps" })).getByRole("button", { name: /Reconcile payments/ }),
    );
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll.mock.contexts[0]).toBe(screen.getByRole("region", { name: "Selected step" }));
    expect(scroll).toHaveBeenCalledWith({ block: "start", behavior: "auto" });
    fireEvent.click(screen.getByRole("button", { name: "Approved" }));
    expect(scroll).toHaveBeenCalledTimes(2);
    vi.restoreAllMocks();
  });

  it("opens the run details when its jump link is clicked", () => {
    Element.prototype.scrollIntoView = vi.fn();
    renderWithIntl(<RunView run={live} />);
    const toggle = screen.getByRole("button", { name: "Show Run details" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(
      within(screen.getByRole("navigation", { name: "Jump to" })).getByRole("link", { name: "Run details" }),
    );
    expect(screen.getByRole("button", { name: "Hide Run details" })).toHaveAttribute("aria-expanded", "true");
  });

  it("shows times in the viewer's zone and says so", () => {
    renderWithIntl(<RunView run={live} />);
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(zone).toBeTruthy();
    expect(screen.getByText(/^Times in your time zone \(.+\)$/)).toBeInTheDocument();
    expect(screen.queryByText("Times in Pacific time")).not.toBeInTheDocument();
  });

  it("keeps the run's ids under technical details and tells agents from app actions in the legend", () => {
    renderWithIntl(<RunView run={live} />);
    for (const id of ["run_2011", "order-payment-reconciliation@2", "order-payment-reconciliation@1"]) {
      expect(screen.getByText(id).closest("details")).not.toBeNull();
    }
    // In the legend, and on each agent and connector step of the list.
    const steps = screen.getByRole("region", { name: "Workflow" });
    expect(within(steps).getAllByText("AI agent").length).toBeGreaterThan(1);
    expect(within(steps).getAllByText("App action").length).toBeGreaterThan(1);
    expect(within(steps).queryByText("Agent or tool")).not.toBeInTheDocument();
  });

  it("lists the steps for a phone, selecting one on tap, and folds the run details until asked", () => {
    renderWithIntl(<RunView run={live} />);
    const list = screen.getByRole("list", { name: "Steps" });
    const steps = within(list).getAllByRole("button");
    expect(steps).toHaveLength(live.nodes.length);
    // The default selection is the decision step; tapping another step moves the inspector to it.
    expect(within(list).getByRole("button", { name: /Can this be accepted\?/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    fireEvent.click(within(list).getByRole("button", { name: /Reconcile payments/ }));
    expect(within(list).getByRole("button", { name: /Reconcile payments/ })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("heading", { level: 3, name: "Reconcile payments" })).toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: "Show Run details" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById(toggle.getAttribute("aria-controls")!)).toHaveClass("hidden");
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Hide Run details" })).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById(toggle.getAttribute("aria-controls")!)).not.toHaveClass("hidden");

    const nav = screen.getByRole("navigation", { name: "Jump to" });
    expect(within(nav).getByRole("link", { name: "Timeline" })).toHaveAttribute("href", "#run-timeline");
  });
});
