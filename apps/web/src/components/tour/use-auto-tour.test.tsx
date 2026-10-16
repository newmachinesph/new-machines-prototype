import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { markSeen, reset } from "@/lib/tour/seen";
import { TourContext, type TourRequest } from "./tour-context";
import { isSettled, useAutoTour } from "./use-auto-tour";

const start = vi.fn<(name: string, opener?: Element | null) => boolean>();
const clearPending = vi.fn();
let pending: TourRequest | null = null;
const wrapper = ({ children }: { children: ReactNode }) => (
  <TourContext value={{ start, replay: vi.fn(), pending, clearPending, visible: false }}>{children}</TourContext>
);
const render = (ready: boolean) =>
  renderHook(({ ready: r }: { ready: boolean }) => useAutoTour("welcome", r), { wrapper, initialProps: { ready } });

describe("useAutoTour", () => {
  beforeEach(() => {
    start.mockReset().mockReturnValue(true);
    clearPending.mockReset();
    pending = null;
    window.localStorage.clear();
    reset("welcome");
    // The welcome tour's first target, as the overview renders it.
    document.body.innerHTML = '<div data-tour="ask-box"></div>';
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    document.body.innerHTML = "";
  });

  it("starts the tour once, when the page is ready", () => {
    const hook = render(true);
    expect(start).toHaveBeenCalledTimes(1);
    expect(start).toHaveBeenCalledWith("welcome");
    hook.rerender({ ready: false });
    hook.rerender({ ready: true });
    expect(start).toHaveBeenCalledTimes(1);
  });

  it("does not start again in the same session when the page mounts again", () => {
    render(true).unmount();
    render(true);
    expect(start).toHaveBeenCalledTimes(1);
  });

  it("tries again when the tour could not start", () => {
    start.mockReturnValueOnce(false);
    const hook = render(true);
    hook.rerender({ ready: false });
    hook.rerender({ ready: true });
    expect(start).toHaveBeenCalledTimes(2);
  });

  it("waits until the page is ready", () => {
    const hook = render(false);
    expect(start).not.toHaveBeenCalled();
    hook.rerender({ ready: true });
    expect(start).toHaveBeenCalledTimes(1);
  });

  it("does not start a tour already seen", () => {
    markSeen("welcome");
    render(true);
    expect(start).not.toHaveBeenCalled();
  });

  it("does not start when NEXT_PUBLIC_TOURS is off", () => {
    vi.stubEnv("NEXT_PUBLIC_TOURS", "off");
    render(true);
    expect(start).not.toHaveBeenCalled();
  });

  it("does not start while its first target is missing", () => {
    document.body.innerHTML = "";
    render(true);
    expect(start).not.toHaveBeenCalled();
  });

  it("starts a replay waiting for this page, even when seen or switched off", () => {
    const opener = document.createElement("button");
    markSeen("welcome");
    vi.stubEnv("NEXT_PUBLIC_TOURS", "off");
    pending = { name: "welcome", href: "/app", opener };
    render(true);
    expect(start).toHaveBeenCalledWith("welcome", opener);
    expect(clearPending).toHaveBeenCalledTimes(1);
  });

  it("leaves a replay for another tour waiting", () => {
    markSeen("welcome");
    pending = { name: "studio", href: "/studio", opener: null };
    render(true);
    expect(start).not.toHaveBeenCalled();
    expect(clearPending).not.toHaveBeenCalled();
  });

  it("does nothing outside a tour provider", () => {
    expect(() => renderHook(() => useAutoTour("welcome", true))).not.toThrow();
  });
});

describe("isSettled", () => {
  it("counts data, an error or a query that is not running as settled, and a running fetch as not", () => {
    expect(isSettled({ isPending: false, fetchStatus: "idle" })).toBe(true);
    expect(isSettled({ isPending: false, fetchStatus: "fetching" })).toBe(true);
    // A disabled query stays pending with nothing fetching.
    expect(isSettled({ isPending: true, fetchStatus: "idle" })).toBe(true);
    expect(isSettled({ isPending: true, fetchStatus: "fetching" })).toBe(false);
  });
});
