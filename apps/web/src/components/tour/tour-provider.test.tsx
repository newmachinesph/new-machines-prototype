import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isSeen, markSeen, reset } from "@/lib/tour/seen";
import { TOURS, type TourName } from "@/lib/tour/tours";
import { useLeaveGuard } from "@/lib/use-leave-guard";
import { renderWithIntl } from "@/test/intl";
import type { TourApi } from "./tour-context";
import { TourProvider, useTour } from "./tour-provider";
import { useAutoTour } from "./use-auto-tour";

const nav = vi.hoisted(() => ({ push: vi.fn(), path: "/app" }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: nav.push }), usePathname: () => nav.path }));

let api: TourApi;

function Opener() {
  const tour = useTour();
  useEffect(() => {
    api = tour;
  });
  return (
    <button type="button" onClick={() => tour.start("welcome")}>
      Open tour
    </button>
  );
}

/** The overview's own auto-start, for replays to be picked up by. */
function AutoTour({ ready }: { ready: boolean }) {
  useAutoTour("welcome", ready);
  return null;
}

/** A page holding unsaved work. */
function Dirty() {
  useLeaveGuard(true);
  return null;
}

type PageOptions = { autoTour?: boolean; dirty?: boolean; main?: boolean };

/** The provider around a page holding the given `data-tour` targets. `autoTour` renders the page's `useAutoTour`,
 * ready or not. */
function pageTree(targets: string[], { autoTour, dirty, main }: PageOptions = {}) {
  const content = targets.map((v) => (
    <div key={v} data-tour={v}>
      {v}
    </div>
  ));
  return (
    <TourProvider>
      <Opener />
      {main ? (
        <main id="main" tabIndex={-1}>
          {content}
        </main>
      ) : (
        content
      )}
      {autoTour === undefined ? null : <AutoTour ready={autoTour} />}
      {dirty ? <Dirty /> : null}
    </TourProvider>
  );
}

const renderPage = (targets: string[], options?: PageOptions) => renderWithIntl(pageTree(targets, options));

const site = () => document.querySelector('[data-name="nextstep-site"]');

