import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Compass, House, Workflow } from "lucide-react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithIntl } from "@/test/intl";
import { useUi } from "@/stores/ui";
import { CommandPalette } from "./command-palette";
import { TourContext } from "./tour/tour-context";

const ok = <T,>(data: T) => ({ isPending: false, isError: false, data });
const data = vi.hoisted(() => ({ demo: false }));

vi.mock("@/lib/queries/me", () => ({ useIsDemo: () => data.demo }));
vi.mock("@/lib/queries/catalog", () => ({
  usePacks: () => ok([{ slug: "e2e-request-check", name: "E2E Request Check", installed: true, category: "Ops" }]),
}));
vi.mock("@/lib/queries/runs", () => ({
  useRuns: () =>
    ok([
      // Two runs of the same pack share a title; the palette must still tell them apart.
      {
        id: "run_2012",
        packSlug: "e2e-request-check",
        title: "E2E Request Check",
        summary: "The run finished.",
        status: "COMPLETED",
        startedAt: "2026-10-12T15:40:00Z",
        hasDetail: true,
      },
      {
        id: "run_2009",
        packSlug: "e2e-request-check",
        title: "E2E Request Check",
        summary: "The run finished.",
        status: "FAILED",
        startedAt: "2026-10-11T16:00:00Z",
        hasDetail: true,
      },
    ]),
}));
vi.mock("@/lib/queries/tasks", () => ({ useEligibleTasks: () => ok([]) }));
vi.mock("@/lib/queries/workspace", () => ({ useApprovals: () => ok([]) }));

const PAGES = [
  { href: "/app", label: "Overview", icon: House },
  { href: "/app/runs", label: "Runs", icon: Workflow },
];

// Outside a live workspace the clock is pinned at 2026-10-12T16:40Z, so the runs read 1 h ago and yesterday.
describe("CommandPalette", () => {
  beforeEach(() => {
    data.demo = false;
    useUi.setState({ paletteOpen: true });
  });

  it("tells runs of one pack apart by status and age, and keeps the id searchable", async () => {
    renderWithIntl(<CommandPalette pages={PAGES} />);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Completed · 1 h ago")).toBeInTheDocument();
    expect(within(dialog).getByText("Failed · yesterday")).toBeInTheDocument();
    expect(within(dialog).queryByText("run_2012")).not.toBeInTheDocument();
    expect(within(dialog).getAllByRole("option", { name: /E2E Request Check/ })).toHaveLength(3); // 2 runs + the pack
  });

  it("lists pages without repeating a hint on every row", async () => {
    renderWithIntl(<CommandPalette pages={PAGES} />);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("option", { name: "Overview" })).toHaveAttribute("href", "/app");
    expect(within(dialog).queryByText("Go to page")).not.toBeInTheDocument();
  });

  it("notes that search covers demo data in the demo only", async () => {
    const { unmount } = renderWithIntl(<CommandPalette pages={PAGES} />);
    await screen.findByRole("dialog");
    expect(screen.queryByText("Search covers demo data only")).not.toBeInTheDocument();
    unmount();
    data.demo = true;
    renderWithIntl(<CommandPalette pages={PAGES} />);
    await screen.findByRole("dialog");
    expect(screen.getByText("Search covers demo data only")).toBeInTheDocument();
  });

  it("runs an action, closes, and hands it what had focus before the palette opened", async () => {
    useUi.setState({ paletteOpen: false });
    const before = document.createElement("button");
    document.body.append(before);
    before.focus();
    const run = vi.fn();
    renderWithIntl(
      <CommandPalette pages={PAGES} actions={[{ id: "tour", label: "Take the tour", icon: Compass, run }]} />,
    );
    act(() => useUi.getState().setPaletteOpen(true));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Actions")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("option", { name: "Take the tour" }));
    expect(run).toHaveBeenCalledWith(before);
    expect(useUi.getState().paletteOpen).toBe(false);
    before.remove();
  });

  it("leaves its shortcuts to a product tour on screen", async () => {
    useUi.setState({ paletteOpen: false });
    const tour = (visible: boolean) => (
      <TourContext value={{ start: () => false, replay: () => {}, pending: null, clearPending: () => {}, visible }}>
        <CommandPalette pages={PAGES} />
      </TourContext>
    );
    const { rerender } = renderWithIntl(tour(true));
    await userEvent.keyboard("/");
    await userEvent.keyboard("{Control>}k{/Control}");
    expect(useUi.getState().paletteOpen).toBe(false);
    rerender(tour(false));
    await userEvent.keyboard("{Control>}k{/Control}");
    expect(useUi.getState().paletteOpen).toBe(true);
  });
});
