import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StageReveal } from "./stage-reveal";

type Callback = (entries: Array<{ isIntersecting: boolean }>) => void;
let observe: Callback | null = null;

function stubObserver() {
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(cb: Callback) {
        observe = cb;
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
}

function stubMotion(allowed: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: allowed && query.includes("no-preference") }));
}

function placeAt(top: number) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ top } as DOMRect);
}

const stage = () =>
  render(
    <ol>
      <StageReveal offset={0.2}>
        <span className="rail-arrive">line</span>
      </StageReveal>
    </ol>,
  ).getByRole("listitem");

describe("StageReveal", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    observe = null;
  });

  it("renders complete without an observer or matchMedia", () => {
    expect(stage()).not.toHaveAttribute("data-armed");
  });

  it("renders complete when motion is reduced", () => {
    stubObserver();
    stubMotion(false);
    placeAt(5000);
    expect(stage()).not.toHaveAttribute("data-armed");
  });

  it("renders complete when the stage is already on screen", () => {
    stubObserver();
    stubMotion(true);
    placeAt(100);
    expect(stage()).not.toHaveAttribute("data-armed");
  });

  it("leaves a stage that is partly on screen visible, even inside the observer's bottom margin", () => {
    stubObserver();
    stubMotion(true);
    vi.stubGlobal("innerHeight", 800);
    placeAt(740);
    expect(stage()).not.toHaveAttribute("data-armed");
  });

  it("arms a stage below the fold and plays it once in view", () => {
    stubObserver();
    stubMotion(true);
    placeAt(5000);
    const li = stage();
    expect(li).toHaveAttribute("data-armed");
    expect(li).not.toHaveAttribute("data-play");
    act(() => observe?.([{ isIntersecting: false }]));
    expect(li).not.toHaveAttribute("data-play");
    act(() => observe?.([{ isIntersecting: true }]));
    expect(li).toHaveAttribute("data-play");
  });
});