describe("TourProvider", () => {
  beforeEach(() => {
    for (const name of Object.keys(TOURS) as TourName[]) reset(name);
    nav.push.mockReset();
    nav.path = "/app";
    window.localStorage.clear();
    // jsdom has no layout or observers; the tour library needs all of these to place its card.
    vi.spyOn(Element.prototype, "getClientRects").mockReturnValue([new DOMRect(0, 0, 10, 10)] as never);
    Element.prototype.scrollIntoView = vi.fn();
    window.scrollTo = vi.fn() as never;
    window.scrollBy = vi.fn() as never;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
      },
    );
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        observe() {}
        unobserve() {}
        disconnect() {}
        takeRecords() {
          return [];
        }
      },
    );
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: false,
      media: query,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
    }));
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows a step for each target on the page, makes the page inert, and Escape skips and records it", async () => {
    renderPage(["ask-box"]);
    await userEvent.click(screen.getByRole("button", { name: "Open tour" }));
    expect(await screen.findByRole("dialog", { name: "Start from the outcome" })).toBeInTheDocument();
    expect(screen.getByText("Step 1 of 1")).toBeInTheDocument();
    expect(site()).toHaveAttribute("inert");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(isSeen("welcome")).toBe(true);
    expect(site()).not.toHaveAttribute("inert");
    expect(screen.getByRole("button", { name: "Open tour" })).toHaveFocus();
  });

  it("records the tour when Done is pressed and returns focus to the opener", async () => {
    renderPage(["ask-box", "nav-runs"]);
    await userEvent.click(screen.getByRole("button", { name: "Open tour" }));
    await screen.findByRole("dialog", { name: "Start from the outcome" });
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("dialog", { name: "Follow every run" })).toBeInTheDocument();
    expect(isSeen("welcome")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(isSeen("welcome")).toBe(true);
    expect(screen.getByRole("button", { name: "Open tour" })).toHaveFocus();
  });

  it("scrolls a step's target up under the top bar when its card would not fit below it", async () => {
    renderPage(["ask-box"]);
    const target = document.querySelector('[data-tour="ask-box"]')!;
    vi.spyOn(target, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 700, 600, 120));
    vi.spyOn(window, "innerHeight", "get").mockReturnValue(900);
    vi.spyOn(document.documentElement, "scrollHeight", "get").mockReturnValue(3000);
    await userEvent.click(screen.getByRole("button", { name: "Open tour" }));
    await screen.findByRole("dialog", { name: "Start from the outcome" });
    // 700px down, the ask box leaves no room for its card; it moves up to 88px, under the top bar.
    await waitFor(() => expect(window.scrollBy).toHaveBeenCalledWith({ top: 612, behavior: "smooth" }));
  });

  it("does not start when none of the tour's targets is on the page", async () => {
    renderPage([]);
    let started: boolean | undefined;
    act(() => {
      started = api.start("welcome");
    });
    expect(started).toBe(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(site()).not.toHaveAttribute("inert");
    expect(isSeen("welcome")).toBe(false);
  });

  it("leaves a tour on screen alone when asked to start again", async () => {
    renderPage(["ask-box", "nav-runs"]);
    await userEvent.click(screen.getByRole("button", { name: "Open tour" }));
    await screen.findByRole("dialog", { name: "Start from the outcome" });
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByRole("dialog", { name: "Follow every run" });
    let again: boolean | undefined;
    act(() => {
      again = api.start("welcome");
    });
    expect(again).toBe(false);
    expect(screen.getByRole("dialog", { name: "Follow every run" })).toBeInTheDocument();
  });

  it("tells the app while a tour is on screen", async () => {
    renderPage(["ask-box"]);
    expect(api.visible).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Open tour" }));
    await screen.findByRole("dialog", { name: "Start from the outcome" });
    expect(api.visible).toBe(true);
  });

  it("returns focus to the main content after a tour nothing opened", async () => {
    renderPage(["ask-box"], { main: true });
    act(() => {
      api.start("welcome", document.body);
    });
    await screen.findByRole("dialog", { name: "Start from the outcome" });
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.getElementById("main")).toHaveFocus();
  });

  describe("replay", () => {
    beforeEach(() => {
      // Replays ignore the seen state; marking it keeps the page from starting the tour by itself.
      markSeen("welcome");
    });

    it("waits for its own page to be ready, then starts there", async () => {
      const page = renderPage(["ask-box"], { autoTour: false });
      act(() => api.replay("welcome"));
      expect(nav.push).not.toHaveBeenCalled();
      expect(api.pending).toMatchObject({ name: "welcome", href: "/app" });
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      page.rerender(pageTree(["ask-box"], { autoTour: true }));
      expect(await screen.findByRole("dialog", { name: "Start from the outcome" })).toBeInTheDocument();
      expect(api.pending).toBeNull();
    });

    it("goes to the tour's page first and starts it there, returning focus to the opener", async () => {
      nav.path = "/app/marketplace";
      const page = renderPage(["ask-box"], { autoTour: true });
      const opener = screen.getByRole("button", { name: "Open tour" });
      act(() => api.replay("welcome", { href: "/app", opener }));
      expect(nav.push).toHaveBeenCalledWith("/app");
      // Not on the page being left.
      expect(api.pending).toBeNull();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      nav.path = "/app";
      page.rerender(pageTree(["ask-box"], { autoTour: true }));
      await screen.findByRole("dialog", { name: "Start from the outcome" });
      await userEvent.keyboard("{Escape}");
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
      expect(opener).toHaveFocus();
    });

    it("drops a replay when the person leaves its page before it starts", () => {
      nav.path = "/app/marketplace";
      // No first target on the page, so the tour cannot start.
      const page = renderPage([], { autoTour: true });
      act(() => api.replay("welcome", { href: "/app" }));
      nav.path = "/app";
      page.rerender(pageTree([], { autoTour: true }));
      expect(api.pending).toMatchObject({ name: "welcome" });
      nav.path = "/app/runs";
      page.rerender(pageTree([], { autoTour: true }));
      nav.path = "/app";
      page.rerender(pageTree([], { autoTour: true }));
      expect(api.pending).toBeNull();
    });

    it("drops a replay whose page never became ready", () => {
      vi.useFakeTimers();
      try {
        const page = renderPage([], { autoTour: true });
        act(() => api.replay("welcome"));
        expect(api.pending).not.toBeNull();
        act(() => vi.advanceTimersByTime(15_000));
        page.rerender(pageTree([], { autoTour: true }));
        expect(api.pending).toBeNull();
      } finally {
        vi.useRealTimers();
      }
    });

    it("asks before leaving unsaved work, and stays on no", () => {
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      nav.path = "/studio/agents/new";
      renderPage([], { dirty: true });
      act(() => api.replay("studio", { href: "/studio" }));
      expect(confirm).toHaveBeenCalledWith("You have unsaved changes. Leave this page without saving them?");
      expect(nav.push).not.toHaveBeenCalled();
      confirm.mockReturnValue(true);
      act(() => api.replay("studio", { href: "/studio" }));
      expect(nav.push).toHaveBeenCalledWith("/studio");
    });

    it("does not ask when the replay stays on the page", () => {
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      renderPage(["ask-box"], { dirty: true });
      act(() => api.replay("welcome"));
      expect(confirm).not.toHaveBeenCalled();
      expect(api.pending).toMatchObject({ name: "welcome" });
    });
  });
});
